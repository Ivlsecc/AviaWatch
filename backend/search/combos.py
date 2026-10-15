"""Составные маршруты: два отдельных билета через пересадочный хаб.

Агрегаторы почти не склеивают билеты разных перевозчиков через хаб (Хургада → Стамбул
на одной компании + Стамбул → Москва на другой), хотя иногда это заметно дешевле.
Ищем «ноги» отдельно быстрыми источниками и комбинируем с безопасным запасом на стыковку.

Это самостоятельная пересадка: багаж перерегистрировать, при опоздании первого рейса
второй билет сгорает. Поэтому функция опциональна (FilterSettings.self_combos) и
показываем только варианты заметно дешевле обычных билетов.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from common.airports import airports
from search.filters import FilterSettings
from search.orchestrator import SearchService
from sources.base import FlightOffer, SearchQuery

log = logging.getLogger(__name__)

# Хабы, через которые реально летают из Египта и Турции в Россию и обратно
HUBS = ["IST", "AYT", "CAI", "DXB", "SHJ", "AUH", "EVN", "TBS", "GYD", "DOH"]
FAST_SOURCES = {"kupibilet", "aviakassa", "onetwotrip"}
MIN_CONNECTION_MIN = 3 * 60
MIN_CONNECTION_CHANGE_AIRPORT_MIN = 5 * 60
MAX_CONNECTION_MIN = 20 * 60
LEG_CANDIDATES = 12
MAX_HUBS = 6
MAX_COMBOS = 10
# Показываем, только если дешевле лучшего обычного билета хотя бы на столько
MIN_SAVING = 0.07

LEG_FILTERS = FilterSettings(max_transfers=0, max_duration_factor=None)


def combine(leg1: list[FlightOffer], leg2: list[FlightOffer], limit: int = MAX_COMBOS) -> list[FlightOffer]:
    """Пары «прилёт в хаб → вылет из хаба» с безопасной стыковкой, по возрастанию цены."""
    combos: list[FlightOffer] = []
    a_list = sorted((o for o in leg1 if o.time_known and o.arrival_at), key=lambda o: o.price_rub)[:LEG_CANDIDATES]
    b_list = sorted((o for o in leg2 if o.time_known), key=lambda o: o.price_rub)[:LEG_CANDIDATES]
    for a in a_list:
        for b in b_list:
            if airports.city(a.destination_airport) != airports.city(b.origin_airport):
                continue
            change = a.destination_airport != b.origin_airport
            gap = (b.departure_at - a.arrival_at).total_seconds() / 60
            min_gap = MIN_CONNECTION_CHANGE_AIRPORT_MIN if change else MIN_CONNECTION_MIN
            if not (min_gap <= gap <= MAX_CONNECTION_MIN):
                continue
            combos.append(_join(a, b, int(gap), change))
    # При равной цене удобнее без смены аэропорта и короче
    combos.sort(key=lambda o: (o.price_rub, bool(o.airport_change), o.duration_min or 0))
    return combos[:limit]


def _join(a: FlightOffer, b: FlightOffer, gap_min: int, change: bool) -> FlightOffer:
    hub = airports.name(a.destination_airport)
    h, m = divmod(gap_min, 60)
    note = f"составной маршрут: 2 отдельных билета, стыковка {h} ч {m:02d} мин в {hub}"
    if change:
        note += f", смена аэропорта {a.destination_airport}→{b.origin_airport}"
    note += "; багаж перерегистрировать, при опоздании первого рейса второй билет не перенесут"
    route = a.route_airports or [a.origin_airport, a.destination_airport]
    route2 = b.route_airports or [b.origin_airport, b.destination_airport]
    return FlightOffer(
        source="combo",
        price_rub=a.price_rub + b.price_rub,
        origin_airport=a.origin_airport,
        destination_airport=b.destination_airport,
        departure_at=a.departure_at,
        arrival_at=b.arrival_at,
        duration_min=int((b.arrival_at - a.departure_at).total_seconds() // 60) if b.arrival_at else None,
        transfers=a.transfers + b.transfers + 1,
        airlines=list(dict.fromkeys(a.airlines + b.airlines)),
        flight_numbers=a.flight_numbers + b.flight_numbers,
        segments=a.segments + b.segments,
        route_airports=route + (route2[1:] if route2[0] == route[-1] else route2),
        airport_change=change,
        baggage_included=(a.baggage_included and b.baggage_included) if None not in (a.baggage_included, b.baggage_included) else None,
        self_transfer=True,
        link=a.link,
        legs_links=[("1-й билет", a.price_rub, a.link), ("2-й билет", b.price_rub, b.link)],
        note=note,
    )


async def find_combos(svc: SearchService, query: SearchQuery, hubs: list[str] | None = None) -> list[FlightOffer]:
    hubs = [h for h in (hubs or HUBS) if airports.city(h) not in {airports.city(query.origin), airports.city(query.destination)}]
    hubs = hubs[:MAX_HUBS]
    if not hubs:
        return []

    async def leg(o: str, d: str, days: int) -> list[FlightOffer]:
        q = query.model_copy(update={
            "origin": o, "destination": d, "date_to": query.date_to + timedelta(days=days), "direct_only": False,
        })
        try:
            res = await svc.search(q, LEG_FILTERS, only_sources=FAST_SOURCES, log_search=False)
            return res.offers
        except Exception:  # noqa: BLE001 — одна нога не должна ронять поиск
            log.exception("combo leg %s→%s failed", o, d)
            return []

    firsts = await asyncio.gather(*(leg(query.origin, h, 0) for h in hubs))
    seconds = await asyncio.gather(*(leg(h, query.destination, 1) for h in hubs))
    combos: list[FlightOffer] = []
    for a, b in zip(firsts, seconds):
        combos += combine(a, b)
    combos = [c for c in combos if query.date_from <= c.departure_date <= query.date_to]
    combos.sort(key=lambda o: o.price_rub)
    return combos[:MAX_COMBOS]


def worth_showing(combos: list[FlightOffer], regular: list[FlightOffer]) -> list[FlightOffer]:
    """Оставляем составные маршруты, которые дешевле лучшего обычного билета хотя бы на MIN_SAVING."""
    if not regular:
        return combos
    best = min(o.price_rub for o in regular)
    return [c for c in combos if c.price_rub <= best * (1 - MIN_SAVING)]
