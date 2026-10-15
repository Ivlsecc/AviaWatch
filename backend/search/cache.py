"""Кэш результатов поиска: одинаковые запросы разных пользователей не идут на сайты повторно."""

from __future__ import annotations

import json
import time
from typing import Protocol

from common.config import get_settings


class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_s: int) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}

    async def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if not item:
            return None
        expires, value = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        self._data[key] = (time.monotonic() + ttl_s, value)


class RedisCache:
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._redis.get(f"aw:search:{key}")

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        await self._redis.set(f"aw:search:{key}", value, ex=ttl_s)


def make_cache() -> Cache:
    url = get_settings().redis_url
    return RedisCache(url) if url else MemoryCache()


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
