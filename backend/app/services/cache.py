"""URL 기반 분석 결과 캐시 (PRD §13 Day 5, §10 일관성).

- 키: URL의 sha256 (in_flight.url_key와 동일 해시 함수)
- TTL: 24시간
- 값: 직렬화된 AnalyzeResponse (model_dump)
- 텍스트 직접 입력은 캐시 제외 (PRD §13: "텍스트 직접 입력은 캐시 제외")
- in-memory dict — 서버 재시작 시 휘발. MVP 수용 (피드백 DB 추가 시 SQLite로 이관 검토)

Day 2에 만든 in_flight 락과 보완 관계:
  in_flight = 처리 중인 짧은 윈도우 동안 중복 LLM 호출 차단
  cache    = 처리가 끝난 뒤 24h 동안 동일 URL에 대해 LLM 호출 0회
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional


_TTL_SECONDS = 24 * 60 * 60
_MAX_ENTRIES = 1000  # 메모리 안전장치 — 초과 시 가장 오래된 entry FIFO eviction

_LOCK = threading.Lock()
_STORE: dict[str, tuple[float, Any]] = {}  # key -> (expires_at_monotonic, value)


def get(key: str) -> Optional[Any]:
    """캐시 조회. 만료/부재 시 None."""
    now = time.monotonic()
    with _LOCK:
        entry = _STORE.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= now:
            _STORE.pop(key, None)
            return None
        return value


def set(key: str, value: Any) -> None:
    """캐시 저장. 용량 초과 시 가장 오래 머문 entry 제거."""
    expires_at = time.monotonic() + _TTL_SECONDS
    with _LOCK:
        if len(_STORE) >= _MAX_ENTRIES and key not in _STORE:
            # dict는 Python 3.7+ insertion order 보장 → 첫 키가 가장 오래된 것
            oldest = next(iter(_STORE))
            _STORE.pop(oldest, None)
        _STORE[key] = (expires_at, value)


def invalidate(key: str) -> None:
    with _LOCK:
        _STORE.pop(key, None)


def reset_for_test() -> None:
    with _LOCK:
        _STORE.clear()


def size() -> int:
    with _LOCK:
        return len(_STORE)
