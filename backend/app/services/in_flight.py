"""동일 URL 동시 처리 락 (PRD §11, §13 Day 2).

같은 URL이 처리 중인데 또 들어오면 즉시 거절 — 연타·중복 요청으로 인한
LLM 중복 호출과 비용 누수를 방지한다. Day 5의 캐시(같은 URL 24h 재사용)와
보완 관계: 캐시 hit이 나기 전 1차 처리가 진행 중인 짧은 윈도우를 막는다.
"""
from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from typing import Iterator, Optional


class AlreadyInFlight(Exception):
    """이미 같은 URL이 처리 중."""


_LOCK = threading.Lock()
_IN_FLIGHT: set[str] = set()


def url_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


@contextmanager
def acquire(key: Optional[str]) -> Iterator[None]:
    """key가 None이면 락 없이 통과 (텍스트 입력 등)."""
    if key is None:
        yield
        return

    with _LOCK:
        if key in _IN_FLIGHT:
            raise AlreadyInFlight()
        _IN_FLIGHT.add(key)
    try:
        yield
    finally:
        with _LOCK:
            _IN_FLIGHT.discard(key)


def reset_for_test() -> None:
    with _LOCK:
        _IN_FLIGHT.clear()
