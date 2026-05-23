"""content_guard — 짧음/비한국어/오피니언 휴리스틱 (Day 9)"""
from __future__ import annotations

from app.services import content_guard


def test_too_short():
    assert content_guard.too_short(["문장 하나."]) is True
    assert content_guard.too_short(["가.", "나."]) is True
    assert content_guard.too_short(["가.", "나.", "다."]) is False


def test_korean_ratio():
    assert content_guard.korean_ratio("") == 0.0
    assert content_guard.korean_ratio("12345!@#") == 0.0  # 글자 없음
    assert content_guard.is_korean("정부가 노동시장 개혁안을 발표했다.")
    assert not content_guard.is_korean(
        "The government announced a labor market reform plan today."
    )


def test_detect_opinion_url_patterns():
    assert content_guard.detect_opinion("https://www.chosun.com/opinion/sasul/", None)
    assert content_guard.detect_opinion("https://www.hani.co.kr/arti/opinion/123", None)
    assert content_guard.detect_opinion("https://example.com/column/abc", None)
    assert not content_guard.detect_opinion("https://example.com/economy/1", None)
    assert not content_guard.detect_opinion(None, None)


def test_detect_opinion_title_prefix():
    assert content_guard.detect_opinion(None, "[칼럼] 한국 경제의 미래")
    assert content_guard.detect_opinion(None, "[사설] 노조 파업의 의미")
    assert content_guard.detect_opinion(None, "[기고] 우리가 잊은 것")
    assert not content_guard.detect_opinion(None, "삼성전자 노조 파업 결의")
