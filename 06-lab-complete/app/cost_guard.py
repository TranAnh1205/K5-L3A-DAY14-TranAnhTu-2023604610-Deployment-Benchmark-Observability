"""
Cost guard (tiêu chí 8) — theo dõi tổng chi phí LLM trong Redis.
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _budget_key() -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost:daily:{day}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    try:
        current_spend = float(r.get(_budget_key()) or 0.0)
    except (redis.RedisError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Cost guard backend unavailable") from exc

    if current_spend >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail="Daily LLM budget exceeded.",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    key = _budget_key()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, 48 * 3600)
        pipe.execute()
    except (redis.RedisError, OSError):
        pass
    return cost
