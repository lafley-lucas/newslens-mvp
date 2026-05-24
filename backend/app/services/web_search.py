"""웹 검색 — Google Custom Search JSON API (PRD §6 기능 B용).

설계 의도:
- 비교 기사의 **본문은 fetch 하지 않는다**. title + snippet만 가져와서 LLM에 전달.
  PRD §8/§15에 명시된 "비교 기사 추출 시 anti-bot 차단 N배 증폭" 리스크 회피.
  본문이 필요하면 v1.2에서 별도 워커로 분리.
- 원본 기사와 같은 도메인은 제외 (같은 매체 자기인용 의미 없음).
- 검색 API 키가 없으면 빈 리스트 반환 — 호출자가 graceful degradation.

Google Custom Search 무료 한도: 100건/일. 캐시 + rate limit로 충분.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..config import settings


logger = logging.getLogger(__name__)


_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


class SearchError(Exception):
    """검색 호출 자체 실패 — 호출자는 빈 결과로 처리해도 됨."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    snippet: str
    url: str
    source: str  # 매체명 (display_link 또는 도메인)


def _domain(url: str) -> Optional[str]:
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    # www. 접두어는 비교 시 동등하게 본다
    return host.lower().lstrip(".").removeprefix("www.")


def _build_query(title: str, source: Optional[str]) -> str:
    """기사 제목을 그대로 검색어로. 매체명은 제외 연산자로 빼면 결과가 너무 좁아져 사용 X.
    제목 길이가 너무 길면 앞 80자만.
    """
    q = title.strip()
    if len(q) > 80:
        q = q[:80]
    return q


def search_related_articles(
    title: str,
    exclude_domain: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 5,
) -> list[SearchResult]:
    """제목으로 관련 기사 검색. 같은 도메인 제외 후 상위 limit개 반환.

    실패 시 SearchError 전파. 키 미설정 시 빈 리스트.
    """
    if not settings.perspectives_enabled:
        logger.info("CSE 키가 설정되지 않음 — 검색 스킵")
        return []

    query = _build_query(title, source)
    params = {
        "key": settings.GOOGLE_CSE_API_KEY,
        "cx": settings.GOOGLE_CSE_ID,
        "q": query,
        "num": 10,  # 도메인 필터링 후 limit만큼 남기려면 여유 있게
        "hl": "ko",
        "lr": "lang_ko",
    }

    try:
        with httpx.Client(timeout=settings.PERSPECTIVES_SEARCH_TIMEOUT) as client:
            resp = client.get(_CSE_ENDPOINT, params=params)
    except httpx.TimeoutException as e:
        raise SearchError("검색 응답 시간 초과") from e
    except httpx.HTTPError as e:
        raise SearchError(f"검색 요청 실패: {type(e).__name__}") from e

    if resp.status_code == 429:
        raise SearchError("검색 API 일일 한도 초과 (429)")
    if resp.status_code >= 400:
        # 400류는 본문에 에러가 들어있을 수 있음
        try:
            err = resp.json().get("error", {}).get("message", "")
        except Exception:
            err = ""
        raise SearchError(f"검색 API 오류 HTTP {resp.status_code}: {err}")

    try:
        data = resp.json()
    except ValueError as e:
        raise SearchError("검색 응답 JSON 파싱 실패") from e

    items = data.get("items", [])
    if not isinstance(items, list):
        return []

    exclude_norm = (exclude_domain or "").lower().removeprefix("www.")
    results: list[SearchResult] = []
    for item in items:
        url = item.get("link") or ""
        if not url:
            continue
        domain = _domain(url)
        if not domain:
            continue
        if exclude_norm and (domain == exclude_norm or domain.endswith("." + exclude_norm)):
            continue
        title_v = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        if not title_v:
            continue
        display = item.get("displayLink") or domain
        results.append(SearchResult(
            title=title_v,
            snippet=snippet,
            url=url,
            source=display,
        ))
        if len(results) >= limit:
            break

    return results
