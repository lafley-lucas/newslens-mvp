from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..models.schemas import (
    AnalysisBlock,
    AnalyzeResponse,
    ArticleMeta,
    ExtractRequest,
    ExtractResponse,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackType,
    PerspectivesRequest,
    PerspectivesResponse,
    Sentence,
)
from ..services import cache, content_guard, db, in_flight
from ..services.classifier import (
    ClassificationError,
    QuotaExceededError,
    analyze_article,
    compute_summary,
)
from ..services.fetcher import (
    FetchError,
    ParsedArticle,
    extract_from_text,
    extract_from_url,
)
from ..services.perspectives import (
    PerspectivesDisabledError,
    PerspectivesError,
    analyze_perspectives,
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

    # 너무 짧은 기사 차단 (PRD §11)
    if content_guard.too_short(sentences):
        raise HTTPException(
            status_code=422,
            detail=f"본문이 너무 짧습니다 (최소 {content_guard.MIN_SENTENCES}문장 필요).",
        )

    # 비한국어 차단 (PRD §11)
    if not content_guard.is_korean(article.text):
        raise HTTPException(
            status_code=422,
            detail="현재 한국어 기사만 지원합니다. 한국어 비율이 너무 낮습니다.",
        )

    return article, sentences


def _article_meta(article: ParsedArticle, req: ExtractRequest) -> ArticleMeta:
    url_hash = in_flight.url_key(article.url) if article.url else None
    return ArticleMeta(
        title=article.title,
        source=article.source or req.source,
        date=article.date,
        author=article.author,
        url=article.url,
        url_hash=url_hash,
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

    # 오피니언/칼럼 1차 판별 → meta.type 표시
    notices: list[str] = []
    if content_guard.detect_opinion(url_str, meta.title):
        meta.type = "opinion"
        notices.append(
            "이 글은 칼럼·사설(오피니언) 콘텐츠로 보입니다. 분석은 진행되지만 "
            "원래 의견 중심으로 작성된 글이므로 의견·프레이밍 비율이 자연스럽게 높습니다."
        )

    try:
        classified, fact_digest, llm_warnings = analyze_article(
            title=meta.title,
            source=meta.source,
            sentences=sentences,
        )
    except QuotaExceededError as e:
        retry = e.retry_after_sec or 60
        raise HTTPException(
            status_code=429,
            detail=(
                f"AI 분석 한도가 일시적으로 초과됐습니다. "
                f"약 {retry}초 후 다시 시도해주세요."
            ),
            headers={"Retry-After": str(retry)},
        )
    except ClassificationError as e:
        raise HTTPException(status_code=503, detail=f"분석 중 오류 발생: {e}")

    warnings.extend(llm_warnings)
    summary = compute_summary(classified)

    # 분류 결과 기반 2차 오피니언 휴리스틱: opinion+framing이 60%↑면 사설 류로 추정
    if meta.type != "opinion" and summary.total_sentences > 0:
        op_fr_ratio = (summary.opinion_count + summary.framing_count) / summary.total_sentences
        if op_fr_ratio >= 0.60:
            meta.type = "opinion"
            notices.append(
                "분류 결과 의견·프레이밍 비율이 매우 높습니다 (60% 이상). "
                "이 글이 사설·칼럼이라면 정상이며, 일반 보도라면 주의해서 읽어주세요."
            )

    # significant=0 안내 (PRD §11)
    if summary.significant_highlights == 0 and meta.type == "news":
        notices.append(
            "분석 모드에서 강조할 비사실 문장이 없습니다. 이 기사는 사실 중심이거나 "
            "양쪽 입장이 균형 있게 인용된 것으로 보입니다."
        )

    return AnalyzeResponse(
        article=meta,
        parser=article.parser,
        analysis=AnalysisBlock(
            summary=summary,
            fact_digest=fact_digest,
            sentences=classified,
        ),
        warnings=warnings,
        notices=notices,
    )


# =========================================================================
# Day 10: 피드백 수집 (PRD §10 §15 — 원문 절대 미저장)
# =========================================================================

@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    dependencies=[Depends(check_rate_limit)],
)
def submit_feedback(req: FeedbackRequest) -> FeedbackResponse:
    """사용자 피드백 수집.

    데이터 정책:
    - article_url_hash만 저장 (원문 URL 절대 미저장)
    - sentence_index + original/suggested category만 저장
    - 원문 문장 텍스트 미저장
    - timestamp는 DB가 자동 (CURRENT_TIMESTAMP)
    """
    # 단순 thumbs면 suggested_category 무시
    suggested = req.suggested_category
    if req.feedback_type != FeedbackType.CATEGORY_CORRECTION:
        suggested = None

    # category_correction이면 suggested_category 필수
    if req.feedback_type == FeedbackType.CATEGORY_CORRECTION and suggested is None:
        raise HTTPException(
            status_code=400,
            detail="category_correction 피드백에는 suggested_category가 필요합니다.",
        )

    fid = db.insert_feedback(
        article_url_hash=req.article_url_hash,
        sentence_index=req.sentence_index,
        original_category=req.original_category.value,
        feedback_type=req.feedback_type.value,
        suggested_category=suggested.value if suggested else None,
    )
    return FeedbackResponse(id=fid)


# =========================================================================
# 기능 B — 빠진 관점 분석 (PRD §2 기능 B + §5.3)
# =========================================================================

_PERSPECTIVES_CACHE_PREFIX = "persp:"


@router.post(
    "/perspectives",
    response_model=PerspectivesResponse,
    dependencies=[Depends(check_rate_limit)],
)
def perspectives(req: PerspectivesRequest) -> PerspectivesResponse:
    """기능 B — 빠진 관점 분석.

    프론트는 /api/analyze 결과를 받은 직후 비동기로 이 엔드포인트를 호출한다.
    article_url_hash를 기준으로 24h 캐시. 동일 hash 동시 처리 락.

    검색 API 키 미설정 시 501 — 프론트는 카드 자체를 숨김.
    """
    cache_key = _PERSPECTIVES_CACHE_PREFIX + req.article_url_hash

    # 1차 캐시 조회 — 락 없이 빠른 경로
    hit = _load_perspectives_cache(cache_key)
    if hit is not None:
        return hit

    try:
        with in_flight.acquire(cache_key):
            # 락 안에서 2차 조회
            hit = _load_perspectives_cache(cache_key)
            if hit is not None:
                return hit

            try:
                block, n, warnings = analyze_perspectives(
                    title=req.title,
                    source=req.source,
                    source_domain=req.source_domain,
                    core_facts=req.core_facts,
                )
            except PerspectivesDisabledError as e:
                # 키 미설정 — 501 Not Implemented로 프론트가 카드 숨김
                raise HTTPException(status_code=501, detail=str(e))
            except QuotaExceededError as e:
                retry = e.retry_after_sec or 60
                raise HTTPException(
                    status_code=429,
                    detail=f"AI 분석 한도가 일시적으로 초과됐습니다. 약 {retry}초 후 다시 시도해주세요.",
                    headers={"Retry-After": str(retry)},
                )
            except PerspectivesError as e:
                raise HTTPException(status_code=503, detail=f"빠진 관점 분석 실패: {e}")

            response = PerspectivesResponse(
                perspectives=block,
                warnings=warnings,
                search_results_count=n,
            )
            cache.set(cache_key, response.model_dump(mode="json"))
            return response
    except in_flight.AlreadyInFlight:
        raise HTTPException(
            status_code=409,
            detail="이 기사는 이미 빠진 관점 분석 중입니다. 잠시 후 다시 시도해주세요.",
        )


def _load_perspectives_cache(cache_key: str) -> PerspectivesResponse | None:
    cached_dump = cache.get(cache_key)
    if cached_dump is None:
        return None
    resp = PerspectivesResponse.model_validate(cached_dump)
    resp.cached = True
    return resp
