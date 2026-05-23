"""pytest 공통 설정 — .env 무시하고 격리된 환경 변수로 실행."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# .env가 테스트에 새어들지 않도록 환경 변수를 먼저 비움
os.environ.pop("GEMINI_API_KEY", None)
os.environ["APP_ENV"] = "test"
os.environ["RATE_LIMIT_PER_HOUR"] = "10000"  # 테스트가 rate limit에 걸리지 않게

# backend/ 디렉토리를 import path에 추가
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-golden",
        action="store_true",
        default=False,
        help="실제 LLM을 호출하는 골든셋 회귀 테스트 실행 (GEMINI_API_KEY 필요)",
    )


@pytest.fixture(autouse=True)
def _clean_state():
    """매 테스트마다 in-memory state 초기화."""
    from app.services import cache, in_flight, rate_limiter, db
    cache.reset_for_test()
    in_flight.reset_for_test()
    rate_limiter.reset_for_test()
    db.reset_for_test()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)
