"""SQLite 피드백 저장소 (PRD §10 §15 데이터 폐기 정책 준수).

**저장하지 않는 것**:
- 원문 기사 URL
- 원문 기사 본문
- 원문 문장 텍스트
- IP 주소 (rate_limiter의 in-memory 외)

**저장하는 것**:
- 기사 URL의 sha256 hash (식별자, 역추적 불가)
- sentence_index (몇 번째 문장인지)
- original_category (원래 LLM이 분류한 카테고리)
- suggested_category (사용자가 제안한 카테고리, 단순 down vote면 NULL)
- feedback_type (category_correction / thumbs_up / thumbs_down)
- timestamp (ISO 8601, UTC)
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DB_PATH = _DB_DIR / "feedback.db"
_LOCK = threading.Lock()

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_url_hash TEXT NOT NULL,
    sentence_index INTEGER NOT NULL,
    original_category TEXT NOT NULL,
    suggested_category TEXT,
    feedback_type TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feedback_article ON feedback(article_url_hash);
CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback(timestamp);
"""


_initialized = False


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    with _LOCK:
        if _initialized:
            return
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(_DB_PATH) as conn:
            conn.executescript(_INIT_SQL)
        _initialized = True


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    _ensure_initialized()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_feedback(
    article_url_hash: str,
    sentence_index: int,
    original_category: str,
    feedback_type: str,
    suggested_category: Optional[str] = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO feedback (
                article_url_hash, sentence_index,
                original_category, suggested_category, feedback_type
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (article_url_hash, sentence_index, original_category, suggested_category, feedback_type),
        )
        return cur.lastrowid or 0


def feedback_count() -> int:
    """테스트/디버깅용."""
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM feedback").fetchone()
        return int(row["c"])


def reset_for_test() -> None:
    """테스트용 — DB 파일을 비움."""
    global _initialized
    with _LOCK:
        if _DB_PATH.exists():
            try:
                os.remove(_DB_PATH)
            except OSError:
                pass
        _initialized = False
