"""기능 B — 빠진 관점 분석 (PRD §2 기능 B + §5.3).

흐름:
  1. 검색 (web_search) — 같은 주제 다른 매체 기사 title+snippet 5개
  2. LLM 호출 — 원본 핵심 사실 + 비교 기사들 → 빠진 사실/관점/프레이밍 JSON
  3. Pydantic 검증 + 1회 재시도

classifier.py와 같은 안정성 패턴:
  - temperature=0 + response_mime_type=application/json
  - 1차 모델(flash) → 429이면 fallback(flash-lite)
  - 파싱 실패 시 1회 재시도
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from google import genai
from google.genai import types
from pydantic import ValidationError

from ..config import settings
from ..models.schemas import Perspective, PerspectivesBlock, PerspectiveType
from .classifier import (
    ClassificationError,
    QuotaExceededError,
    _is_quota_error,
    _quota_retry_after,
)
from .web_search import SearchError, SearchResult, search_related_articles


logger = logging.getLogger(__name__)


class PerspectivesError(Exception):
    """빠진 관점 분석 실패 — 라우트가 503으로 변환."""


class PerspectivesDisabledError(PerspectivesError):
    """검색 API 키 미설정 — 503/501로 변환."""


# PRD §5.3 시스템 프롬프트를 한국 매체 비교 컨텍스트에 맞춰 보강.
# 비교 기사는 본문이 아닌 title+snippet만 들어오므로 그 제약을 명시.
_SYSTEM_PROMPT = """당신은 한국 뉴스 기사의 보도 범위를 비교 분석하는 미디어 분석 전문가입니다.

원본 기사의 핵심 사실과, 같은 주제를 다룬 다른 매체의 검색 결과(제목·요약 스니펫)를 비교하여,
원본 기사에 빠져 있을 가능성이 높은 사실·관점·프레이밍을 찾아주세요.

## 분석 유형

1. MISSING_FACT
   - 다른 매체에는 언급되나 원본에는 없는, **검증 가능한 사실** (수치·사건·일자·기관)
   - 비교 매체의 제목/스니펫에서 명확히 새로운 사실이 드러나야 함

2. MISSING_VIEWPOINT
   - 다른 매체에는 인용되나 원본에는 없는 **이해관계자의 입장**
   - 예: 원본은 사측 입장만, 비교 매체는 노조 입장; 또는 시민단체·반대 진영의 목소리

3. DIFFERENT_FRAMING
   - 같은 사실을 다른 관점·맥락으로 보도한 경우
   - 예: 원본은 "노조의 무리한 요구"로 프레이밍, 비교 매체는 "사측의 조정안 거부"로 프레이밍

## 입력 데이터의 한계

비교 매체는 **제목과 짧은 검색 스니펫만** 제공됩니다 (전체 본문 아님).
따라서:
- 스니펫에 명확히 드러나는 차이만 지적합니다 (추측·확장 해석 금지)
- 스니펫이 모호하거나 같은 내용을 반복하면, 그 매체는 건너뛰고 다음 매체로
- 빠진 관점이 명확하지 않으면 missing_perspectives를 **빈 배열**로 두는 것이 정답입니다

## 출력 규칙

- topic_summary: 이 이슈의 핵심을 1문장 (원본 핵심 사실 기반)
- missing_perspectives: 최대 5개. 각 항목은 description 1~2문장으로 구체적으로
- found_in은 출처 매체명 그대로 (예: "한겨레", "조선일보", "매일경제")
- source_url은 입력으로 받은 비교 기사 URL 중 하나를 정확히 인용
- description에는 **원본에 무엇이 없고 비교 기사에 무엇이 있는지** 대비를 명시

## 출력 형식

반드시 아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트는 포함하지 마세요.

{
  "topic_summary": "(이 이슈의 핵심 요약, 1문장)",
  "missing_perspectives": [
    {
      "type": "MISSING_FACT" | "MISSING_VIEWPOINT" | "DIFFERENT_FRAMING",
      "description": "(빠진 내용 설명, 한국어 1~2문장)",
      "found_in": "(출처 매체명)",
      "source_url": "(입력된 비교 기사 URL 중 정확히 하나)"
    }
  ]
}
"""


def _build_user_prompt(
    title: str,
    source: Optional[str],
    core_facts: list[str],
    comparisons: list[SearchResult],
) -> str:
    facts_block = "\n".join(f"- {f}" for f in core_facts) if core_facts else "(원본 핵심 사실 없음)"
    comp_lines = []
    for i, r in enumerate(comparisons, 1):
        comp_lines.append(
            f"[{i}] 매체: {r.source}\n"
            f"    제목: {r.title}\n"
            f"    스니펫: {r.snippet}\n"
            f"    URL: {r.url}"
        )
    comp_block = "\n\n".join(comp_lines) if comp_lines else "(비교 기사 없음)"

    return (
        f"[원본 기사 제목]: {title}\n"
        f"[원본 기사 출처]: {source or '(없음)'}\n"
        f"[원본 기사 핵심 사실]:\n{facts_block}\n\n"
        f"[비교 매체 검색 결과 (제목+스니펫만)]:\n{comp_block}\n\n"
        "원본 기사에 빠진 사실·관점·프레이밍을 분석해주세요."
    )


def _call_gemini(user_prompt: str, model: str) -> str:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    text = response.text
    if not text:
        raise PerspectivesError("Gemini 응답이 비어있습니다.")
    return text


def _call_gemini_with_fallback(user_prompt: str) -> tuple[str, str]:
    primary = settings.GEMINI_MODEL
    fallback = settings.GEMINI_MODEL_FALLBACK

    try:
        return _call_gemini(user_prompt, primary), primary
    except Exception as e:
        if not _is_quota_error(e) or not fallback or fallback == primary:
            raise

    logger.info("perspectives: primary %s hit quota, fallback %s", primary, fallback)
    try:
        return _call_gemini(user_prompt, fallback), fallback
    except Exception as e:
        if _is_quota_error(e):
            retry_after = _quota_retry_after(e)
            raise QuotaExceededError(
                f"무료 티어 한도 초과 (primary={primary}, fallback={fallback})",
                retry_after_sec=retry_after,
            ) from e
        raise


def _parse_and_validate(
    raw_json: str,
    valid_urls: set[str],
) -> PerspectivesBlock:
    """JSON 파싱 + source_url이 입력 URL 집합 내인지 확인 (LLM 환각 차단)."""
    data = json.loads(raw_json)
    topic = data.get("topic_summary", "").strip()
    if not topic:
        topic = "(주제 요약 없음)"

    raw_items = data.get("missing_perspectives", [])
    if not isinstance(raw_items, list):
        raw_items = []

    cleaned: list[Perspective] = []
    for item in raw_items:
        try:
            p = Perspective.model_validate(item)
        except ValidationError:
            continue
        # 환각된 URL 차단: LLM이 만든 source_url이 검색 결과에 없으면 버림
        if valid_urls and p.source_url not in valid_urls:
            logger.debug("perspective dropped — source_url not in search results: %s", p.source_url)
            continue
        cleaned.append(p)
        if len(cleaned) >= 5:
            break

    return PerspectivesBlock(topic_summary=topic, missing_perspectives=cleaned)


def analyze_perspectives(
    title: str,
    source: Optional[str],
    source_domain: Optional[str],
    core_facts: list[str],
) -> tuple[PerspectivesBlock, int, list[str]]:
    """빠진 관점 분석 진입점.

    반환: (PerspectivesBlock, 검색된 비교 기사 수, warnings)
    예외:
      - PerspectivesDisabledError: CSE 키 미설정
      - QuotaExceededError: LLM 무료 한도 초과 (primary+fallback 모두)
      - PerspectivesError: 그 외 실패
    """
    if not settings.perspectives_enabled:
        raise PerspectivesDisabledError(
            "빠진 관점 분석 기능이 비활성화돼 있습니다 (GOOGLE_CSE_API_KEY 미설정)."
        )
    if not settings.GEMINI_API_KEY:
        raise PerspectivesError("GEMINI_API_KEY가 설정되지 않았습니다.")
    if not title or not title.strip():
        raise PerspectivesError("title이 비어있어 검색을 수행할 수 없습니다.")

    warnings: list[str] = []

    try:
        comparisons = search_related_articles(
            title=title,
            exclude_domain=source_domain,
            source=source,
            limit=settings.PERSPECTIVES_MAX_RESULTS,
        )
    except SearchError as e:
        raise PerspectivesError(f"검색 실패: {e}") from e

    if not comparisons:
        warnings.append("같은 주제를 다룬 다른 매체 기사를 찾지 못했습니다.")
        return PerspectivesBlock(
            topic_summary=title.strip(),
            missing_perspectives=[],
        ), 0, warnings

    user_prompt = _build_user_prompt(title, source, core_facts, comparisons)
    valid_urls = {c.url for c in comparisons}

    last_error: Optional[Exception] = None
    for attempt in (1, 2):
        try:
            raw, used_model = _call_gemini_with_fallback(user_prompt)
            block = _parse_and_validate(raw, valid_urls)
            if used_model != settings.GEMINI_MODEL:
                logger.info("perspectives used fallback model: %s", used_model)
            return block, len(comparisons), warnings
        except QuotaExceededError:
            raise
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logger.warning("perspectives attempt %d: parse failed: %s", attempt, e)
            last_error = e
            continue
        except Exception as e:
            logger.warning("perspectives attempt %d: LLM failed: %s", attempt, e)
            last_error = e
            continue

    raise PerspectivesError(
        f"빠진 관점 분석 실패 (2회 시도). 마지막 오류: {type(last_error).__name__}"
    )
