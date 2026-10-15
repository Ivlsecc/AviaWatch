"""История цен: чтение (сырые снимки + дневные агрегаты), тренд и свёртка старых данных.

Все цены в истории — за одного пассажира.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from common.db import session_scope
from common.models import PriceDaily, PriceSnapshot
from search.orchestrator import as_utc

log = logging.getLogger(__name__)

RAW_KEEP_DAYS = 30


def _min_merge(target: dict, key, price: int) -> None:
    if key not in target or price < target[key]:
        target[key] = price


async def past_daily_min(origins: list[str], destinations: list[str], d_from: date, d_to: date) -> dict[date, int]:
    """Минимальная цена по каждой дате вылета в [d_from; d_to] за всё время наблюдений."""
    if d_from > d_to:
        return {}
    result: dict[date, int] = {}
    async with session_scope() as s:
        raw = await s.execute(
            select(PriceSnapshot.departure_date, func.min(PriceSnapshot.price_rub))
            .where(
                PriceSnapshot.origin.in_(origins),
                PriceSnapshot.destination.in_(destinations),
                PriceSnapshot.departure_date.between(d_from, d_to),
            )
            .group_by(PriceSnapshot.departure_date)
        )
        daily = await s.execute(
            select(PriceDaily.departure_date, func.min(PriceDaily.min_price))
            .where(
                PriceDaily.origin.in_(origins),
                PriceDaily.destination.in_(destinations),
                PriceDaily.departure_date.between(d_from, d_to),
            )
            .group_by(PriceDaily.departure_date)
        )
        for d, p in [*raw.all(), *daily.all()]:
            _min_merge(result, d, p)
    return result


@dataclass
class Trend:
    points: list[tuple[date, int]]  # (день наблюдения, лучшая цена в этот день)

    @property
    def enough(self) -> bool:
        return len(self.points) >= 2

    @property
    def change_pct(self) -> float | None:
        if not self.enough:
            return None
        first, last = self.points[0][1], self.points[-1][1]
        return (last - first) / first * 100

    @property
    def days(self) -> int:
        return (self.points[-1][0] - self.points[0][0]).days if self.enough else 0


async def price_trend(
    origins: list[str], destinations: list[str], dep_from: date, dep_to: date, days: int = 7, today: date | None = None
) -> Trend:
    """Как менялась лучшая цена на ВАШИ даты вылета за последние `days` дней наблюдений."""
    today = today or date.today()
    since = today - timedelta(days=days)
    by_day: dict[date, int] = {}
    async with session_scope() as s:
        raw = await s.execute(
            select(PriceSnapshot.collected_at, PriceSnapshot.price_rub).where(
                PriceSnapshot.origin.in_(origins),
                PriceSnapshot.destination.in_(destinations),
                PriceSnapshot.departure_date.between(dep_from, dep_to),
                PriceSnapshot.collected_at >= datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc),
            )
        )
        for collected_at, price in raw.all():
            _min_merge(by_day, as_utc(collected_at).date(), price)

        daily = await s.execute(
            select(PriceDaily.collected_date, func.min(PriceDaily.min_price))
            .where(
                PriceDaily.origin.in_(origins),
                PriceDaily.destination.in_(destinations),
                PriceDaily.departure_date.between(dep_from, dep_to),
                PriceDaily.collected_date >= since,
            )
            .group_by(PriceDaily.collected_date)
        )
        for d, p in daily.all():
            _min_merge(by_day, d, p)
    return Trend(sorted(by_day.items()))


async def roll_up_and_prune(keep_days: int = RAW_KEEP_DAYS, now: datetime | None = None) -> int:
    """Сворачивает сырые снимки старше keep_days в PriceDaily и удаляет их. Возвращает число удалённых."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=keep_days)
    agg: dict[tuple, list[int]] = {}
    async with session_scope() as s:
        rows = await s.execute(
            select(
                PriceSnapshot.origin, PriceSnapshot.destination, PriceSnapshot.departure_date,
                PriceSnapshot.collected_at, PriceSnapshot.price_rub,
            ).where(PriceSnapshot.collected_at < cutoff)
        )
        for o, d, dep, collected_at, price in rows.all():
            key = (o, d, dep, as_utc(collected_at).date())
            cur = agg.setdefault(key, [price, 0])
            cur[0] = min(cur[0], price)
            cur[1] += 1

        for (o, d, dep, cd), (price, n) in agg.items():
            existing = await s.get(PriceDaily, (o, d, dep, cd))
            if existing:
                existing.min_price = min(existing.min_price, price)
                existing.samples += n
            else:
                s.add(PriceDaily(origin=o, destination=d, departure_date=dep, collected_date=cd, min_price=price, samples=n))

        deleted = (await s.execute(delete(PriceSnapshot).where(PriceSnapshot.collected_at < cutoff))).rowcount or 0
    if deleted:
        log.info("История: свёрнуто %d снимков в %d дневных записей", deleted, len(agg))
    return deleted


LOG_KEEP_DAYS = 30


async def prune_logs(keep_days: int = LOG_KEEP_DAYS, now: datetime | None = None) -> int:
    """Удаляет журналы запросов к источникам, поисков и уведомлений старше keep_days."""
    from common.models import NotificationLog, SearchLog, SourceRunLog

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=keep_days)
    total = 0
    async with session_scope() as s:
        for model in (SourceRunLog, SearchLog, NotificationLog):
            total += (await s.execute(delete(model).where(model.created_at < cutoff))).rowcount or 0
    if total:
        log.info("Журналы: удалено %d записей старше %d дней", total, keep_days)
    return total
