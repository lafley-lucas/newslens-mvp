"""Gemini 기반 사실/의견 분류기 (PRD §5.1 기능A).

PRD 5.1 시스템 프롬프트와 JSON 출력 스키마를 그대로 사용한다.
LLM 백엔드만 Anthropic Claude → Google Gemini로 교체.

핵심 안정성 장치 (PRD §11):
- temperature=0 고정 + response_mime_type=application/json (일관성·강제 JSON)
- Pydantic 스키마 검증 → 1회 재시도
- 반환 index ↔ 원문 문장 매핑 검증 → 누락 시 경고
- text 필드는 LLM 반환값이 아닌 우리 원문으로 덮어쓰기 (LLM이 임의 정규화·요약하는 것 차단)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from google import genai
from google.genai import types
from pydantic import ValidationError

from ..config import settings
from ..models.schemas import AnalysisSummary, Category, ClassifiedSentence, FactDigest


logger = logging.getLogger(__name__)


class ClassificationError(Exception):
    """LLM 분류 호출이 실패했고 재시도도 실패. 라우트는 500/503으로 변환."""


# PRD §5.1 시스템 프롬프트 — 한 글자도 임의로 바꾸지 않음.
_SYSTEM_PROMPT = """당신은 한국 뉴스 기사의 사실과 의견을 구분하는 미디어 리터러시 전문가입니다.

주어진 기사 본문의 각 문장을 아래 4가지 카테고리 중 하나로 분류하고,
일반 독자가 스스로 인지하기 어려운 비사실 문장만 significant=true로 표시하세요.

## 분류 카테고리

1. FACT (사실 보도)
   - 검증 가능한 사건, 날짜, 수치, 데이터, 공식 발표
   - 예: "삼성전자 노사 임금협상이 20일 결렬됐다."

2. CLAIM (인용·주장)
   - 특정 주체(인물, 기관, 단체)의 발언이나 입장을 인용한 것
   - "~라고 밝혔다", "~라고 주장했다", "~에 따르면" 등의 인용 표지가 있음
   - 인용 행위 자체는 사실이지만, 인용된 내용은 해당 주체의 주장임을 구분
   - 예: "노조는 '사측이 조정안을 거부했다'고 밝혔다."

3. OPINION (의견·해석)
   - 기자 또는 매체의 주관적 판단, 분석, 예측, 평가
   - "~할 것으로 보인다", "~할 전망이다", "~이 우려된다" 등의 해석 표현
   - 형용사/부사가 주관적 평가를 담는 경우: "무리한", "과도한", "획기적인"
   - 예: "이번 사태는 예견된 파국이었다."

4. FRAMING (프레이밍)
   - 명시적 의견은 아니지만, 단어 선택·어순·강조를 통해 특정 인식을 유도
   - "떼쓰는", "긴급히", "강경", "졸속" 등 감정·방향성을 함축하는 단어
   - 특정 사실만 선택적으로 강조하거나 배치하는 것
   - 예: "노조가 또다시 강경 투쟁에 나섰다."

## 한국 언론 특유 표현 패턴 (실제 감지 대상)

한국 뉴스에는 의견을 사실처럼 포장하는 특유의 관용적 표현이 존재합니다.
아래 패턴은 significant=true로 표시할 가능성이 높습니다:

- "~로 알려졌다" → 출처 불명의 정보를 기정사실화
- "~라는 지적이 나온다" / "~라는 우려가 나온다" → 익명의 권위를 빌린 의견 주입
- "~라는 분석이다" / "~라는 관측이 나온다" → 출처 없는 해석을 사실화
- "~할 것으로 전망된다" (출처 없이) → 기자 자신의 전망을 객관적 예측처럼 포장
- "~라는 시각도 있다" → 소수 의견을 마치 다수인 것처럼 인용
- "~에 나서야 한다는 목소리가 높다" → 출처 불명의 당위성 주장

## 의미도(Significance) 판정 기준

각 비사실(CLAIM/OPINION/FRAMING) 문장에 대해 significant 필드를 판정합니다.
"일반 독자가 이 문장의 비사실성을 스스로 인지하기 어려운가?"가 핵심 질문입니다.

significant = true:
- 사실 보도처럼 읽히지만 실제로는 한쪽 입장이거나 기자 해석이 섞인 문장
- 위 "한국 언론 특유 표현 패턴"에 해당하는 문장
- 한쪽 이해관계자의 주장만 인용되고 반대쪽 입장이 기사 전체에서 부재한 경우
- 독자가 눈치채기 어려운 단어 선택 프레이밍

significant = false:
- "~할 것으로 보인다", "~할 전망이다" 등 누구나 의견임을 인지하는 관용적 전망 표현
- "~에 나섰다", "~에 밝혔다" 등 기사 문체상 자연스러운 관용적 표현
- 양쪽 입장이 균형 있게 인용된 인용문
- 기사 구조상 자연스러운 요약·전환 문장

FACT 문장은 항상 significant = false (사실은 하이라이트 대상이 아님)

## 판단 원칙

- 애매한 경우, 더 높은(더 주관적인) 카테고리로 분류합니다
- 한 문장에 사실과 의견이 섞여 있으면, 더 지배적인 요소로 분류하되 rationale에 혼합 사실을 명시합니다
- confidence는 0.0~1.0 사이 값으로, 분류 확신도를 나타냅니다
- rationale은 한국어 1~2문장으로 작성. significant=true인 경우 "왜 독자가 인지하기 어려운지"를 포함합니다

## 출력 형식

반드시 아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트는 포함하지 마세요.

{
  "sentences": [
    {
      "index": (문장 번호, 1부터 시작),
      "text": "(원문 문장)",
      "category": "FACT" | "CLAIM" | "OPINION" | "FRAMING",
      "confidence": (0.0~1.0),
      "significant": (true | false),
      "rationale": "(분류 이유, 한국어 1~2문장)"
    }
  ]
}
"""


def _build_user_prompt(
    title: Optional[str],
    source: Optional[str],
    sentences: list[str],
) -> str:
    indexed = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    return (
        "아래 뉴스 기사의 각 문장을 분류해주세요. "
        "각 문장 앞에 붙은 번호를 그대로 JSON의 index로 사용하세요.\n\n"
        f"[기사 제목]: {title or '(없음)'}\n"
        f"[기사 출처]: {source or '(없음)'}\n"
        f"[기사 문장 목록]:\n{indexed}\n"
    )


def _call_gemini(user_prompt: str) -> str:
    """단일 Gemini 호출. JSON 문자열 반환. 실패 시 예외 전파."""
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    text = response.text
    if not text:
        raise ClassificationError("Gemini 응답이 비어있습니다.")
    return text


def _parse_and_validate(
    raw_json: str,
    expected_sentences: list[str],
) -> list[ClassifiedSentence]:
    """JSON 파싱 + 스키마 검증 + index→원문 매핑. 실패하면 ValueError/ValidationError."""
    data = json.loads(raw_json)
    items = data.get("sentences")
    if not isinstance(items, list):
        raise ValueError("응답에 'sentences' 배열이 없습니다.")

    classified: list[ClassifiedSentence] = []
    n = len(expected_sentences)
    seen: set[int] = set()
    for item in items:
        cs = ClassifiedSentence.model_validate(item)
        if cs.index < 1 or cs.index > n:
            continue  # 범위 밖 인덱스는 버림
        if cs.index in seen:
            continue  # 중복 인덱스 버림
        seen.add(cs.index)
        # FACT는 항상 significant=false (PRD §2 불변식)
        if cs.category == Category.FACT and cs.significant:
            cs = cs.model_copy(update={"significant": False})
        # text는 우리 원문으로 강제 — LLM이 임의로 정규화·요약 못 하게.
        cs = cs.model_copy(update={"text": expected_sentences[cs.index - 1]})
        classified.append(cs)

    classified.sort(key=lambda c: c.index)
    return classified


def classify_sentences(
    title: Optional[str],
    source: Optional[str],
    sentences: list[str],
) -> tuple[list[ClassifiedSentence], list[str]]:
    """문장 리스트를 LLM에 보내 분류 결과 + 경고 메시지 반환.

    예외 시 ClassificationError. 부분 누락은 예외가 아니라 warnings에 기록.
    """
    if not sentences:
        return [], []

    if not settings.GEMINI_API_KEY:
        raise ClassificationError(
            "GEMINI_API_KEY가 설정되지 않았습니다. backend/.env 파일을 확인해주세요."
        )

    user_prompt = _build_user_prompt(title, source, sentences)
    warnings: list[str] = []
    last_error: Optional[Exception] = None

    for attempt in (1, 2):
        try:
            raw = _call_gemini(user_prompt)
            classified = _parse_and_validate(raw, sentences)
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logger.warning("classify attempt %d: parse/validate failed: %s", attempt, e)
            last_error = e
            continue
        except Exception as e:
            logger.warning("classify attempt %d: LLM call failed: %s", attempt, e)
            last_error = e
            continue

        missing = [i for i in range(1, len(sentences) + 1)
                   if not any(c.index == i for c in classified)]
        if missing and attempt == 1:
            logger.info("classify attempt 1: %d sentences missing, retrying", len(missing))
            continue
        if missing:
            warnings.append(
                f"일부 문장({len(missing)}개)의 분석이 누락됐습니다. 결과 표시는 가능합니다."
            )

        return classified, warnings

    raise ClassificationError(
        f"LLM 분류에 실패했습니다 (2회 시도). 마지막 오류: {type(last_error).__name__}"
    )


# =========================================================================
# 기능 D: Fact Digest (PRD §5.2)
# =========================================================================

_DIGEST_SYSTEM_PROMPT = """당신은 뉴스 기사에서 핵심 사실만 추출하여 간결하게 요약하는 전문가입니다.

아래 문장들은 뉴스 기사에서 '사실 보도'로 분류된 문장들입니다.
이 문장들만을 바탕으로 기사의 핵심 내용을 3~5개 항목으로 요약하세요.

## 규칙
- 의견, 해석, 전망, 프레이밍은 절대 포함하지 않습니다
- 검증 가능한 사실(누가, 언제, 무엇을, 어떤 수치로)만 남깁니다
- 각 항목은 1줄, 간결한 한국어 문장으로 작성합니다
- 기사를 읽지 않은 사람도 "무슨 일이 있었는지" 핵심을 파악할 수 있어야 합니다

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요.

{
  "core_facts": [
    "(핵심 사실 1)",
    "(핵심 사실 2)",
    "(핵심 사실 3)"
  ]
}
"""


def build_fact_digest(
    title: Optional[str],
    sentences: list[ClassifiedSentence],
) -> FactDigest:
    """FACT 문장만 모아 LLM으로 핵심 사실 요약. 실패해도 빈 digest 반환 (분류는 살리기)."""
    fact_sentences = [s for s in sentences if s.category == Category.FACT]
    fact_indices = [s.index for s in fact_sentences]

    if len(fact_sentences) < 2:
        # FACT가 0~1개면 요약 의미 없음 — 있는 그대로 둠.
        core = [s.text for s in fact_sentences]
        return FactDigest(core_facts=core, fact_sentence_indices=fact_indices)

    if not settings.GEMINI_API_KEY:
        # 분류는 이미 성공한 상태라 여기서 에러 띄우면 분류 결과까지 못 봄. 폴백.
        return FactDigest(core_facts=[s.text for s in fact_sentences[:5]],
                          fact_sentence_indices=fact_indices)

    indexed = "\n".join(f"{s.index}. {s.text}" for s in fact_sentences)
    user_prompt = (
        "아래는 뉴스 기사에서 사실로 분류된 문장들입니다. 핵심만 3~5개로 요약해주세요.\n\n"
        f"[기사 제목]: {title or '(없음)'}\n"
        f"[사실 문장들]:\n{indexed}\n"
    )

    for attempt in (1, 2):
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_DIGEST_SYSTEM_PROMPT,
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            raw = response.text
            if not raw:
                raise ValueError("empty response")
            data = json.loads(raw)
            facts = data.get("core_facts")
            if not isinstance(facts, list) or not all(isinstance(f, str) for f in facts):
                raise ValueError("core_facts is not a list[str]")
            return FactDigest(
                core_facts=[f.strip() for f in facts if f.strip()][:5],
                fact_sentence_indices=fact_indices,
            )
        except Exception as e:
            logger.warning("fact_digest attempt %d failed: %s", attempt, e)

    # 두 번 모두 실패 → 원문 FACT 문장으로 폴백. 사용자에게 0개보다 낫다.
    logger.error("fact_digest failed twice, falling back to raw FACT sentences")
    return FactDigest(
        core_facts=[s.text for s in fact_sentences[:5]],
        fact_sentence_indices=fact_indices,
    )


def compute_summary(sentences: list[ClassifiedSentence]) -> AnalysisSummary:
    """PRD §2 analysis_summary 계산."""
    n = len(sentences)
    fact = sum(1 for s in sentences if s.category == Category.FACT)
    claim = sum(1 for s in sentences if s.category == Category.CLAIM)
    opinion = sum(1 for s in sentences if s.category == Category.OPINION)
    framing = sum(1 for s in sentences if s.category == Category.FRAMING)
    significant = sum(1 for s in sentences if s.significant)
    return AnalysisSummary(
        total_sentences=n,
        fact_count=fact,
        claim_count=claim,
        opinion_count=opinion,
        framing_count=framing,
        fact_ratio=round(fact / n, 4) if n else 0.0,
        significant_highlights=significant,
    )
