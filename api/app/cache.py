import logging

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.config import get_settings

logger = logging.getLogger("url_shortener")
settings = get_settings()

# Redis is only a cache: Postgres has every link. Short timeouts so that when Redis is down a
# lookup fails fast and falls back to Postgres, instead of hanging the request.
redis_client = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)


async def get_redis() -> redis.Redis:
    return redis_client


async def check_redis() -> bool:
    try:
        return await redis_client.ping()
    except Exception:  # noqa: BLE001 - any failure means "unhealthy", never an error
        return False


async def cache_get(client: redis.Redis, key: str) -> str | None:
    """Cached value, or None on a miss OR if Redis is unavailable (caller falls back to Postgres)."""
    try:
        return await client.get(key)
    except RedisError as exc:
        logger.warning("Redis unavailable, reading from Postgres instead: %s", exc)
        return None


async def cache_set(client: redis.Redis, key: str, value: str) -> None:
    """Best effort: a failed cache write must never fail the request."""
    try:
        await client.set(key, value)
    except RedisError as exc:
        logger.warning("Redis unavailable, not caching %s: %s", key, exc)
