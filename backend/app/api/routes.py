from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..models.schemas import (
    AnalysisBlock,
    AnalyzeResponse,
    ArticleMeta,
    ExtractRequest,
    ExtractResponse,
    Sentence,
)
from ..services import cache, in_flight
from ..services.classifier import (
    ClassificationError,
    analyze_article,
    compute_summary,
)
from ..services.fetcher import (
    FetchError,
    ParsedArticle,
    extract_from_text,
    extract_from_url,
)
from ..services.rate_limiter import check_rate_limit
from ..services.splitter import split_sentences


router = APIRouter(prefix="/api", tags=["extract"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post(
    "/extract",
    response_model=ExtractResponse,
    dependencies=[Depends(check_rate_limit)],
)
def extract(req: ExtractRequest) -> ExtractResponse:
    """Day 1 산출물: URL 또는 텍스트 → 메타데이터 + 문장 리스트.

    Day 2: SSRF 차단, IP rate limit, 동일 URL 동시처리 락.
    Day 3에 LLM 분류를 붙여 /api/analyze로 확장 예정.
    """
    if not req.has_input():
        raise HTTPException(status_code=400, detail="url 또는 text 중 하나는 필수입니다.")

    url_str = str(req.url) if req.url is not None else None
    lock_key = in_flight.url_key(url_str) if url_str else None

    try:
        with in_flight.acquire(lock_key):
            return _do_extract(req, url_str)
    except in_flight.AlreadyInFlight:
        raise HTTPException(
            status_code=409,
            detail="이 기사는 이미 분석 중입니다. 잠시 후 다시 시도해주세요.",
        )


def _do_extract(req: ExtractRequest, url_str: str | None) -> ExtractResponse:
    article, sentences = _fetch_and_split(req, url_str)
    sentence_objs = [Sentence(index=i + 1, text=s) for i, s in enumerate(sentences)]
    return ExtractResponse(
        article=_article_meta(article, req),
        sentences=sentence_objs,
        total_sentences=len(sentence_objs),
        parser=article.parser,
    )


def _fetch_and_split(req: ExtractRequest, url_str: str | None) -> tuple[ParsedArticle, list[str]]:
    try:
        if url_str is not None:
            article = extract_from_url(url_str)
        else:
            assert req.text is not None
            article = extract_from_text(req.text, source=req.source)
    except FetchError as e:
        raise HTTPException(status_code=422, detail=str(e))

    sentences = split_sentences(article.text)
    if not sentences:
        raise HTTPException(status_code=422, detail="본문에서 문장을 추출하지 못했습니다.")
    return article, sentences


def _article_meta(article: ParsedArticle, req: ExtractRequest) -> ArticleMeta:
    return ArticleMeta(
        title=article.title,
        source=article.source or req.source,
        date=article.date,
        author=article.author,
        url=article.url,
    )


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    dependencies=[Depends(check_rate_limit)],
)
def analyze(req: ExtractRequest) -> AnalyzeResponse:
    """추출 + 사실/의견 분류 + Fact Digest (PRD §10).

    Day 5부터 URL 캐시(TTL 24h) 적용. 텍스트 직접 입력은 캐시 제외.
    """
    if not req.has_input():
        raise HTTPException(status_code=400, detail="url 또는 text 중 하나는 필수입니다.")

    url_str = str(req.url) if req.url is not None else None
    cache_key = in_flight.url_key(url_str) if url_str else None

    # 1차 캐시 조회 — 락 없이 빠른 경로
    if cache_key:
        hit = _load_from_cache(cache_key)
        if hit is not None:
            return hit

    try:
        with in_flight.acquire(cache_key):
            # 락 안에서 2차 조회 — 직전에 다른 요청이 채워뒀을 수 있음
            if cache_key:
                hit = _load_from_cache(cache_key)
                if hit is not None:
                    return hit

            response = _do_analyze(req, url_str)

            if cache_key:
                cache.set(cache_key, response.model_dump(mode="json"))

            return response
    except in_flight.AlreadyInFlight:
        raise HTTPException(
            status_code=409,
            detail="이 기사는 이미 분석 중입니다. 잠시 후 다시 시도해주세요.",
        )


def _load_from_cache(cache_key: str) -> AnalyzeResponse | None:
    cached_dump = cache.get(cache_key)
    if cached_dump is None:
        return None
    resp = AnalyzeResponse.model_validate(cached_dump)
    resp.cached = True
    return resp


def _do_analyze(req: ExtractRequest, url_str: str | None) -> AnalyzeResponse:
    article, sentences = _fetch_and_split(req, url_str)

    warnings: list[str] = []
    if len(sentences) > settings.MAX_SENTENCES_PER_REQUEST:
        warnings.append(
            f"기사가 길어 앞 {settings.MAX_SENTENCES_PER_REQUEST}문장만 분석합니다. "
            f"전체 {len(sentences)}문장 중 일부."
        )
        sentences = sentences[: settings.MAX_SENTENCES_PER_REQUEST]

    meta = _article_meta(article, req)

    try:
        classified, fact_digest, llm_warnings = analyze_article(
            title=meta.title,
            source=meta.source,
            sentences=sentences,
        )
    except ClassificationError as e:
        raise HTTPException(status_code=503, detail=f"분석 중 오류 발생: {e}")

    warnings.extend(llm_warnings)
    summary = compute_summary(classified)

    return AnalyzeResponse(
        article=meta,
        parser=article.parser,
        analysis=AnalysisBlock(
            summary=summary,
            fact_digest=fact_digest,
            sentences=classified,
        ),
        warnings=warnings,
    )
