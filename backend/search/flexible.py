"""Гибкие даты: «если сдвинуть вылет на пару дней — будет дешевле».

Смотрим календарь цен в окне ±FLEX_DAYS вокруг выбранных дат и подсказываем день,
где минимальная цена заметно ниже лучшей найденной на выбранные даты.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta

from search.orchestrator import SearchService

FLEX_DAYS = 3
MIN_SAVING = 0.08  # подсказываем, только если дешевле хотя бы на 8%


@dataclass
class FlexHint:
    day: date
    price_per_pax: int
    saving_per_pax: int
    saving_pct: float


async def flexible_hint(
    svc: SearchService,
    origins: list[str],
    destinations: list[str],
    date_from: date,
    date_to: date,
    best_per_pax: int | None,
    today: date | None = None,
) -> FlexHint | None:
    if best_per_pax is None:
        return None
    today = today or date.today()
    w_from = max(date_from - timedelta(days=FLEX_DAYS), today)
    w_to = date_to + timedelta(days=FLEX_DAYS)
    pairs = [(o, d) for o in origins for d in destinations if o != d]
    merged: dict[date, int] = {}
    for cal in await asyncio.gather(*(svc.calendar(o, d, w_from, w_to) for o, d in pairs)):
        for d, p in cal.items():
            if d not in merged or p < merged[d]:
                merged[d] = p
    outside = {d: p for d, p in merged.items() if not (date_from <= d <= date_to)}
    return pick_hint(outside, best_per_pax)


def pick_hint(prices: dict[date, int], best_per_pax: int) -> FlexHint | None:
    if not prices:
        return None
    day = min(prices, key=lambda d: (prices[d], d))
    price = prices[day]
    saving = best_per_pax - price
    if saving <= 0 or saving / best_per_pax < MIN_SAVING:
        return None
    return FlexHint(day, price, saving, saving / best_per_pax * 100)
