"""Arc Publishing(Fusion) 플랫폼 본문 추출기.

조선닷컴 같은 Arc 기반 매체는 본문이 `<p>` DOM이 아니라
`Fusion.globalContent = { content_elements: [...] };` JS 객체에 박혀있다.

DOM 파서(trafilatura/newspaper4k)가 실패한 경우의 마지막 폴백.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional


logger = logging.getLogger(__name__)


_FUSION_START = re.compile(r"Fusion\.globalContent\s*=\s*(?=\{)")


@dataclass
class FusionExtraction:
    text: str
    title: Optional[str]
    author: Optional[str]
    date: Optional[str]  # ISO 8601 date or None


def _find_balanced_json_object(src: str, start_brace_idx: int) -> Optional[str]:
    """src의 start_brace_idx 위치에 있는 '{'부터 균형 잡힌 JSON 객체 substring을 반환.

    문자열 리터럴 내부의 중괄호와 백슬래시 이스케이프를 정확히 다룬다.
    """
    if start_brace_idx >= len(src) or src[start_brace_idx] != "{":
        return None

    depth = 0
    i = start_brace_idx
    n = len(src)
    in_string = False
    escape = False

    while i < n:
        ch = src[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return src[start_brace_idx : i + 1]
        i += 1
    return None


def extract_fusion_content(html: str) -> Optional[FusionExtraction]:
    """HTML에서 Fusion.globalContent를 찾아 본문을 추출. 패턴 없거나 본문 없으면 None."""
    m = _FUSION_START.search(html)
    if not m:
        return None

    raw_json = _find_balanced_json_object(html, m.end())
    if not raw_json:
        logger.debug("Fusion: brace balance failed")
        return None

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.debug("Fusion: JSON parse failed (%s)", e)
        return None

    elements = data.get("content_elements") or []
    paragraphs: list[str] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        if el.get("type") == "text":
            content = el.get("content")
            if isinstance(content, str):
                # Arc는 종종 <b>, <a> 같은 인라인 HTML을 content에 그대로 넣어둔다 — 제거.
                stripped = re.sub(r"<[^>]+>", "", content).strip()
                if stripped:
                    paragraphs.append(stripped)

    if not paragraphs:
        return None

    body = "\n\n".join(paragraphs)

    headlines = data.get("headlines") or {}
    title = headlines.get("basic") if isinstance(headlines, dict) else None

    credits = data.get("credits") or {}
    by = credits.get("by") if isinstance(credits, dict) else None
    author = None
    if isinstance(by, list) and by:
        names = [b.get("name") for b in by if isinstance(b, dict) and b.get("name")]
        if names:
            author = "; ".join(names)

    # display_date: ISO 8601 with timezone. 날짜 부분만.
    date = None
    display_date = data.get("display_date") or data.get("first_publish_date")
    if isinstance(display_date, str) and len(display_date) >= 10:
        date = display_date[:10]

    return FusionExtraction(text=body, title=title, author=author, date=date)
