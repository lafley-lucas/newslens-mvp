"""cache — TTL + 크기 상한 (Day 5)"""
from __future__ import annotations

import time
from unittest.mock import patch

from app.services import cache


def test_set_then_get():
    cache.set("key1", {"a": 1})
    assert cache.get("key1") == {"a": 1}


def test_miss_returns_none():
    assert cache.get("nonexistent") is None


def test_ttl_expiration():
    cache.set("ephemeral", "value")
    # 만료시간 강제 — monotonic을 24h+1 앞으로
    with patch("app.services.cache.time.monotonic", return_value=time.monotonic() + 25 * 3600):
        assert cache.get("ephemeral") is None


def test_invalidate():
    cache.set("k", "v")
    cache.invalidate("k")
    assert cache.get("k") is None


def test_fifo_eviction_when_full():
    # 상한 임시로 줄여 검증
    original_max = cache._MAX_ENTRIES
    try:
        cache._MAX_ENTRIES = 3
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # a가 밀려나야
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("d") == 4
    finally:
        cache._MAX_ENTRIES = original_max
