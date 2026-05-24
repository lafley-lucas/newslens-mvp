"""web_search 모듈 단위 테스트 — 실제 CSE 호출 없이 httpx mock."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.services.web_search import (
    SearchError,
    SearchResult,
    _build_query,
    _domain,
    search_related_articles,
)


def test_domain_normalizes_www():
    assert _domain("https://www.chosun.com/article/123") == "chosun.com"
    assert _domain("https://news.hani.co.kr/x") == "news.hani.co.kr"
    assert _domain("not-a-url") is None


def test_build_query_truncates_long_title():
    long = "가" * 200
    assert len(_build_query(long, None)) == 80


def test_search_returns_empty_when_keys_missing(monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "")
    assert search_related_articles("아무 제목") == []


def _mock_cse_response(items: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"items": items}, request=httpx.Request("GET", "x"))


def test_search_filters_excluded_domain(monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "fake-key")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "fake-cx")

    items = [
        {"title": "기사1", "snippet": "내용1", "link": "https://chosun.com/a", "displayLink": "chosun.com"},
        {"title": "기사2", "snippet": "내용2", "link": "https://hani.co.kr/b", "displayLink": "hani.co.kr"},
        {"title": "기사3", "snippet": "내용3", "link": "https://www.chosun.com/c", "displayLink": "chosun.com"},
    ]

    def fake_get(self, url, params=None):
        return _mock_cse_response(items)

    with patch("httpx.Client.get", fake_get):
        results = search_related_articles("테스트", exclude_domain="chosun.com", limit=5)

    assert len(results) == 1
    assert results[0].url == "https://hani.co.kr/b"
    assert results[0].source == "hani.co.kr"


def test_search_respects_limit(monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")

    items = [
        {"title": f"기사{i}", "snippet": "s", "link": f"https://m{i}.kr/x", "displayLink": f"m{i}.kr"}
        for i in range(10)
    ]

    def fake_get(self, url, params=None):
        return _mock_cse_response(items)

    with patch("httpx.Client.get", fake_get):
        results = search_related_articles("t", limit=3)

    assert len(results) == 3


def test_search_raises_on_429(monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")

    def fake_get(self, url, params=None):
        return httpx.Response(429, request=httpx.Request("GET", "x"))

    with patch("httpx.Client.get", fake_get):
        with pytest.raises(SearchError, match="한도 초과"):
            search_related_articles("t")


def test_search_skips_items_without_link(monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")

    items = [
        {"title": "no link", "snippet": "x"},  # link 없음
        {"title": "ok", "snippet": "y", "link": "https://ok.kr/a", "displayLink": "ok.kr"},
    ]

    def fake_get(self, url, params=None):
        return _mock_cse_response(items)

    with patch("httpx.Client.get", fake_get):
        results = search_related_articles("t")

    assert len(results) == 1
    assert results[0].source == "ok.kr"
