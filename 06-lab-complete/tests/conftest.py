import os
import sys
from pathlib import Path

import fakeredis
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_KEY = "test-secret-key"
os.environ["AGENT_API_KEY"] = TEST_KEY
os.environ["RATE_LIMIT_PER_MINUTE"] = "5"
os.environ["DAILY_BUDGET_USD"] = "1.0"
os.environ["ENVIRONMENT"] = "test"

import redis  # noqa: E402

_server = fakeredis.FakeServer()
redis.from_url = lambda *a, **k: fakeredis.FakeRedis(server=_server, decode_responses=True)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.redis_client import r  # noqa: E402


@pytest.fixture(autouse=True)
def clean_redis():
    r.flushall()
    yield
    r.flushall()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def headers():
    return {"X-API-Key": TEST_KEY}
