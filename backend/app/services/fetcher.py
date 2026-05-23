"""URL → 기사 본문 추출.

추출 전략 (PRD §13 Day 1 벤치마크 결정):
1. trafilatura — 가벼움, 한겨레/네이버 등 표준 SSR에 강함
2. newspaper4k — DOM 셀렉터 휴리스틱이 다름, 일부 매체에서 더 잘 붙음
3. fusion — Arc Publishing(조선닷컴 등) 전용. 본문이 `Fusion.globalContent` JS 객체에 박힌 케이스

같은 HTML을 두 번 fetch하지 않도록 같은 raw HTML을 세 파서가 공유한다.

Day 2에 SSRF 차단 + 도메인 화이트리스트 + rate limit 추가 예정 (PRD §11).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx
import trafilatura
from newspaper import Article as NewspaperArticle
from newspaper.article import ArticleException
from trafilatura.settings import use_config

from ..config import settings
from .fusion_parser import extract_fusion_content
from .url_guard import UnsafeUrlError, validate_url


logger = logging.getLogger(__name__)

_TRAFILATURA_CFG = use_config()
_TRAFILATURA_CFG.set("DEFAULT", "MIN_EXTRACTED_SIZE", "200")
_TRAFILATURA_CFG.set("DEFAULT", "MIN_OUTPUT_SIZE", "200")
_TRAFILATURA_CFG.set("DEFAULT", "EXTRACTION_TIMEOUT", "10")

_MIN_BODY_CHARS = 50


class FetchError(Exception):
    """URL fetch 또는 본문 추출 실패. 메시지는 사용자에게 그대로 보여줄 수 있음."""


@dataclass
class ParsedArticle:
    title: Optional[str]
    text: str
    author: Optional[str]
    date: Optional[str]
    source: Optional[str]
    url: Optional[str]
    parser: str  # "trafilatura" | "newspaper4k" | "text_input"


def _fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36 NewsLens/0.1"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    }
    try:
        with httpx.Client(
            timeout=settings.HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = client.get(url)
    except httpx.TimeoutException as e:
        raise FetchError("기사 페이지 응답 시간이 초과됐습니다.") from e
    except httpx.HTTPError as e:
        raise FetchError(f"기사 페이지 요청에 실패했습니다: {type(e).__name__}") from e

    if resp.status_code >= 400:
        raise FetchError(
            f"기사 페이지가 차단되었거나 접근할 수 없습니다 (HTTP {resp.status_code})."
        )

    return resp.text


def extract_from_url(url: str) -> ParsedArticle:
    try:
        safe = validate_url(url)
    except UnsafeUrlError as e:
        raise FetchError(str(e)) from e

    html = _fetch_html(safe.original)

    try:
        return _extract_trafilatura(html, url)
    except FetchError as e_traf:
        logger.info("trafilatura failed for %s (%s); trying newspaper4k", url, e_traf)

    try:
        return _extract_newspaper(html, url)
    except FetchError as e_news:
        logger.info("newspaper4k failed for %s (%s); trying fusion", url, e_news)

    try:
        return _extract_fusion(html, url)
    except FetchError as e_fusion:
        raise FetchError(
            "본문을 추출하지 못했습니다. 기사 본문을 직접 붙여넣어 주세요."
        ) from e_fusion


def extract_from_text(text: str, source: Optional[str] = None) -> ParsedArticle:
    cleaned = text.strip()
    if len(cleaned) > settings.MAX_ARTICLE_CHARS:
        cleaned = cleaned[: settings.MAX_ARTICLE_CHARS]
    return ParsedArticle(
        title=None,
        text=cleaned,
        author=None,
        date=None,
        source=source,
        url=None,
        parser="text_input",
    )


def _extract_trafilatura(html: str, url: Optional[str]) -> ParsedArticle:
    body = trafilatura.extract(
        html,
        config=_TRAFILATURA_CFG,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not body or len(body.strip()) < _MIN_BODY_CHARS:
        raise FetchError("trafilatura: 본문이 너무 짧거나 비어있습니다.")

    meta = trafilatura.extract_metadata(html)
    return ParsedArticle(
        title=getattr(meta, "title", None) if meta else None,
        text=body.strip(),
        author=getattr(meta, "author", None) if meta else None,
        date=getattr(meta, "date", None) if meta else None,
        source=getattr(meta, "sitename", None) if meta else None,
        url=url,
        parser="trafilatura",
    )


def _extract_newspaper(html: str, url: Optional[str]) -> ParsedArticle:
    article = NewspaperArticle(url or "", language="ko")
    try:
        article.download(input_html=html)
        article.parse()
    except ArticleException as e:
        raise FetchError(f"newspaper4k: 파싱 실패 ({e})") from e

    text = (article.text or "").strip()
    if len(text) < _MIN_BODY_CHARS:
        raise FetchError("newspaper4k: 본문이 너무 짧거나 비어있습니다.")

    date_str: Optional[str] = None
    if article.publish_date is not None:
        date_str = article.publish_date.date().isoformat()

    authors = "; ".join(article.authors) if article.authors else None

    return ParsedArticle(
        title=article.title or None,
        text=text,
        author=authors,
        date=date_str,
        source=article.meta_data.get("og:site_name") if article.meta_data else None,
        url=url,
        parser="newspaper4k",
    )


def _extract_fusion(html: str, url: Optional[str]) -> ParsedArticle:
    """Arc Publishing(Fusion) 본문 추출. 메타데이터가 부족하면 newspaper4k 결과로 보강."""
    fusion = extract_fusion_content(html)
    if fusion is None or len(fusion.text) < _MIN_BODY_CHARS:
        raise FetchError("fusion: Arc 패턴을 찾지 못했거나 본문이 너무 짧습니다.")

    # 메타데이터는 Fusion JSON이 우선, 누락된 필드는 newspaper4k로 채워넣는다.
    title, author, date, source = fusion.title, fusion.author, fusion.date, None
    if not (title and author and date):
        try:
            backup = NewspaperArticle(url or "", language="ko")
            backup.download(input_html=html)
            backup.parse()
            title = title or (backup.title or None)
            if not author and backup.authors:
                author = "; ".join(backup.authors)
            if not date and backup.publish_date is not None:
                date = backup.publish_date.date().isoformat()
            if backup.meta_data:
                source = backup.meta_data.get("og:site_name") or None
        except Exception as e:
            logger.debug("fusion metadata backup failed: %s", e)

    return ParsedArticle(
        title=title,
        text=fusion.text,
        author=author,
        date=date,
        source=source,
        url=url,
        parser="fusion",
    )
