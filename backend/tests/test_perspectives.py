"""perspectives 모듈 단위 테스트 — LLM은 mock."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.models.schemas import PerspectiveType
from app.services.perspectives import (
    PerspectivesDisabledError,
    PerspectivesError,
    _build_user_prompt,
    _parse_and_validate,
    analyze_perspectives,
)
from app.services.web_search import SearchResult


def _valid_llm_response(urls: list[str]) -> str:
    return json.dumps({
        "topic_summary": "삼성전자 임금협상 결렬",
        "missing_perspectives": [
            {
                "type": "MISSING_FACT",
                "description": "법원이 7천 명 필수유지인력 배치를 명령한 사실이 빠짐",
                "found_in": "매일노동뉴스",
                "source_url": urls[0],
            },
            {
                "type": "MISSING_VIEWPOINT",
                "description": "노조의 영업이익 미배분 주장이 원본에는 없음",
                "found_in": "한겨레",
                "source_url": urls[1] if len(urls) > 1 else urls[0],
            },
        ],
    })


def test_build_user_prompt_includes_all_parts():
    comparisons = [
        SearchResult(title="t1", snippet="s1", url="https://a.kr/1", source="a.kr"),
        SearchResult(title="t2", snippet="s2", url="https://b.kr/2", source="b.kr"),
    ]
    prompt = _build_user_prompt(
        title="원본 제목",
        source="원본 매체",
        core_facts=["사실1", "사실2"],
        comparisons=comparisons,
    )
    assert "원본 제목" in prompt
    assert "원본 매체" in prompt
    assert "사실1" in prompt
    assert "사실2" in prompt
    assert "a.kr" in prompt
    assert "b.kr" in prompt
    assert "https://a.kr/1" in prompt
    assert "https://b.kr/2" in prompt


def test_build_prompt_with_empty_inputs():
    prompt = _build_user_prompt("제목", None, [], [])
    assert "(원본 핵심 사실 없음)" in prompt
    assert "(비교 기사 없음)" in prompt


def test_parse_valid_response():
    urls = ["https://a.kr/1", "https://b.kr/2"]
    block = _parse_and_validate(_valid_llm_response(urls), set(urls))
    assert block.topic_summary == "삼성전자 임금협상 결렬"
    assert len(block.missing_perspectives) == 2
    assert block.missing_perspectives[0].type == PerspectiveType.MISSING_FACT
    assert block.missing_perspectives[1].type == PerspectiveType.MISSING_VIEWPOINT


def test_parse_drops_hallucinated_source_url():
    """LLM이 입력 검색 결과에 없는 URL을 만들어 보내면 해당 perspective 버림."""
    valid_urls = {"https://real.kr/x"}
    bad_response = json.dumps({
        "topic_summary": "t",
        "missing_perspectives": [
            {
                "type": "MISSING_FACT",
                "description": "환각된 URL",
                "found_in": "거짓 매체",
                "source_url": "https://hallucinated.kr/y",
            },
            {
                "type": "MISSING_FACT",
                "description": "정상",
                "found_in": "진짜 매체",
                "source_url": "https://real.kr/x",
            },
        ],
    })
    block = _parse_and_validate(bad_response, valid_urls)
    assert len(block.missing_perspectives) == 1
    assert block.missing_perspectives[0].source_url == "https://real.kr/x"


def test_parse_caps_at_5_items():
    urls = [f"https://m{i}.kr/x" for i in range(10)]
    items = [{
        "type": "MISSING_FACT",
        "description": f"d{i}",
        "found_in": f"m{i}",
        "source_url": urls[i],
    } for i in range(10)]
    response = json.dumps({"topic_summary": "t", "missing_perspectives": items})
    block = _parse_and_validate(response, set(urls))
    assert len(block.missing_perspectives) == 5


def test_parse_empty_topic_summary_fallback():
    """topic_summary 비어있으면 placeholder."""
    response = json.dumps({"topic_summary": "", "missing_perspectives": []})
    block = _parse_and_validate(response, set())
    assert block.topic_summary == "(주제 요약 없음)"


def test_parse_skips_invalid_perspective_items():
    """Pydantic 검증 실패한 항목은 스킵하되 나머지는 살림."""
    valid_urls = {"https://real.kr/x"}
    response = json.dumps({
        "topic_summary": "t",
        "missing_perspectives": [
            {"type": "INVALID_TYPE", "description": "x", "found_in": "x", "source_url": "https://real.kr/x"},
            {"type": "MISSING_FACT", "description": "ok", "found_in": "x", "source_url": "https://real.kr/x"},
        ],
    })
    block = _parse_and_validate(response, valid_urls)
    assert len(block.missing_perspectives) == 1
    assert block.missing_perspectives[0].description == "ok"


def test_disabled_when_no_cse_key(monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "")
    with pytest.raises(PerspectivesDisabledError):
        analyze_perspectives("t", None, None, [])


def test_empty_search_returns_empty_block(monkeypatch):
    """검색 결과 0건이면 LLM 호출 없이 빈 블록 + warning."""
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")
    monkeypatch.setattr(s, "GEMINI_API_KEY", "fake")

    with patch("app.services.perspectives.search_related_articles", return_value=[]):
        block, n, warnings = analyze_perspectives("제목", None, "chosun.com", [])
    assert n == 0
    assert block.missing_perspectives == []
    assert any("찾지 못했습니다" in w for w in warnings)


def test_analyze_end_to_end_with_mocks(monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")
    monkeypatch.setattr(s, "GEMINI_API_KEY", "fake")

    fake_results = [
        SearchResult(title="비교1", snippet="s1", url="https://a.kr/1", source="a.kr"),
        SearchResult(title="비교2", snippet="s2", url="https://b.kr/2", source="b.kr"),
    ]
    fake_llm = _valid_llm_response(["https://a.kr/1", "https://b.kr/2"])

    with patch("app.services.perspectives.search_related_articles", return_value=fake_results), \
         patch("app.services.perspectives._call_gemini_with_fallback", return_value=(fake_llm, "model-x")):
        block, n, warnings = analyze_perspectives(
            "원본 제목", "원본매체", "src.kr", ["사실1", "사실2"]
        )

    assert n == 2
    assert warnings == []
    assert block.topic_summary == "삼성전자 임금협상 결렬"
    assert len(block.missing_perspectives) == 2


def test_analyze_requires_title(monkeypatch):
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")
    monkeypatch.setattr(s, "GEMINI_API_KEY", "fake")

    with pytest.raises(PerspectivesError, match="title"):
        analyze_perspectives("", None, None, [])
