"""
Kết nối Redis dùng chung cho rate limiter và cost guard.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1.5,
    socket_timeout=1.5,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except (redis.RedisError, OSError):
        return False
