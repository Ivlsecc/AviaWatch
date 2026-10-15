"""Запуск одного источника: таймаут, ретраи, лимит частоты, прокси, метрики.

Не зависит от БД — используется и оркестратором, и CLI-проверкой.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from common.metrics import SOURCE_LATENCY, SOURCE_OFFERS, SOURCE_REQUESTS
from sources.base import FlightOffer, SearchQuery, Source, SourceContext

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


@dataclass
class RunSettings:
    timeout_s: float = 20.0
    retries: int = 1
    rate_limit_per_min: int = 30
    proxy: str | None = None
    params: dict | None = None


@dataclass
class SourceRunResult:
    source: str
    ok: bool
    offers: list[FlightOffer]
    error: str | None = None
    elapsed_s: float = 0.0


class SourceRunner:
    def __init__(self) -> None:
        self._clients: dict[str | None, httpx.AsyncClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_call: dict[str, float] = {}

    def client(self, proxy: str | None) -> httpx.AsyncClient:
        if proxy not in self._clients:
            self._clients[proxy] = httpx.AsyncClient(
                proxy=proxy or None,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9"},
                follow_redirects=True,
            )
        return self._clients[proxy]

    async def close(self) -> None:
        for c in self._clients.values():
            await c.aclose()
        self._clients.clear()

    async def _respect_rate_limit(self, name: str, per_min: int) -> None:
        if per_min <= 0:
            return
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            gap = 60.0 / per_min
            wait = self._last_call.get(name, 0) + gap - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call[name] = time.monotonic()

    async def run(self, source: Source, query: SearchQuery, s: RunSettings) -> SourceRunResult:
        ctx = SourceContext(http=self.client(s.proxy), params=s.params or {}, timeout_s=s.timeout_s)
        started = time.monotonic()
        last_error = "unknown"
        for attempt in range(s.retries + 1):
            await self._respect_rate_limit(source.name, s.rate_limit_per_min)
            try:
                offers = await asyncio.wait_for(source.search(query, ctx), timeout=s.timeout_s * 2)
                elapsed = time.monotonic() - started
                SOURCE_REQUESTS.labels(source.name, "ok").inc()
                SOURCE_LATENCY.labels(source.name).observe(elapsed)
                SOURCE_OFFERS.labels(source.name).inc(len(offers))
                return SourceRunResult(source.name, True, offers, elapsed_s=elapsed)
            except asyncio.TimeoutError:
                last_error = "таймаут"
            except Exception as e:  # noqa: BLE001 — любой сбой источника не должен ронять поиск
                last_error = f"{type(e).__name__}: {e}"
            log.warning("source %s attempt %d failed: %s", source.name, attempt + 1, last_error)
            if attempt < s.retries:
                await asyncio.sleep(1.5 * (attempt + 1))

        SOURCE_REQUESTS.labels(source.name, "error").inc()
        return SourceRunResult(source.name, False, [], last_error, time.monotonic() - started)
