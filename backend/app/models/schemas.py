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


class ErrorResponse(BaseModel):
    status: str = "error"
    code: str
    message: str
