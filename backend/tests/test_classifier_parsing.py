"""classifier._parse_and_validate — JSON 파싱·검증·강제 (Day 3, 7)"""
from __future__ import annotations

import json

import pytest

from app.services.classifier import _parse_and_validate
from app.models.schemas import Category


def _valid_response(n=3, with_facts=True):
    sentences = [
        {"index": i + 1, "text": f"문장 {i+1}",
         "category": "FACT" if i == 0 else "CLAIM",
         "confidence": 0.9, "significant": False, "rationale": "테스트"}
        for i in range(n)
    ]
    out = {"sentences": sentences}
    if with_facts:
        out["core_facts"] = ["사실 1", "사실 2"]
    return json.dumps(out)


def test_basic_parse():
    classified, facts = _parse_and_validate(
        _valid_response(), ["원문 A", "원문 B", "원문 C"]
    )
    assert len(classified) == 3
    assert facts == ["사실 1", "사실 2"]
    # text는 우리 원문으로 덮어쓰기 됐는지
    assert classified[0].text == "원문 A"
    assert classified[2].text == "원문 C"


def test_fact_significant_forced_false():
    """FACT 문장에 significant=true가 와도 false로 강제 (PRD §2 불변식)"""
    data = json.dumps({
        "sentences": [{
            "index": 1, "text": "x", "category": "FACT",
            "confidence": 1.0, "significant": True, "rationale": "test"
        }],
        "core_facts": []
    })
    classified, _ = _parse_and_validate(data, ["원문"])
    assert classified[0].category == Category.FACT
    assert classified[0].significant is False


def test_out_of_range_index_discarded():
    data = json.dumps({
        "sentences": [
            {"index": 1, "text": "a", "category": "FACT", "confidence": 1.0,
             "significant": False, "rationale": "ok"},
            {"index": 99, "text": "b", "category": "FACT", "confidence": 1.0,
             "significant": False, "rationale": "out of range"},
        ],
        "core_facts": []
    })
    classified, _ = _parse_and_validate(data, ["원문"])
    assert len(classified) == 1
    assert classified[0].index == 1


def test_duplicate_index_discarded():
    data = json.dumps({
        "sentences": [
            {"index": 1, "text": "a", "category": "FACT", "confidence": 1.0,
             "significant": False, "rationale": "first"},
            {"index": 1, "text": "b", "category": "OPINION", "confidence": 1.0,
             "significant": False, "rationale": "dup"},
        ],
        "core_facts": []
    })
    classified, _ = _parse_and_validate(data, ["원문"])
    assert len(classified) == 1
    assert classified[0].category == Category.FACT  # 첫 번째만


def test_missing_sentences_array_raises():
    with pytest.raises(ValueError):
        _parse_and_validate('{"other": "no sentences"}', ["x"])


def test_invalid_category_raises():
    bad = json.dumps({"sentences": [{
        "index": 1, "text": "x", "category": "INVALID",
        "confidence": 1.0, "significant": False, "rationale": "test"
    }], "core_facts": []})
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        _parse_and_validate(bad, ["원문"])


def test_core_facts_optional():
    """core_facts 없으면 빈 리스트로"""
    data = json.dumps({"sentences": []})
    classified, facts = _parse_and_validate(data, [])
    assert classified == []
    assert facts == []
