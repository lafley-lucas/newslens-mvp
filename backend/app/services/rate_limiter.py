"""IP 기반 sliding-window rate limit (PRD §11, §13 Day 2).

기본값: 시간당 IP당 RATE_LIMIT_PER_HOUR(=20)건.
in-memory dict — 다중 worker / 다중 인스턴스에서는 한계 있음. MVP 수용.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from ..config import settings


_WINDOW_SECONDS = 3600
_LOCK = threading.Lock()
_HISTORY: dict[str, deque[float]] = {}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> None:
    """FastAPI dependency. 초과 시 HTTP 429."""
    limit = settings.RATE_LIMIT_PER_HOUR
    if limit <= 0:
        return

    now = time.monotonic()
    ip = _client_ip(request)

    with _LOCK:
        bucket = _HISTORY.setdefault(ip, deque())
        cutoff = now - _WINDOW_SECONDS
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            wait_sec = int(_WINDOW_SECONDS - (now - bucket[0]))
            wait_min = max(wait_sec // 60, 1)
            raise HTTPException(
                status_code=429,
                detail=f"분석 요청이 너무 많습니다. 약 {wait_min}분 후 다시 시도해주세요.",
                headers={"Retry-After": str(max(wait_sec, 1))},
            )

        bucket.append(now)


def reset_for_test() -> None:
    """테스트용 — 모든 히스토리 초기화."""
    with _LOCK:
        _HISTORY.clear()
