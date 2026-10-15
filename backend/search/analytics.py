"""Средняя цена по маршруту.

Окно — вылеты в [сегодня−30; сегодня+30] (от даты ЗАПРОСА, не от даты вылета):
«сколько сейчас в среднем стоит лететь по этому маршруту без раннего бронирования».
Будущая половина — календарь цен из API, прошлая — наша накопленная история.
"""

from __future__ import annotations

import asyncio
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select

from common.db import session_scope
from common.models import PriceSnapshot
from search.orchestrator import SearchService

WINDOW_DAYS = 30


@dataclass
class PriceStats:
    mean: int | None
    median: int | None
    days: int  # сколько дней с ценами вошло в расчёт
    past_days: int  # из них из истории (прошлые даты)
    window_from: date
    window_to: date

    @property
    def has_history(self) -> bool:
        return self.past_days > 0


async def route_price_stats(
    svc: SearchService, origins: list[str], destinations: list[str], today: date | None = None
) -> PriceStats:
    today = today or date.today()
    w_from, w_to = today - timedelta(days=WINDOW_DAYS), today + timedelta(days=WINDOW_DAYS)

    pairs = [(o, d) for o in origins for d in destinations if o != d]
    future: dict[date, int] = {}
    for cal in await asyncio.gather(*(svc.calendar(o, d, today, w_to) for o, d in pairs)):
        for d, p in cal.items():
            if d not in future or p < future[d]:
                future[d] = p

    past = await _past_daily_min(origins, destinations, w_from, today - timedelta(days=1))
    return compute_stats(past, future, w_from, w_to)


def compute_stats(past: dict[date, int], future: dict[date, int], w_from: date, w_to: date) -> PriceStats:
    prices = list(past.values()) + list(future.values())
    if not prices:
        return PriceStats(None, None, 0, 0, w_from, w_to)
    return PriceStats(
        mean=round(statistics.fmean(prices)),
        median=round(statistics.median(prices)),
        days=len(prices),
        past_days=len(past),
        window_from=w_from,
        window_to=w_to,
    )


async def _past_daily_min(origins: list[str], destinations: list[str], d_from: date, d_to: date) -> dict[date, int]:
    if d_from > d_to:
        return {}
    async with session_scope() as s:
        rows = await s.execute(
            select(PriceSnapshot.departure_date, func.min(PriceSnapshot.price_rub))
            .where(
                PriceSnapshot.origin.in_(origins),
                PriceSnapshot.destination.in_(destinations),
                PriceSnapshot.departure_date.between(d_from, d_to),
            )
            .group_by(PriceSnapshot.departure_date)
        )
        return {d: p for d, p in rows.all()}
