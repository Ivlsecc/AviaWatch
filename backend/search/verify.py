"""Перепроверка цен из кэша.

Aviasales Data API отдаёт цены, которые кто-то видел в последние дни, — к моменту
покупки их может уже не быть. Если такая цена попала в верх выдачи, сверяем её
с живыми сайтами по тому же рейсу:

* живой сайт нашёл рейс примерно за ту же цену — цена подтверждена;
* живой сайт нашёл рейс дороже — показываем живую цену, кэш упоминаем;
* живые сайты искали этот день и рейса не нашли — предупреждаем, что цена не подтверждена.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from common.airports import airports
from search.dedup import group_same_flights
from search.filters import FilterSettings
from search.orchestrator import SearchService, SourceStatus
from sources.base import MAX_SEARCH_DAYS, FlightOffer, SearchQuery
from sources.registry import all_sources

log = logging.getLogger(__name__)

# Сколько верхних предложений выдачи проверяем
TOP_N = 5
# Не больше стольких дополнительных однодневных поисков на выдачу
MAX_EXTRA_DAYS = 3
# Живая цена в пределах этого допуска от кэша — считаем, что цена та же
TOLERANCE = 0.03


def cached_sources() -> set[str]:
    return {name for name, cls in all_sources().items() if not cls.live}


def live_sources() -> set[str]:
    return {name for name, cls in all_sources().items() if cls.live}


def apply_live_price(o: FlightOffer, live_price: int, live_source: str, live_link: str) -> None:
    if live_price <= o.price_rub * (1 + TOLERANCE):
        o.price_check = "confirmed"
        if live_price < o.price_rub:
            o.price_rub, o.source, o.link = live_price, live_source, live_link
        return
    o.price_check = "updated"
    o.cached_price_rub = o.price_rub
    o.price_rub, o.source, o.link = live_price, live_source, live_link


async def verify_cached_prices(
    svc: SearchService,
    queries: list[SearchQuery],
    offers: list[FlightOffer],
    filters: FilterSettings,
    statuses: list[SourceStatus],
) -> list[FlightOffer]:
    """Сверяет верхние цены из кэша с живыми сайтами. Возвращает выдачу, заново отсортированную по цене."""
    cached = cached_sources()
    live_ok = any(st.ok and st.source not in cached and st.source != "combo" for st in statuses)
    targets = [o for o in offers[:TOP_N] if o.source in cached and not o.legs_links]
    if not targets or not live_ok:
        return offers

    need_search: dict[tuple[str, str, date], SearchQuery] = {}
    pending: list[FlightOffer] = []
    for o in targets:
        live_alts = [a for a in o.alt_links if a[0] not in cached]
        if live_alts:
            # Тот же рейс уже нашёлся на живом сайте — дороже, иначе он был бы основным
            src, price, link = min(live_alts, key=lambda a: a[1])
            apply_live_price(o, price, src, link)
            if o.price_check == "updated":
                o.alt_links = [a for a in o.alt_links if a[0] != src]
            continue
        q = _query_for(o, queries)
        if q is None:
            continue
        day = o.departure_date
        if day not in await _days_searched_live(svc, q):
            key = (q.origin, q.destination, day)
            if key not in need_search and len(need_search) >= MAX_EXTRA_DAYS:
                continue
            need_search[key] = q.model_copy(update={"date_from": day, "date_to": day})
        pending.append(o)

    live_found: list[FlightOffer] = []
    if need_search:
        only = live_sources()
        results = await asyncio.gather(
            *(svc.search(q, filters, only_sources=only, log_search=False) for q in need_search.values()),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, BaseException):
                log.warning("price verification search failed: %s", r)
                continue
            live_found += r.offers
    # Живые предложения из основной выдачи тоже годятся для сверки
    live_found += [x for x in offers if x.source not in cached]

    for o in pending:
        match = _same_flight(o, live_found)
        if match:
            apply_live_price(o, match.price_rub, match.source, match.link)
        else:
            o.price_check = "unconfirmed"

    return sorted(offers, key=lambda o: (o.price_rub, o.departure_at))


def _query_for(o: FlightOffer, queries: list[SearchQuery]) -> SearchQuery | None:
    for q in queries:
        if airports.matches(o.origin_airport, q.origin) and airports.matches(o.destination_airport, q.destination):
            return q
    return None


async def _days_searched_live(svc: SearchService, q: SearchQuery) -> set[date]:
    days = q.dates()
    if len(days) <= MAX_SEARCH_DAYS:
        return set(days)
    # Длинный диапазон: «подневные» источники искали только самые дешёвые дни календаря
    return set(await svc._focus_days(q) or [])


def _same_flight(o: FlightOffer, candidates: list[FlightOffer]) -> FlightOffer | None:
    probe = o.model_copy(update={"alt_links": []})
    for group in group_same_flights([probe, *candidates]):
        if any(x is probe for x in group):
            others = [x for x in group if x is not probe]
            return min(others, key=lambda x: x.price_rub) if others else None
    return None
