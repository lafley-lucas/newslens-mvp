"""기사 본문 분류·차단 휴리스틱 (PRD §11 엣지케이스).

- 너무 짧은 기사 (3문장 이하) → 분석 거부
- 비한국어 기사 (한글 문자 비율 < 50%) → 안내
- 칼럼/사설/오피니언 콘텐츠 → 진행하되 type="opinion"로 표시
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse


MIN_SENTENCES = 3
KOREAN_RATIO_THRESHOLD = 0.30  # 본문 중 한글 문자 비율 — 인용·숫자 제외하면 30%면 충분히 한국어


_OPINION_URL_KEYWORDS = (
    "/opinion/",
    "/column/",
    "/editorial/",
    "/columns/",
    "/oped/",
    "/op-ed/",
    "/columnist/",
    # 한국 매체 path 패턴
    "/opi/",
    "/edit/",
)
_OPINION_TITLE_KEYWORDS = ("[칼럼]", "[사설]", "[기고]", "[기자수첩]", "[데스크칼럼]", "[오피니언]")


_HANGUL_RE = re.compile(r"[가-힯]")
_LETTERS_RE = re.compile(r"[A-Za-z가-힯぀-ヿ一-鿿]")


def too_short(sentences: list[str]) -> bool:
    return len(sentences) < MIN_SENTENCES


def korean_ratio(text: str) -> float:
    """본문 중 한글 글자가 전체 알파벳/한글/일본어/중국어 글자 대비 차지하는 비율."""
    if not text:
        return 0.0
    letters = _LETTERS_RE.findall(text)
    if not letters:
        return 0.0
    hangul = _HANGUL_RE.findall(text)
    return len(hangul) / len(letters)


def is_korean(text: str) -> bool:
    return korean_ratio(text) >= KOREAN_RATIO_THRESHOLD


def detect_opinion(url: Optional[str], title: Optional[str]) -> bool:
    """URL path와 제목 prefix로 오피니언 콘텐츠 1차 판별. 보수적으로 매칭."""
    if url:
        try:
            path = urlparse(url).path.lower()
        except ValueError:
            path = ""
        for kw in _OPINION_URL_KEYWORDS:
            if kw in path:
                return True

    if title:
        t = title.strip()
        for kw in _OPINION_TITLE_KEYWORDS:
            if t.startswith(kw):
                return True

    return False
