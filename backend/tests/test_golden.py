"""골든셋 회귀 테스트 (PRD §13 사전 작업).

사용자가 golden_set.json의 "sentences" 배열에 직접 라벨링 후 실행:
    pytest backend/tests/test_golden.py -v --run-golden

GEMINI_API_KEY가 있어야 실행됨. 기본은 skip (CI 비용 절감).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


_GOLDEN_PATH = Path(__file__).parent / "golden_set.json"


def _golden_data():
    with open(_GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def _api_key_set() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def test_golden_set_file_loadable():
    """파일 자체는 항상 검증 — JSON 깨지면 빨리 발견"""
    data = _golden_data()
    assert "sentences" in data
    for s in data["sentences"]:
        assert "text" in s
        assert "expected_category" in s
        assert s["expected_category"] in {"FACT", "CLAIM", "OPINION", "FRAMING"}


@pytest.fixture
def run_golden(request):
    if not request.config.getoption("--run-golden"):
        pytest.skip("골든셋 LLM 호출 테스트는 --run-golden 옵션 필요")
    if not _api_key_set():
        pytest.skip("GEMINI_API_KEY 미설정")
    data = _golden_data()
    if len(data.get("sentences", [])) < 5:
        pytest.skip(f"골든셋이 비어있거나 너무 작음 ({len(data.get('sentences', []))} sentences). "
                    f"golden_set.json에 라벨링 후 다시 실행하세요.")
    return data


def test_golden_classification_accuracy(run_golden):
    """라벨링된 골든셋으로 분류 일치율 측정. PRD §13 목표 70%+."""
    from app.services.classifier import analyze_article

    sentences_data = run_golden["sentences"]
    texts = [s["text"] for s in sentences_data]
    expected_cats = [s["expected_category"] for s in sentences_data]

    classified, _, _ = analyze_article(
        title="golden test",
        source="test",
        sentences=texts,
    )

    by_index = {c.index: c.category.value for c in classified}
    correct = sum(
        1 for i, exp in enumerate(expected_cats, start=1)
        if by_index.get(i) == exp
    )
    accuracy = correct / len(expected_cats)

    print(f"\n[GOLDEN] category accuracy: {correct}/{len(expected_cats)} = {accuracy:.1%}")
    assert accuracy >= 0.70, f"PRD §13 목표(70%) 미달: {accuracy:.1%}"


def test_golden_significant_recall(run_golden):
    """significant=true로 라벨된 문장 중 실제로 LLM이 잡아낸 비율"""
    from app.services.classifier import analyze_article

    sentences_data = run_golden["sentences"]
    texts = [s["text"] for s in sentences_data]
    expected_significant = [
        bool(s.get("expected_significant", False)) for s in sentences_data
    ]

    if not any(expected_significant):
        pytest.skip("골든셋에 significant=true 라벨이 없음")

    classified, _, _ = analyze_article(
        title="golden test",
        source="test",
        sentences=texts,
    )
    by_index = {c.index: c.significant for c in classified}

    true_positives = sum(
        1 for i, want in enumerate(expected_significant, start=1)
        if want and by_index.get(i, False)
    )
    total_positives = sum(1 for want in expected_significant if want)
    recall = true_positives / total_positives

    print(f"\n[GOLDEN] significant recall: {true_positives}/{total_positives} = {recall:.1%}")
    # 보수적 임계값 — 정확도보다 낮게 잡음 (significant는 어려운 판정)
    assert recall >= 0.50, f"significant recall 너무 낮음: {recall:.1%}"
