"""
Rate limiting (tiêu chí 7) — atomic sliding window 60 giây lưu trong Redis.
"""
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60

_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_start = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local ttl = tonumber(ARGV[5])

redis.call('ZREMRANGEBYSCORE', key, 0, window_start)
local count = redis.call('ZCARD', key)
if count >= limit then
    return {0, count}
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, ttl)
return {1, count + 1}
"""

_rate_limit_script = r.register_script(_SLIDING_WINDOW_LUA)


def check_rate_limit(key: str) -> dict:
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"ratelimit:{key}"
    member = f"{now}:{uuid.uuid4().hex}"

    try:
        allowed, current_count = _rate_limit_script(
            keys=[redis_key],
            args=[now, window_start, settings.rate_limit_per_minute, member, WINDOW_SECONDS + 5],
        )
    except (redis.RedisError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Rate limiter backend unavailable") from exc

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later.",
            headers={
                "Retry-After": str(WINDOW_SECONDS),
                "X-RateLimit-Limit": str(settings.rate_limit_per_minute),
                "X-RateLimit-Remaining": "0",
            },
        )

    remaining = max(0, settings.rate_limit_per_minute - int(current_count))
    return {
        "limit": settings.rate_limit_per_minute,
        "remaining": remaining,
    }
