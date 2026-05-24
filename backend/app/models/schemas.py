from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


class Category(str, Enum):
    FACT = "FACT"
    CLAIM = "CLAIM"
    OPINION = "OPINION"
    FRAMING = "FRAMING"


class ExtractRequest(BaseModel):
    """URL 또는 text 중 하나는 필수. /api/extract와 /api/analyze 공통."""
    url: Optional[HttpUrl] = None
    text: Optional[str] = Field(default=None, min_length=10)
    source: Optional[str] = None

    def has_input(self) -> bool:
        return self.url is not None or bool(self.text and self.text.strip())


class ArticleMeta(BaseModel):
    title: Optional[str] = None
    source: Optional[str] = None
    date: Optional[str] = None
    author: Optional[str] = None
    url: Optional[str] = None
    url_hash: Optional[str] = None  # 피드백 식별자 (원문 URL은 미전송, hash만)
    type: str = "news"  # "news" | "opinion" — 칼럼/사설로 보이면 "opinion"


class Sentence(BaseModel):
    """추출만 끝난 문장 (분류 전)."""
    index: int
    text: str


class ClassifiedSentence(BaseModel):
    """LLM 분류까지 마친 문장 — PRD §2 출력 스키마."""
    index: int
    text: str
    category: Category
    confidence: float = Field(ge=0.0, le=1.0)
    significant: bool
    rationale: str


class AnalysisSummary(BaseModel):
    """PRD §2 analysis_summary."""
    total_sentences: int
    fact_count: int
    claim_count: int
    opinion_count: int
    framing_count: int
    fact_ratio: float
    significant_highlights: int


class FactDigest(BaseModel):
    """PRD §2 기능 D — FACT 문장만 모아 3~5줄 핵심 사실 요약."""
    core_facts: list[str]
    fact_sentence_indices: list[int]


class AnalysisBlock(BaseModel):
    summary: AnalysisSummary
    fact_digest: FactDigest
    sentences: list[ClassifiedSentence]


class ExtractResponse(BaseModel):
    status: str = "success"
    article: ArticleMeta
    sentences: list[Sentence]
    total_sentences: int
    parser: str  # trafilatura | newspaper4k | fusion | text_input


class AnalyzeResponse(BaseModel):
    """PRD §10 POST /api/analyze 응답 구조."""
    status: str = "success"
    article: ArticleMeta
    parser: str
    analysis: AnalysisBlock
    warnings: list[str] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)  # 사용자에게 보여줄 안내 (opinion, 한국어 비율 등)
    cached: bool = False  # Day 5: URL 캐시 히트 여부


class ErrorResponse(BaseModel):
    status: str = "error"
    code: str
    message: str


# =========================================================================
# 피드백 (Day 10) — PRD §10 §15: 원문 텍스트/URL은 절대 저장하지 않음
# =========================================================================

class FeedbackType(str, Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    CATEGORY_CORRECTION = "category_correction"


class FeedbackRequest(BaseModel):
    article_url_hash: str = Field(min_length=8, max_length=128)
    sentence_index: int = Field(ge=1)
    original_category: Category
    feedback_type: FeedbackType
    suggested_category: Optional[Category] = None


class FeedbackResponse(BaseModel):
    status: str = "success"
    id: int


# =========================================================================
# 기능 B — 빠진 관점 분석 (PRD §2 기능 B + §5.3)
# =========================================================================

class PerspectiveType(str, Enum):
    MISSING_FACT = "MISSING_FACT"
    MISSING_VIEWPOINT = "MISSING_VIEWPOINT"
    DIFFERENT_FRAMING = "DIFFERENT_FRAMING"


class Perspective(BaseModel):
    type: PerspectiveType
    description: str
    found_in: str  # 출처 매체명
    source_url: str  # 출처 URL


class PerspectivesBlock(BaseModel):
    topic_summary: str
    missing_perspectives: list[Perspective] = Field(default_factory=list)


class PerspectivesRequest(BaseModel):
    """기능 A 결과를 받아 기능 B를 별도 호출. 비동기 UX 패턴."""
    article_url_hash: str = Field(min_length=8, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    source: Optional[str] = None  # 같은 매체 제외용 (원본 매체명)
    source_domain: Optional[str] = None  # 같은 매체 제외용 (원본 도메인)
    core_facts: list[str] = Field(default_factory=list, max_length=10)


class PerspectivesResponse(BaseModel):
    status: str = "success"
    perspectives: PerspectivesBlock
    warnings: list[str] = Field(default_factory=list)
    cached: bool = False
    search_results_count: int = 0  # 검색 결과 중 LLM에 전달된 기사 수 (디버깅용)
