"""OneTwoTrip — живой поиск.

Исследование (октябрь 2026): открытый JSON без капчи —
www.onetwotrip.com/_api/searching/startSync2/?route=2011HRGMOW&ad=1&cn=0&in=0&cs=E
• frs — тарифы: цена prcInf.amt (за всех пассажиров), dirs[0].trps — ссылки на сегменты
  с признаками selfConnect (самостоятельная пересадка) и багажом bg ("0PC", "1PC", "20K")
• trps — сегменты: дата/время МЕСТНЫЕ без смещения → часовой пояс из справочника аэропортов

В выдаче регулярно встречаются мусорные тарифы (≈1 млн ₽ за HRG→MOW) — отсекаем
по абсолютному потолку и по отклонению от медианы.
"""

from __future__ import annotations

import asyncio
import statistics
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from common.airports import airports
from sources.base import FlightOffer, SearchQuery, Segment, Source, SourceContext, SourceError, focus_days
from sources.registry import register

SEARCH_URL = "https://www.onetwotrip.com/_api/searching/startSync2/"
SITE_URL = "https://www.onetwotrip.com"
HEADERS = {"Referer": SITE_URL + "/ru/", "Accept": "application/json"}
MAX_PRICE_PER_PAX = 300_000
MAX_MEDIAN_FACTOR = 5


@register
class OneTwoTripSource(Source):
    name = "onetwotrip"
    title = "OneTwoTrip"
    method = "json"
    default_timeout_s = 40.0

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        await airports.ensure_loaded(ctx.http)
        sem = asyncio.Semaphore(3)

        async def one(day) -> list[FlightOffer]:
            async with sem:
                route = f"{day:%d%m}{query.origin}{query.destination}"
                return parse_response(await self._fetch(ctx, query, route), query, route)

        offers: list[FlightOffer] = []
        for part in await asyncio.gather(*(one(d) for d in focus_days(query, ctx))):
            offers += part
        return offers

    async def _fetch(self, ctx: SourceContext, q: SearchQuery, route: str) -> dict[str, Any]:
        params = {"route": route, "ad": q.adults, "cn": q.children, "in": q.infants, "cs": "E", "source": "web"}
        resp = await ctx.http.get(SEARCH_URL, params=params, headers=HEADERS, timeout=ctx.timeout_s)
        if resp.status_code >= 400:
            raise SourceError(f"OneTwoTrip: HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise SourceError("OneTwoTrip: не удалось разобрать ответ") from e


def _local(date_s: str, time_s: str, code: str, day_shift: int = 0) -> datetime:
    tz = airports.tz(code) or "UTC"
    dt = datetime.strptime(date_s + time_s, "%Y%m%d%H%M") + timedelta(days=day_shift)
    return dt.replace(tzinfo=ZoneInfo(tz))


def _has_baggage(code: str | None) -> bool | None:
    if not code:
        return None
    digits = "".join(ch for ch in code if ch.isdigit())
    return int(digits or 0) > 0


def parse_response(data: dict[str, Any], q: SearchQuery, route: str) -> list[FlightOffer]:
    trps = data.get("trps") or []
    pax = max(q.passengers, 1)
    raw: list[tuple[float, FlightOffer]] = []
    for fare in data.get("frs") or []:
        dirs = fare.get("dirs") or []
        price = (fare.get("prcInf") or {}).get("amt")
        if len(dirs) != 1 or not price or (fare.get("prcInf") or {}).get("cur", "RUB") != "RUB":
            continue
        refs = dirs[0].get("trps") or []
        try:
            chain = [trps[r["id"]] for r in refs]
        except (IndexError, KeyError):
            continue
        if not chain:
            continue
        segments = []
        for s in chain:
            dep = _local(s["stDt"], s["stTm"], s["from"])
            arr = _local(s["stDt"], s["endTm"], s["to"], int(s.get("dayChg") or 0))
            segments.append(
                Segment(
                    origin=s["from"], destination=s["to"], departure_at=dep, arrival_at=arr,
                    airline=s.get("airCmp"), flight_number=f"{s.get('airCmp', '')}{int(s['fltNm']) if str(s.get('fltNm', '')).isdigit() else s.get('fltNm', '')}",
                )
            )
        raw.append(
            (
                price / pax,
                FlightOffer(
                    source="onetwotrip",
                    price_rub=round(price),
                    price_original=float(price),
                    origin_airport=segments[0].origin,
                    destination_airport=segments[-1].destination,
                    departure_at=segments[0].departure_at,
                    arrival_at=segments[-1].arrival_at,
                    duration_min=int((segments[-1].arrival_at - segments[0].departure_at).total_seconds() // 60),
                    transfers=len(segments) - 1,
                    airlines=list(dict.fromkeys(s.airline for s in segments if s.airline)),
                    flight_numbers=[s.flight_number for s in segments],
                    segments=segments,
                    route_airports=[segments[0].origin] + [s.destination for s in segments],
                    baggage_included=_has_baggage(dirs[0].get("bg")),
                    self_transfer=any(r.get("selfConnect") for r in refs),
                    link=f"{SITE_URL}/ru/f/search/{route}?s=true",
                ),
            )
        )
    if not raw:
        return []
    median = statistics.median(p for p, _ in raw)
    return [o for p, o in raw if p <= MAX_PRICE_PER_PAX and p <= median * MAX_MEDIAN_FACTOR]
