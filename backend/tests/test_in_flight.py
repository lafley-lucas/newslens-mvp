"""in_flight — 동일 키 동시 처리 락 (Day 2)"""
from __future__ import annotations

import pytest

from app.services import in_flight


def test_url_key_is_stable_sha256():
    key1 = in_flight.url_key("https://example.com/a")
    key2 = in_flight.url_key("https://example.com/a")
    assert key1 == key2
    assert len(key1) == 64


def test_acquire_releases_on_exit():
    key = in_flight.url_key("https://x.com/1")
    with in_flight.acquire(key):
        pass
    # 풀린 뒤 재진입 가능
    with in_flight.acquire(key):
        pass


def test_concurrent_acquire_raises():
    key = in_flight.url_key("https://x.com/2")
    with in_flight.acquire(key):
        with pytest.raises(in_flight.AlreadyInFlight):
            with in_flight.acquire(key):
                pass


def test_none_key_skips_lock():
    with in_flight.acquire(None):
        with in_flight.acquire(None):  # 여러 번 진입 OK
            pass


def test_release_on_exception():
    key = in_flight.url_key("https://x.com/3")
    with pytest.raises(RuntimeError):
        with in_flight.acquire(key):
            raise RuntimeError("boom")
    # 예외 후에도 락이 풀려 재진입 가능
    with in_flight.acquire(key):
        pass
