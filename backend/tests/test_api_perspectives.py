"""/api/perspectives 통합 테스트 — 실제 검색/LLM은 mock."""
from __future__ import annotations

import json
from unittest.mock import patch

from app.models.schemas import PerspectivesBlock, Perspective, PerspectiveType


def _fake_block(urls=None) -> PerspectivesBlock:
    if urls is None:
        urls = ["https://a.kr/1", "https://b.kr/2"]
    return PerspectivesBlock(
        topic_summary="테스트 주제",
        missing_perspectives=[
            Perspective(
                type=PerspectiveType.MISSING_FACT,
                description="설명1",
                found_in="매체A",
                source_url=urls[0],
            ),
            Perspective(
                type=PerspectiveType.MISSING_VIEWPOINT,
                description="설명2",
                found_in="매체B",
                source_url=urls[1] if len(urls) > 1 else urls[0],
            ),
        ],
    )


def test_perspectives_disabled_returns_501(client):
    """CSE 키 없으면 501 — 프론트는 카드 자체를 숨김."""
    payload = {
        "article_url_hash": "a" * 40,
        "title": "테스트 제목",
        "source": "테스트매체",
        "core_facts": ["사실1"],
    }
    r = client.post("/api/perspectives", json=payload)
    # conftest가 GEMINI 키도 비워두므로 CSE도 기본 비활성
    assert r.status_code == 501
    assert "비활성화" in r.json()["detail"]


def test_perspectives_validation_empty_title(client):
    payload = {
        "article_url_hash": "a" * 40,
        "title": "",  # min_length=1 위반
        "core_facts": [],
    }
    r = client.post("/api/perspectives", json=payload)
    assert r.status_code == 422


def test_perspectives_validation_missing_hash(client):
    r = client.post("/api/perspectives", json={"title": "t"})
    assert r.status_code == 422


def test_perspectives_happy_path(client, monkeypatch):
    """모든 의존성을 mock — 라우트 → 캐시 → 응답 직렬화까지 확인."""
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")
    monkeypatch.setattr(s, "GEMINI_API_KEY", "fake")

    fake_block = _fake_block()
    with patch(
        "app.api.routes.analyze_perspectives",
        return_value=(fake_block, 2, []),
    ):
        payload = {
            "article_url_hash": "h" * 40,
            "title": "원본 제목",
            "source": "원본매체",
            "source_domain": "chosun.com",
            "core_facts": ["사실1", "사실2"],
        }
        r = client.post("/api/perspectives", json=payload)

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert data["cached"] is False
    assert data["search_results_count"] == 2
    assert data["perspectives"]["topic_summary"] == "테스트 주제"
    assert len(data["perspectives"]["missing_perspectives"]) == 2


def test_perspectives_cache_hit(client, monkeypatch):
    """2번째 호출은 cached=true — LLM 호출 없이 캐시 hit."""
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")
    monkeypatch.setattr(s, "GEMINI_API_KEY", "fake")

    fake_block = _fake_block()
    call_count = {"n": 0}

    def fake_analyze(**kwargs):
        call_count["n"] += 1
        return fake_block, 2, []

    with patch("app.api.routes.analyze_perspectives", side_effect=fake_analyze):
        payload = {
            "article_url_hash": "h" * 40,
            "title": "원본 제목",
            "core_facts": [],
        }
        r1 = client.post("/api/perspectives", json=payload)
        r2 = client.post("/api/perspectives", json=payload)

    assert r1.status_code == 200
    assert r1.json()["cached"] is False
    assert r2.status_code == 200
    assert r2.json()["cached"] is True
    assert call_count["n"] == 1  # 2번째는 분석 호출 안 됨


def test_perspectives_quota_exceeded_returns_429(client, monkeypatch):
    from app.config import settings as s
    from app.services.classifier import QuotaExceededError
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")
    monkeypatch.setattr(s, "GEMINI_API_KEY", "fake")

    with patch(
        "app.api.routes.analyze_perspectives",
        side_effect=QuotaExceededError("쿼터 초과", retry_after_sec=42),
    ):
        payload = {
            "article_url_hash": "h" * 40,
            "title": "t",
            "core_facts": [],
        }
        r = client.post("/api/perspectives", json=payload)

    assert r.status_code == 429
    assert r.headers.get("retry-after") == "42"


def test_perspectives_generic_error_returns_503(client, monkeypatch):
    from app.config import settings as s
    from app.services.perspectives import PerspectivesError
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")
    monkeypatch.setattr(s, "GEMINI_API_KEY", "fake")

    with patch(
        "app.api.routes.analyze_perspectives",
        side_effect=PerspectivesError("검색 망함"),
    ):
        payload = {
            "article_url_hash": "h" * 40,
            "title": "t",
            "core_facts": [],
        }
        r = client.post("/api/perspectives", json=payload)

    assert r.status_code == 503


def test_perspectives_empty_results_returns_200(client, monkeypatch):
    """검색 결과 0건이어도 200 + warnings — 프론트가 빈 상태 안내."""
    from app.config import settings as s
    monkeypatch.setattr(s, "GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setattr(s, "GOOGLE_CSE_ID", "cx")
    monkeypatch.setattr(s, "GEMINI_API_KEY", "fake")

    empty_block = PerspectivesBlock(topic_summary="t", missing_perspectives=[])
    with patch(
        "app.api.routes.analyze_perspectives",
        return_value=(empty_block, 0, ["같은 주제를 다룬 다른 매체 기사를 찾지 못했습니다."]),
    ):
        payload = {
            "article_url_hash": "h" * 40,
            "title": "t",
            "core_facts": [],
        }
        r = client.post("/api/perspectives", json=payload)

    assert r.status_code == 200
    data = r.json()
    assert data["search_results_count"] == 0
    assert data["perspectives"]["missing_perspectives"] == []
    assert any("찾지 못했" in w for w in data["warnings"])
