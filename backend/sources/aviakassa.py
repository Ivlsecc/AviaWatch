"""Авиакасса — живой поиск.

Исследование (октябрь 2026): открытый JSON без капчи —
www.aviakassa.com/api/v4/avia/search/get-recommendations с теми же параметрами,
что в адресе страницы поиска. Отвечает за ≈1 с, до 100 вариантов на страницу,
отсортированных по цене. Время в сегментах — unix ts + часовой пояс.

Сайт не проходит TLS через некоторые VPN-прокси, поэтому по умолчанию источник
ходит напрямую (proxy = "direct").

Флаг is_russian_passport_acceptable=false стоит у всех международных вариантов —
это про внутренний паспорт РФ, не про загран; не используем.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sources.base import FlightOffer, SearchQuery, Segment, Source, SourceContext, SourceError, focus_days
from sources.registry import register

API_URL = "https://www.aviakassa.com/api/v4/avia/search/get-recommendations"
SITE_URL = "https://www.aviakassa.com"
HEADERS = {"Referer": SITE_URL + "/", "Accept": "application/json"}


def _params(q: SearchQuery, day: date) -> dict[str, Any]:
    return {
        "adt": q.adults,
        "chd": q.children,
        "inf": q.infants,
        "class": "e",
        "is_direct_only": int(q.direct_only),
        "segments[0][0][from]": q.origin,
        "segments[0][0][to]": q.destination,
        "segments[0][0][date]": day.strftime("%d.%m.%Y"),
        "sort[by]": "price",
        "sort[direction]": "asc",
        "page[number]": 1,
        "page[limit]": 100,
    }


def search_link(q: SearchQuery, day: date) -> str:
    return f"{SITE_URL}/avia/search?{urlencode(_params(q, day))}"


@register
class AviakassaSource(Source):
    name = "aviakassa"
    title = "Авиакасса"
    method = "json"
    default_proxy = "direct"
    default_timeout_s = 30.0

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        sem = asyncio.Semaphore(3)

        async def one(day: date) -> list[FlightOffer]:
            async with sem:
                params = {**_params(query, day), "lang": "ru", "partner": "AKV4", "channel_code": "AKV40000"}
                resp = await ctx.http.get(API_URL, params=params, headers=HEADERS, timeout=ctx.timeout_s)
                if resp.status_code >= 400:
                    raise SourceError(f"Авиакасса: HTTP {resp.status_code}")
                body = resp.json()
                if not body.get("success", True):
                    raise SourceError(f"Авиакасса: {body.get('error') or body.get('code')}")
                return parse_response(body, query, day)

        offers: list[FlightOffer] = []
        for part in await asyncio.gather(*(one(d) for d in focus_days(query, ctx))):
            offers += part
        return offers


def _point(p: dict[str, Any]) -> tuple[str, datetime]:
    # Не используем p["ts"]: у Авиакассы он сдвинут на час для Египта зимой
    # (00:20 местного → 23:20 накануне). Местное время строкой + пояс — точнее.
    tz = ZoneInfo(p.get("timezone") or "UTC")
    local = datetime.strptime(p["datetime"], "%d.%m.%Y %H:%M:%S").replace(tzinfo=tz)
    return p["airport"]["code"], local


def parse_response(body: dict[str, Any], q: SearchQuery, day: date) -> list[FlightOffer]:
    link = search_link(q, day)
    offers = []
    for r in (body.get("data") or {}).get("recommendations") or []:
        raw = [s for s in r.get("segments") or [] if s.get("direction", 0) == 0]
        price = ((r.get("price") or {}).get("RUB") or {}).get("amount")
        if not raw or not price:
            continue
        segments = []
        for s in raw:
            dep_code, dep_at = _point(s["dep"])
            arr_code, arr_at = _point(s["arr"])
            airline = (s.get("marketing_supplier") or {}).get("code")
            segments.append(
                Segment(
                    origin=dep_code, destination=arr_code, departure_at=dep_at, arrival_at=arr_at,
                    airline=airline, flight_number=f"{airline or ''}{s.get('flight_number', '')}",
                )
            )
        notes = []
        if r.get("is_charter"):
            notes.append("чартер")
        if r.get("tariff_name"):
            notes.append(f"тариф {r['tariff_name'].lower()}")
        offers.append(
            FlightOffer(
                source="aviakassa",
                price_rub=int(price),
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
                baggage_included=bool(r.get("is_baggage")),
                self_transfer=bool(r.get("is_vtrip") or r.get("is_different_tickets")),
                link=link,
                note=", ".join(notes) or None,
            )
        )
    return offers
