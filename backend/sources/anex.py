"""ANEX Tour — билеты «только перелёт» на чартеры туроператора.

Исследование (октябрь 2026): открытый JSON без капчи на api.anextour.ru/Ticket/:
  Sources                — аэропорты вылета (id вида "town.port", напр. Хургада 225.18);
  Targets?source=        — куда можно улететь из этого аэропорта (есть и город целиком: Москва = "2");
  Checkins?source&target — строка доступности по дням от startDate ('0' — рейса нет);
  Prices?...&checkin=    — варианты на день, цена за всех пассажиров в TotalCost.

Из Египта в Россию Anex продаёт остатки мест на своих чартерах (Nesma и др.)
на ближайшие 2–4 дня: на дальние даты обычно пусто. Багаж включён.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from common.airports import airports
from sources.base import FlightOffer, SearchQuery, Segment, Source, SourceContext, SourceError
from sources.registry import register

API_URL = "https://api.anextour.ru/Ticket/"
SITE_URL = "https://anextour.ru"
HEADERS = {"Origin": SITE_URL, "Referer": SITE_URL + "/", "Accept": "application/json"}

# Справочник аэропортов меняется редко — держим в памяти процесса
_PORTS_TTL_S = 6 * 3600
_ports_cache: tuple[float, list[dict[str, Any]]] | None = None


def port_code(p: dict[str, Any]) -> str:
    # «VKO-A» (Внуково, терминал A) → VKO
    return (p.get("portAlias") or p.get("townIATA") or "").split("-")[0].upper()


def pick_points(points: list[dict[str, Any]], wanted: str) -> list[dict[str, Any]]:
    """Точки Anex под код запроса. Для города берём «город целиком» (id без порта), если он есть."""
    town = [p for p in points if "." not in str(p["id"]) and wanted in (p.get("townIATA"), port_code(p))]
    if town:
        return town
    return [p for p in points if "." in str(p["id"]) and port_code(p) and airports.matches(port_code(p), wanted)]


def available_days(checkins: dict[str, Any], days: list[date]) -> list[date]:
    start = datetime.strptime(checkins["startDate"], "%Y%m%d").date()
    flags = checkins.get("validDates") or ""
    result = []
    for d in days:
        i = (d - start).days
        if 0 <= i < len(flags) and flags[i] != "0":
            result.append(d)
    return result


def search_link(source_id: str, target_id: str, q: SearchQuery, day: date) -> str:
    params = {
        "airFrom": source_id, "airTo": target_id, "isCharter": 1,
        "CHECKIN_BEG": day.strftime("%Y%m%d"), "CHECKIN_END": day.strftime("%Y%m%d"),
        "ADULT": q.adults, "CHILD": q.children, "CURRENCY": 1, "classId": 0,
    }
    return f"{SITE_URL}/search/avia?{urlencode(params)}"


@register
class AnexSource(Source):
    name = "anex"
    title = "ANEX Tour (чартеры)"
    method = "json"
    may_be_empty = True
    default_timeout_s = 30.0
    # С VPN-адресов api.anextour.ru не отвечает (ConnectTimeout), напрямую — за секунду
    default_proxy = "direct"
    param_schema = {"with_regular": "bool — искать и регулярные рейсы (по умолчанию только чартеры)"}

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        await airports.ensure_loaded(ctx.http)
        regular = "true" if ctx.params.get("with_regular") else "false"

        async def get(method: str, **params: Any) -> dict[str, Any]:
            resp = await ctx.http.get(API_URL + method, params=params, headers=HEADERS, timeout=ctx.timeout_s)
            if resp.status_code >= 400:
                raise SourceError(f"Anex {method}: HTTP {resp.status_code}")
            return resp.json()

        global _ports_cache
        if _ports_cache is None or time.monotonic() - _ports_cache[0] > _PORTS_TTL_S:
            body = await get("Sources", withCharter="true", withRegular=regular)
            _ports_cache = (time.monotonic(), body.get("Tickets_SOURCES") or [])
        origins = pick_points(_ports_cache[1], query.origin)
        if not origins:
            return []

        offers: list[FlightOffer] = []
        sem = asyncio.Semaphore(3)

        async def route(src: dict[str, Any]) -> None:
            async with sem:
                targets = (await get("Targets", source=src["id"], withCharter="true", withRegular=regular)).get("Tickets_TARGETS") or []
            for trg in pick_points(targets, query.destination):
                async with sem:
                    ci = (await get("Checkins", freightBack="false", source=src["id"], target=trg["id"])).get("Tickets_CHECKINS")
                if not ci:
                    continue
                for day in available_days(ci, query.dates()):
                    async with sem:
                        body = await get(
                            "Prices", adult=query.adults, child=query.children, ages="false", classId=0, currencyInc=1,
                            directFlight="false", source=src["id"], target=trg["id"], checkin=day.strftime("%Y%m%d"),
                            withCharter="true", withRegular=regular,
                        )
                    offers.extend(parse_prices(body, search_link(src["id"], trg["id"], query, day)))

        await asyncio.gather(*(route(s) for s in origins))
        return offers


def _local(day: str, hhmm: str, code: str) -> datetime:
    tz = ZoneInfo(airports.tz(code) or "UTC")
    return datetime.strptime(f"{day} {hhmm}", "%Y%m%d %H:%M").replace(tzinfo=tz)


def parse_prices(body: dict[str, Any], link: str) -> list[FlightOffer]:
    offers = []
    for p in body.get("Tickets_PRICES") or []:
        # BlockStatusIn=0 — «нет мест»: цену показывают, но купить нельзя
        if not p.get("BlockStatusIn") or not p.get("TotalCost"):
            continue
        origin = (p.get("SrcPortAlias") or "").split("-")[0]
        dest = (p.get("TrgPortAlias") or "").split("-")[0]
        if not origin or not dest:
            continue
        dep = _local(p["DateBeg"], p["SrcTime"], origin)
        arr = _local(p.get("DateEnd") or p["DateBeg"], p["TrgTime"], dest)
        if arr <= dep:
            arr += timedelta(days=1)
        flight = (p.get("FreightName") or "").replace(" ", "")
        airline = flight[:2] if flight else None
        stops = int(p.get("StopsTo") or 0)
        notes = ["чартер туроператора"]
        if p.get("bagageInfoTo"):
            notes.append(f"багаж {p['bagageInfoTo'].lower()}")
        if p.get("BlockCountIn") and p["BlockCountIn"] != "есть":
            notes.append(p["BlockCountIn"])
        segments = [] if stops else [
            Segment(origin=origin, destination=dest, departure_at=dep, arrival_at=arr, airline=airline, flight_number=flight)
        ]
        offers.append(
            FlightOffer(
                source="anex",
                price_rub=int(float(p["TotalCost"])),
                price_original=float(p["TotalCost"]),
                origin_airport=origin,
                destination_airport=dest,
                departure_at=dep,
                arrival_at=arr,
                duration_min=int(p.get("FlyTimeMinTo") or (arr - dep).total_seconds() // 60),
                transfers=stops,
                airlines=[airline] if airline else [],
                flight_numbers=[flight] if flight else [],
                segments=segments,
                route_airports=[origin, dest] if not stops else [],
                baggage_included=bool(p.get("bagage")),
                self_transfer=False,
                link=link,
                note=", ".join(notes),
            )
        )
    return offers
