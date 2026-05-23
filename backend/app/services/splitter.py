"""한국어 문장 분리. kss 6.x 사용.

kss는 첫 호출 시 모델/사전 로드에 약간 시간이 걸려서 import 시점에 워밍업.
"""
from __future__ import annotations

import logging
import re

import kss


logger = logging.getLogger(__name__)


def _warmup() -> None:
    try:
        kss.split_sentences("워밍업 문장입니다. 두 번째 문장.")
    except Exception as e:
        logger.warning("kss warmup failed: %s", e)


_warmup()


_WHITESPACE_RE = re.compile(r"\s+")


def split_sentences(text: str) -> list[str]:
    """본문 텍스트를 한국어 문장 단위 리스트로 분리.

    빈 문장과 너무 짧은 조각(2자 미만)은 버린다.
    """
    if not text or not text.strip():
        return []

    raw = kss.split_sentences(text, backend="punct")
    cleaned: list[str] = []
    for s in raw:
        norm = _WHITESPACE_RE.sub(" ", s).strip()
        if len(norm) >= 2:
            cleaned.append(norm)
    return cleaned
