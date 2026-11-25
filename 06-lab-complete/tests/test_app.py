import json
import logging
import time
from unittest.mock import patch

import redis as redis_lib

from app.config import settings
from app.cost_guard import _budget_key, check_budget, record_cost
from app.redis_client import r

Q = {"question": "What is Docker?", "user_id": "u1"}


def test_ask_returns_answer(client, headers):
    resp = client.post("/ask", json=Q, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["question"] == Q["question"]
    assert isinstance(body["answer"], str) and body["answer"]
    assert body["cost_usd"] > 0


def test_ask_user_id_optional(client, headers):
    assert client.post("/ask", json={"question": "Hello"}, headers=headers).status_code == 200


def test_request_id_header_echoed(client, headers):
    resp = client.post("/ask", json=Q, headers={**headers, "X-Request-ID": "abc123"})
    assert resp.headers["X-Request-ID"] == "abc123"


def test_missing_question_422_no_stacktrace(client, headers):
    resp = client.post("/ask", json={}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"
    assert "Traceback" not in resp.text


def test_blank_question_422(client, headers):
    assert client.post("/ask", json={"question": "   "}, headers=headers).status_code == 422


def test_too_long_question_422(client, headers):
    assert client.post("/ask", json={"question": "x" * 2001}, headers=headers).status_code == 422


def test_invalid_json_422(client, headers):
    resp = client.post("/ask", content="{not json", headers={**headers, "Content-Type": "application/json"})
    assert resp.status_code == 422
    assert "Traceback" not in resp.text


def test_unhandled_error_returns_500_without_stacktrace(client, headers):
    with patch("app.main.llm_ask", side_effect=RuntimeError("boom secret")):
        resp = client.post("/ask", json=Q, headers=headers)
    assert resp.status_code == 500
    assert resp.json()["error"] == "internal_server_error"
    assert "boom secret" not in resp.text and "Traceback" not in resp.text


def test_no_key_401(client):
    assert client.post("/ask", json=Q).status_code == 401


def test_wrong_key_401(client):
    assert client.post("/ask", json=Q, headers={"X-API-Key": "wrong"}).status_code == 401


def test_health_and_ready_need_no_key(client):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_rate_limit_429_after_limit(client, headers):
    limit = settings.rate_limit_per_minute
    for _ in range(limit):
        assert client.post("/ask", json=Q, headers=headers).status_code == 200
    resp = client.post("/ask", json=Q, headers=headers)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"


def test_rate_limit_headers_remaining_decreases(client, headers):
    first = client.post("/ask", json=Q, headers=headers)
    second = client.post("/ask", json=Q, headers=headers)
    assert int(second.headers["X-RateLimit-Remaining"]) == int(first.headers["X-RateLimit-Remaining"]) - 1


def test_rate_limit_state_lives_in_redis(client, headers):
    client.post("/ask", json=Q, headers=headers)
    assert r.keys("ratelimit:*"), "rate limit state must be stored in Redis, not RAM"


def test_rate_limit_window_slides(client, headers):
    limit = settings.rate_limit_per_minute
    real = time.time()
    with patch("app.rate_limiter.time.time", return_value=real - 120):
        for _ in range(limit):
            assert client.post("/ask", json=Q, headers=headers).status_code == 200
    assert client.post("/ask", json=Q, headers=headers).status_code == 200


def test_cost_recorded_in_redis(client, headers):
    client.post("/ask", json=Q, headers=headers)
    assert float(r.get(_budget_key())) > 0


def test_budget_exceeded_402(client, headers):
    r.set(_budget_key(), settings.daily_budget_usd + 0.01)
    resp = client.post("/ask", json=Q, headers=headers)
    assert resp.status_code == 402


def test_check_budget_passes_under_budget():
    r.set(_budget_key(), 0.001)
    check_budget()  # không raise


def test_record_cost_accumulates():
    c1 = record_cost(100, 100)
    c2 = record_cost(100, 100)
    assert abs(float(r.get(_budget_key())) - (c1 + c2)) < 1e-9


def test_ready_503_when_redis_down(client):
    with patch.object(r, "ping", side_effect=redis_lib.ConnectionError("down")):
        assert client.get("/ready").status_code == 503
        assert client.get("/health").status_code == 200  # liveness không phụ thuộc Redis


def test_ask_503_when_redis_down(client, headers):
    with patch("app.rate_limiter._rate_limit_script", side_effect=redis_lib.ConnectionError("down")):
        assert client.post("/ask", json=Q, headers=headers).status_code == 503


def test_json_log_format():
    from app.main import JsonFormatter

    rec = logging.LogRecord("production_agent", logging.INFO, __file__, 1, "hello", None, None)
    rec.status = 200
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "hello" and out["status"] == 200 and "ts" in out


def test_config_reads_env(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "42")
    monkeypatch.setenv("DAILY_BUDGET_USD", "3.5")
    s = Settings()
    assert s.rate_limit_per_minute == 42 and s.daily_budget_usd == 3.5


def test_no_hardcoded_secret_in_source():
    from pathlib import Path

    for f in Path(__file__).resolve().parent.parent.joinpath("app").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "sk-" not in text, f
