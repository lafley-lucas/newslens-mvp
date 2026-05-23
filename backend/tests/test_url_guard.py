"""url_guard.validate_url — SSRF 차단 (Day 2)"""
from __future__ import annotations

import pytest

from app.services.url_guard import UnsafeUrlError, validate_url


@pytest.mark.parametrize("url", [
    "http://localhost/admin",
    "http://127.0.0.1:8000/",
    "http://0.0.0.0/",
    "http://169.254.169.254/latest/meta-data/",  # AWS metadata
    "http://10.0.0.1/",
    "http://172.16.0.1/",
    "http://192.168.1.1/",
    "http://100.64.0.1/",  # CGNAT
])
def test_blocks_private_ips(url):
    with pytest.raises(UnsafeUrlError):
        validate_url(url)


@pytest.mark.parametrize("url", [
    "ftp://example.com/",
    "file:///etc/passwd",
    "javascript:alert(1)",
])
def test_blocks_non_http_schemes(url):
    with pytest.raises(UnsafeUrlError):
        validate_url(url)


def test_rejects_empty_or_too_long():
    with pytest.raises(UnsafeUrlError):
        validate_url("")
    with pytest.raises(UnsafeUrlError):
        validate_url("http://example.com/" + "a" * 3000)


def test_allows_public_https():
    safe = validate_url("https://example.com/article/1")
    assert safe.scheme == "https"
    assert safe.hostname == "example.com"
    assert all(safe.resolved_ips)
