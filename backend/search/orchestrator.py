"""Оркестратор поиска: опрашивает включённые источники параллельно, кэширует,
сохраняет историю цен, ведёт circuit breaker и отдаёт отфильтрованную выдачу."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from common.config import get_settings
from common.db import session_scope
from common.metrics import SEARCHES, SOURCE_UP
from common.models import PriceSnapshot, SearchLog, SourceConfig
from search.cache import Cache, dumps, make_cache
from search.dedup import merge_duplicates
from search.filters import FilterSettings, apply_filters
from search.runner import RunSettings, SourceRunner, SourceRunResult
from sources.base import MAX_SEARCH_DAYS, FlightOffer, SearchQuery, SourceContext
from sources.registry import all_sources, get_source

log = logging.getLogger(__name__)

CALENDAR_TTL_S = 3 * 3600

# Колбэк «источник отключён»: (имя, ошибка) — для алерта админу
SourceDownHook = Callable[[str, str], Awaitable[None]]


@dataclass
class SourceStatus:
    source: str
    ok: bool
    offers: int
    error: str | None = None
    skipped: bool = False


@dataclass
class SearchResult:
    query: SearchQuery
    offers: list[FlightOffer]  # после фильтров и склейки, по возрастанию цены
    raw_count: int
    statuses: list[SourceStatus] = field(default_factory=list)
    from_cache: bool = False


def as_utc(dt: datetime | None) -> datetime | None:
    # SQLite возвращает naive datetime — считаем его UTC
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


async def sync_source_configs() -> None:
    """Создаёт в БД строки конфигов для новых зарегистрированных источников."""
    async with session_scope() as s:
        existing = set((await s.scalars(select(SourceConfig.name))).all())
        for name, cls in all_sources().items():
            if name in existing:
                continue
            params = {"market": "ru"} if name == "aviasales_api" else {}
            s.add(SourceConfig(name=name, params=params, timeout_s=cls.default_timeout_s, proxy=cls.default_proxy))
            log.info("Добавлен конфиг источника %s (%s)", name, cls.title)


class SearchService:
    def __init__(self, cache: Cache | None = None, on_source_down: SourceDownHook | None = None) -> None:
        self.settings = get_settings()
        self.cache = cache or make_cache()
        self.runner = SourceRunner()
        self.on_source_down = on_source_down

    async def close(self) -> None:
        await self.runner.close()

    async def search(
        self,
        query: SearchQuery,
        filters: FilterSettings | None = None,
        user_id: int | None = None,
        use_cache: bool = True,
        only_sources: set[str] | None = None,
        log_search: bool = True,
    ) -> SearchResult:
        """only_sources — опросить только эти источники (служебные поиски, например ноги составных маршрутов)."""
        started = time.monotonic()
        filters = filters or FilterSettings()
        cache_key = query.cache_key() + (":" + ",".join(sorted(only_sources)) if only_sources else "")

        raw, statuses, from_cache = None, [], False
        if use_cache and (cached := await self.cache.get(cache_key)):
            data = json.loads(cached)
            raw = [FlightOffer.model_validate(o) for o in data["offers"]]
            statuses = [SourceStatus(**st) for st in data["statuses"]]
            from_cache = True

        if raw is None:
            raw, statuses = await self._collect(query, only_sources)
            await self.cache.set(
                cache_key,
                dumps({"offers": [o.model_dump(mode="json") for o in raw], "statuses": [st.__dict__ for st in statuses]}),
                self.settings.search_cache_ttl_s,
            )
            await self._save_snapshots(query, raw)

        if query.direct_only:
            filters = filters.model_copy(update={"max_transfers": 0})
        # Сначала склейка: фильтры должны видеть самые подробные данные о рейсе
        offers = apply_filters(merge_duplicates(raw), filters)

        if not log_search:
            return SearchResult(query, offers, len(raw), statuses, from_cache)
        SEARCHES.labels(query.origin, str(from_cache).lower()).inc()
        async with session_scope() as s:
            s.add(
                SearchLog(
                    user_id=user_id,
                    origin=query.origin,
                    destination=query.destination,
                    date_from=query.date_from,
                    date_to=query.date_to,
                    results=len(offers),
                    min_price=offers[0].price_rub if offers else None,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    from_cache=from_cache,
                )
            )
        return SearchResult(query, offers, len(raw), statuses, from_cache)

    async def _collect(
        self, query: SearchQuery, only_sources: set[str] | None = None
    ) -> tuple[list[FlightOffer], list[SourceStatus]]:
        now = datetime.now(timezone.utc)
        async with session_scope() as s:
            configs = (await s.scalars(select(SourceConfig).order_by(SourceConfig.priority))).all()

        registered = all_sources()
        focus = await self._focus_days(query)
        tasks, statuses = [], []
        for cfg in configs:
            if cfg.name not in registered or not cfg.enabled:
                continue
            if only_sources is not None and cfg.name not in only_sources:
                continue
            if (until := as_utc(cfg.disabled_until)) and until > now:
                statuses.append(SourceStatus(cfg.name, False, 0, "временно отключён после ошибок", skipped=True))
                continue
            rs = self._run_settings(cfg)
            rs.focus_days = focus
            tasks.append(self.runner.run(get_source(cfg.name), query, rs))

        results: list[SourceRunResult] = await asyncio.gather(*tasks)
        await self._update_health(results)

        offers: list[FlightOffer] = []
        for r in results:
            offers += r.offers
            statuses.append(SourceStatus(r.source, r.ok, len(r.offers), r.error))
        return offers, statuses

    async def _focus_days(self, query: SearchQuery) -> list[date] | None:
        """На длинном диапазоне — самые дешёвые дни по календарю (для источников «по одному дню»)."""
        if len(query.dates()) <= MAX_SEARCH_DAYS:
            return None
        try:
            cal = await self.calendar(query.origin, query.destination, query.date_from, query.date_to)
        except Exception:  # noqa: BLE001 — без подсказки источники разложат дни равномерно
            log.exception("focus days calendar failed")
            return None
        return sorted(sorted(cal, key=cal.get)[:MAX_SEARCH_DAYS]) or None

    async def calendar(self, origin: str, destination: str, date_from: date, date_to: date) -> dict[date, int]:
        """Минимальная цена за 1 взрослого по дням вылета из всех календарных источников."""
        key = f"cal:{origin}:{destination}:{date_from}:{date_to}"
        if cached := await self.cache.get(key):
            return {date.fromisoformat(k): v for k, v in json.loads(cached).items()}

        async with session_scope() as s:
            configs = (await s.scalars(select(SourceConfig).where(SourceConfig.enabled.is_(True)))).all()
        registered = all_sources()
        now = datetime.now(timezone.utc)

        async def one(cfg: SourceConfig) -> dict[date, int]:
            rs = self._run_settings(cfg)
            ctx = SourceContext(http=self.runner.client(rs.proxy), params=rs.params or {}, timeout_s=rs.timeout_s)
            try:
                return await asyncio.wait_for(
                    get_source(cfg.name).calendar(origin, destination, date_from, date_to, ctx), rs.timeout_s * 2
                )
            except Exception as e:  # noqa: BLE001
                log.warning("calendar %s failed: %s", cfg.name, e)
                return {}

        eligible = [
            c for c in configs
            if c.name in registered and registered[c.name].supports_calendar
            and not ((until := as_utc(c.disabled_until)) and until > now)
        ]
        merged: dict[date, int] = {}
        for part in await asyncio.gather(*(one(c) for c in eligible)):
            for d, p in part.items():
                if d not in merged or p < merged[d]:
                    merged[d] = p

        await self.cache.set(key, dumps({d.isoformat(): p for d, p in merged.items()}), CALENDAR_TTL_S)
        if merged:
            async with session_scope() as s:
                s.add_all(
                    PriceSnapshot(origin=origin, destination=destination, departure_date=d, source="calendar",
                                  price_rub=p, kind="calendar", collected_at=now)
                    for d, p in merged.items()
                )
        return merged

    def _run_settings(self, cfg: SourceConfig) -> RunSettings:
        params = dict(cfg.params or {})
        if cfg.name == "aviasales_api":
            params.setdefault("token", self.settings.travelpayouts_token)
            params.setdefault("marker", self.settings.travelpayouts_marker)
        return RunSettings(
            timeout_s=cfg.timeout_s,
            retries=cfg.retries,
            rate_limit_per_min=cfg.rate_limit_per_min,
            proxy=cfg.proxy or self.settings.http_proxy or None,
            params=params,
        )

    async def _update_health(self, results: list[SourceRunResult]) -> None:
        now = datetime.now(timezone.utc)
        went_down: list[tuple[str, str]] = []
        async with session_scope() as s:
            for r in results:
                cfg = await s.get(SourceConfig, r.source)
                if cfg is None:
                    continue
                if r.ok:
                    cfg.consecutive_failures = 0
                    cfg.last_success_at = now
                    cfg.disabled_until = None
                    SOURCE_UP.labels(r.source).set(1)
                    continue
                cfg.consecutive_failures += 1
                cfg.last_error = r.error
                cfg.last_error_at = now
                if cfg.consecutive_failures >= self.settings.source_failure_threshold:
                    cfg.disabled_until = now + timedelta(minutes=self.settings.source_cooldown_min)
                    cfg.consecutive_failures = 0
                    SOURCE_UP.labels(r.source).set(0)
                    went_down.append((r.source, r.error or ""))

        for name, error in went_down:
            log.error("Источник %s отключён на %d мин: %s", name, self.settings.source_cooldown_min, error)
            if self.on_source_down:
                try:
                    await self.on_source_down(name, error)
                except Exception:  # noqa: BLE001
                    log.exception("on_source_down hook failed")

    async def _save_snapshots(self, query: SearchQuery, offers: list[FlightOffer]) -> None:
        if not offers:
            return
        pax = max(query.passengers, 1)
        async with session_scope() as s:
            s.add_all(
                PriceSnapshot(
                    origin=query.origin,
                    destination=query.destination,
                    departure_date=o.departure_date,
                    departure_at=o.departure_at,
                    source=o.source,
                    # В истории храним цену за одного пассажира, чтобы сравнивать разные запросы
                    price_rub=o.price_rub // pax,
                    transfers=o.transfers,
                    duration_min=o.duration_min,
                    airline=",".join(o.airlines) or None,
                    flight_numbers=",".join(o.flight_numbers) or None,
                    kind="search",
                    collected_at=o.collected_at,
                )
                for o in offers
            )
