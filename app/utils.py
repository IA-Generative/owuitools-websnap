"""Utilities: async-compatible LRU cache with TTL."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from app.config import settings
from app.models import ExtractionResult

logger = logging.getLogger(__name__)


class AsyncTTLCache:
    """Simple async-compatible LRU cache with TTL.

    Key = sha256(url + sorted(cookies) + sorted(headers))
    Excludes PDFs from caching (too large).
    Thread-safe via asyncio.Lock.
    """

    def __init__(
        self,
        max_entries: int = settings.CACHE_MAX_ENTRIES,
        ttl_seconds: int = settings.CACHE_TTL_SECONDS,
    ):
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, ExtractionResult]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def make_key(
        url: str,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        """Generate a cache key from URL, cookies, and headers."""
        parts = [url]
        if cookies:
            parts.append(json.dumps(sorted(cookies.items())))
        if headers:
            parts.append(json.dumps(sorted(headers.items())))
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get(self, key: str) -> ExtractionResult | None:
        """Retrieve a cached result if it exists and hasn't expired."""
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ts, result = entry
            if time.monotonic() - ts > self._ttl_seconds:
                del self._cache[key]
                return None
            return result

    async def set(self, key: str, result: ExtractionResult) -> None:
        """Store a result in the cache, evicting oldest if at capacity."""
        async with self._lock:
            # Evict oldest entries if at capacity
            while len(self._cache) >= self._max_entries:
                oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest_key]
            self._cache[key] = (time.monotonic(), result)

    async def clear(self) -> None:
        """Clear the entire cache."""
        async with self._lock:
            self._cache.clear()


# Global cache instance
extraction_cache = AsyncTTLCache()
