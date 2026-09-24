"""Redis is only a cache: when it fails, lookups must fall back instead of failing the request."""

import asyncio

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.cache import cache_get, cache_set


class DownRedis:
    """Stands in for a Redis server that is unreachable."""

    def __init__(self, error):
        self.error = error

    async def get(self, key):
        raise self.error

    async def set(self, key, value):
        raise self.error


class WorkingRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value


def test_read_from_down_redis_is_a_miss_not_an_error():
    for error in (RedisConnectionError("refused"), RedisTimeoutError("timed out")):
        assert asyncio.run(cache_get(DownRedis(error), "url:1")) is None


def test_write_to_down_redis_is_ignored():
    asyncio.run(cache_set(DownRedis(RedisConnectionError("refused")), "url:1", "https://example.com"))


def test_working_redis_round_trip():
    client = WorkingRedis()
    assert asyncio.run(cache_get(client, "url:1")) is None
    asyncio.run(cache_set(client, "url:1", "https://example.com"))
    assert asyncio.run(cache_get(client, "url:1")) == "https://example.com"
