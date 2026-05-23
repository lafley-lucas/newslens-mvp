"""FastAPI smoke 테스트 — TestClient로 라우트 검증 (LLM 호출 없는 경로만)"""
from __future__ import annotations


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_extract_requires_input(client):
    r = client.post("/api/extract", json={})
    assert r.status_code == 400


def test_extract_text_input_splits_sentences(client):
    text = "첫 번째 문장입니다. 두 번째 문장. 세 번째 문장도 있어요."
    r = client.post("/api/extract", json={"text": text, "source": "테스트"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert data["total_sentences"] == 3
    assert data["parser"] == "text_input"


def test_analyze_blocks_too_short(client):
    r = client.post("/api/analyze", json={"text": "짧다 한 문장만."})
    # 가드는 _fetch_and_split 단계에서 차단
    assert r.status_code in (400, 422)


def test_analyze_blocks_non_korean(client):
    eng = (
        "The government announced a labor market reform plan today. "
        "Critics call it too aggressive. Unions plan to strike next week."
    )
    r = client.post("/api/analyze", json={"text": eng})
    assert r.status_code == 422
    assert "한국어" in r.json().get("detail", "")


def test_analyze_ssrf_blocked(client):
    r = client.post("/api/analyze", json={"url": "http://localhost/admin"})
    assert r.status_code == 422


def test_analyze_aws_metadata_blocked(client):
    r = client.post("/api/analyze", json={"url": "http://169.254.169.254/latest/"})
    assert r.status_code == 422


def test_feedback_thumbs_down(client):
    r = client.post("/api/feedback", json={
        "article_url_hash": "deadbeef" * 8,
        "sentence_index": 3,
        "original_category": "CLAIM",
        "feedback_type": "thumbs_down",
    })
    assert r.status_code == 200
    assert r.json()["status"] == "success"


def test_feedback_correction_requires_suggested(client):
    r = client.post("/api/feedback", json={
        "article_url_hash": "deadbeef" * 8,
        "sentence_index": 1,
        "original_category": "FACT",
        "feedback_type": "category_correction",
        # suggested_category 빠짐
    })
    assert r.status_code == 400


def test_feedback_does_not_store_original_text(client):
    """피드백 요청에 원문 텍스트 필드가 없는지(스키마 차원)"""
    from app.models.schemas import FeedbackRequest
    fields = set(FeedbackRequest.model_fields.keys())
    forbidden = {"text", "url", "title", "content", "article_text"}
    assert fields.isdisjoint(forbidden), (
        f"FeedbackRequest must not accept raw text fields, got {fields & forbidden}"
    )
