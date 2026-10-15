"""Купибилет — живой поиск авиабилетов.

Исследование (октябрь 2026): сайт без капчи и WAF, фронт ходит в открытый JSON API
api-rs-lb.kupibilet.ru/frontend_search (POST). Один запрос ≈ 3 с и ≈ 400 вариантов.
По Хургаде часто дешевле Aviasales и Туту.

Ответ: variants (цена за всех пассажиров, багаж, сегменты → id рейсов) + словари
flights / anyports / airlines. virtual_connection=true на рейсе — после него
самостоятельная пересадка (раздельные билеты). В выдаче бывают поезда — отсекаем.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sources.base import FlightOffer, SearchQuery, Segment, Source, SourceContext, SourceError, focus_days
from sources.registry import register

SEARCH_URL = "https://api-rs-lb.kupibilet.ru/frontend_search"
SITE_URL = "https://www.kupibilet.ru"
HEADERS = {"Origin": SITE_URL, "Referer": SITE_URL + "/"}


@register
class KupibiletSource(Source):
    name = "kupibilet"
    title = "Купибилет"
    method = "json"
    default_timeout_s = 30.0

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        days = focus_days(query, ctx)
        sem = asyncio.Semaphore(3)

        async def one(day: str) -> list[FlightOffer]:
            async with sem:
                return parse_response(await self._search_day(ctx, query, day), query, day)

        offers: list[FlightOffer] = []
        for part in await asyncio.gather(*(one(d.isoformat()) for d in days)):
            offers += part
        return offers

    async def _search_day(self, ctx: SourceContext, q: SearchQuery, day: str) -> dict[str, Any]:
        body = {
            "trips": [{"departure": q.origin, "arrival": q.destination, "date": day}],
            "travelers": {"adult": q.adults, "child": q.children, "infant": q.infants, "childrenAges": []},
            "cabin": "economy",
            "agent": "kup747",
            "language": "RU",
            "currency": "RUB",
            "client_platform": "web",
            "filters": {"transfer_count": [{"max": 0}]} if q.direct_only else {},
            "sort_by": "price",
            "short_response": False,
        }
        resp = await ctx.http.post(SEARCH_URL, json=body, headers=HEADERS, timeout=ctx.timeout_s)
        if resp.status_code >= 400:
            raise SourceError(f"Купибилет: HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise SourceError("Купибилет: не удалось разобрать ответ") from e


def search_link(q: SearchQuery, day: str) -> str:
    return (
        f"{SITE_URL}/search?route[0]=iatax:{q.origin}_{day}_date_{day}_iatax:{q.destination}"
        f"&adult={q.adults}&child={q.children}&infant={q.infants}&childrenAges=[]&cabinClass=Y&v=2"
    )


def parse_response(data: dict[str, Any], q: SearchQuery, day: str) -> list[FlightOffer]:
    flights = data.get("flights") or {}
    link = search_link(q, day)
    offers = []
    for v in data.get("variants") or []:
        segs = v.get("segments") or []
        if len(segs) != 1:  # только в одну сторону
            continue
        try:
            chain = [flights[fid] for fid in segs[0]["flights"]]
        except KeyError:
            continue
        if not chain or any(f.get("transport_kind") != "airplane" for f in chain):
            continue

        segments = [
            Segment(
                origin=f["departure"],
                destination=f["arrival"],
                departure_at=datetime.fromisoformat(f["departure_datetime"]),
                arrival_at=datetime.fromisoformat(f["arrival_datetime"]),
                airline=f.get("marketing_carrier"),
                flight_number=f"{f.get('marketing_carrier', '')}{f.get('number', '')}",
            )
            for f in chain
        ]
        bag = v.get("baggage") or {}
        notes = []
        if any(f.get("is_charter") for f in chain):
            notes.append("чартер")
        if v.get("seats_left"):
            notes.append(f"осталось мест: {v['seats_left']}")
        offers.append(
            FlightOffer(
                source="kupibilet",
                price_rub=int(float(v["price"]["amount"])),
                price_original=float(v["price"]["amount"]),
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
                baggage_included=(bag.get("count") or 0) > 0 or (bag.get("weight") or 0) > 0,
                # virtual_connection на последнем рейсе ничего не значит — пересадки после него нет
                self_transfer=any(f.get("virtual_connection") for f in chain[:-1]),
                link=link,
                note=", ".join(notes) or None,
            )
        )
    return offers
