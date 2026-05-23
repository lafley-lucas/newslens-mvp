"""fusion_parser.extract_fusion_content — Arc Publishing 본문 (Day 1)"""
from __future__ import annotations

from app.services.fusion_parser import extract_fusion_content


_FAKE_ARC_HTML = """
<html><head><title>x</title></head><body>
<script>
window.Fusion = window.Fusion || {};
Fusion.globalContent = {
  "headlines": {"basic": "테스트 헤드라인"},
  "display_date": "2026-05-23T09:00:00Z",
  "credits": {"by": [{"name": "홍길동 기자"}, {"name": "김영희 기자"}]},
  "content_elements": [
    {"_id":"a","type":"text","content":"첫 번째 문단입니다. 이것은 본문이에요."},
    {"_id":"b","type":"image","caption":"사진"},
    {"_id":"c","type":"text","content":"두 번째 문단. <b>강조</b>도 들어있음."},
    {"_id":"d","type":"text","content":"세 번째 문단."}
  ]
};
</script>
</body></html>
"""


def test_extracts_text_elements_joined():
    result = extract_fusion_content(_FAKE_ARC_HTML)
    assert result is not None
    assert "첫 번째 문단" in result.text
    assert "두 번째 문단" in result.text
    assert "세 번째 문단" in result.text
    # 인라인 HTML 태그 제거
    assert "<b>" not in result.text
    assert "강조" in result.text


def test_metadata_from_json():
    result = extract_fusion_content(_FAKE_ARC_HTML)
    assert result is not None
    assert result.title == "테스트 헤드라인"
    assert result.date == "2026-05-23"
    assert "홍길동 기자" in (result.author or "")
    assert "김영희 기자" in (result.author or "")


def test_none_when_no_fusion_pattern():
    assert extract_fusion_content("<html><body><p>일반 HTML</p></body></html>") is None


def test_handles_broken_json_gracefully():
    bad = '<script>Fusion.globalContent={not json}</script>'
    assert extract_fusion_content(bad) is None
