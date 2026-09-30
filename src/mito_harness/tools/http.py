"""Async HTTP helpers with disk-cache replay, retries and per-source rate limiting.

All external API traffic goes through here: cache first (reproducibility),
then network with retry/backoff from config/sources.yaml. NCBI E-utilities
allow ~3 req/s without an API key, so pubmed calls are throttled globally.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from mito_harness.cache import DiskCache

logger = logging.getLogger(__name__)

_throttle_locks: dict[str, tuple[asyncio.Lock, float, float]] = {}


async def _throttle(source: str, min_interval: float) -> None:
    """Serialize calls per source with a minimum interval (0 disables)."""
    if min_interval <= 0:
        return
    lock, _, last = _throttle_locks.get(source, (asyncio.Lock(), 0.0, 0.0))
    _throttle_locks[source] = (lock, min_interval, last)
    async with lock:
        current_lock, interval, last_at = _throttle_locks[source]
        wait = last_at + interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _throttle_locks[source] = (current_lock, interval, time.monotonic())


class SourceClient:
    """HTTP client bound to one source config with cache replay and retries."""

    def __init__(
        self,
        source_name: str,
        base_url: str,
        cache: DiskCache,
        timeout: float = 20.0,
        retries: int = 3,
        backoff: float = 1.5,
        rate_limit_seconds: float = 0.0,
    ) -> None:
        self.source_name = source_name
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.rate_limit_seconds = rate_limit_seconds

    async def get_json(self, url: str, params: dict[str, Any]) -> Any:
        cache_key = {"url": url, "params": params}
        cached = self.cache.get(self.source_name, cache_key)
        if cached is not None:
            return cached
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                await _throttle(self.source_name, self.rate_limit_seconds)
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    payload: Any = resp.json()
                self.cache.set(self.source_name, cache_key, payload)
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                logger.warning("%s GET failed (attempt %d/%d): %s", self.source_name, attempt, self.retries, exc)
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff**attempt)
        raise RuntimeError(f"{self.source_name} request failed after {self.retries} attempts") from last_error

    async def get_text(self, url: str, params: dict[str, Any]) -> str:
        cache_key = {"url": url, "params": params, "as": "text"}
        cached = self.cache.get(self.source_name, cache_key)
        if cached is not None:
            return str(cached)
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                await _throttle(self.source_name, self.rate_limit_seconds)
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    text = resp.text
                self.cache.set(self.source_name, cache_key, text)
                return text
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("%s GET failed (attempt %d/%d): %s", self.source_name, attempt, self.retries, exc)
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff**attempt)
        raise RuntimeError(f"{self.source_name} request failed after {self.retries} attempts") from last_error
