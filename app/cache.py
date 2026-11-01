"""Tiny key-value store used for redirect caching and rate limiting.

Uses Redis when REDIS_URL is set, otherwise an in-memory fallback so the app
runs locally with zero setup. Redis failures never break requests: caching
degrades to "miss" and rate limiting degrades to "allow".
"""
import logging
import threading
import time
from functools import lru_cache

import redis

from app.config import get_settings

logger = logging.getLogger("uvicorn.error")


def link_cache_key(code: str) -> str:
    return f"link:{code}"


class MemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[object, float | None]] = {}
        self._lock = threading.Lock()

    def _purge_if_expired(self, key: str) -> None:
        item = self._data.get(key)
        if item and item[1] is not None and item[1] <= time.monotonic():
            del self._data[key]

    def get(self, key: str):
        with self._lock:
            self._purge_if_expired(key)
            item = self._data.get(key)
            return item[0] if item else None

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        with self._lock:
            self._data[key] = (value, time.monotonic() + ttl if ttl else None)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def incr(self, key: str, ttl: int) -> int:
        """Increment a counter; the window starts when the key is first created."""
        with self._lock:
            self._purge_if_expired(key)
            item = self._data.get(key)
            if item is None:
                self._data[key] = (1, time.monotonic() + ttl)
                return 1
            count = int(item[0]) + 1
            self._data[key] = (count, item[1])
            return count

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class RedisStore:
    def __init__(self, url: str) -> None:
        self._r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)

    def get(self, key: str):
        try:
            return self._r.get(key)
        except redis.RedisError as exc:
            logger.warning("Redis get failed: %s", exc)
            return None

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        try:
            self._r.set(key, value, ex=ttl)
        except redis.RedisError as exc:
            logger.warning("Redis set failed: %s", exc)

    def delete(self, key: str) -> None:
        try:
            self._r.delete(key)
        except redis.RedisError as exc:
            logger.warning("Redis delete failed: %s", exc)

    def incr(self, key: str, ttl: int) -> int:
        try:
            count = self._r.incr(key)
            if count == 1:
                self._r.expire(key, ttl)
            return int(count)
        except redis.RedisError as exc:
            logger.warning("Redis incr failed (rate limit skipped): %s", exc)
            return 0

    def clear(self) -> None:  # only meant for tests
        self._r.flushdb()


@lru_cache
def get_store():
    url = get_settings().redis_url
    return RedisStore(url) if url else MemoryStore()
