"""Туту.ру — живой поиск авиабилетов.

Исследование (октябрь 2026): сайт ходит в собственные JSON API без капчи и WAF.
• suggester-avia.tutu.ru/api/location_suggest/v2?name=HRG — id города Туту по IATA
• offers-api.tutu.ru/avia/offers/v2 (POST) — поиск. Ответ — JSON-массив «пачек»
  (стрим), последняя содержит всё: offers.actual + словари маршрутов/сегментов/аэропортов
• calendar.tutu.ru/v2/min_price_calendar/ — минимальные цены по дням (за 1 взрослого)

Цена в offers — за всех пассажиров, в копейках (amount / fraction).
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date, datetime
from typing import Any

from sources.base import FlightOffer, SearchQuery, Segment, Source, SourceContext, SourceError
from sources.registry import register

SUGGEST_URL = "https://suggester-avia.tutu.ru/api/location_suggest/v2"
OFFERS_URL = "https://offers-api.tutu.ru/avia/offers/v2"
CALENDAR_URL = "https://calendar.tutu.ru/v2/min_price_calendar/"
HEADERS = {"Origin": "https://avia.tutu.ru", "Referer": "https://avia.tutu.ru/"}
MAX_DAYS = 5

# IATA → id города Туту. Справочник стабильный, кэшируем на всё время жизни процесса.
_CITY_IDS: dict[str, int] = {}


@register
class TutuSource(Source):
    name = "tutu"
    title = "Туту"
    method = "json"
    supports_calendar = True
    default_timeout_s = 45.0
    param_schema = {
        "limit": "Сколько предложений запрашивать за день (по умолчанию 100)",
        "max_days": f"Сколько самых дешёвых дней диапазона проверять (по умолчанию {MAX_DAYS})",
    }

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        dep_id = await city_id(query.origin, ctx)
        arr_id = await city_id(query.destination, ctx)
        days = await self._pick_days(query, ctx)

        sem = asyncio.Semaphore(3)

        async def one(day: date) -> list[FlightOffer]:
            async with sem:
                return parse_offers(await self._search_day(ctx, query, dep_id, arr_id, day))

        offers: list[FlightOffer] = []
        for part in await asyncio.gather(*(one(d) for d in days)):
            offers += part
        return offers

    async def _pick_days(self, query: SearchQuery, ctx: SourceContext) -> list[date]:
        """Один поиск Туту ≈ 10 с, поэтому на длинном диапазоне ищем только самые дешёвые дни по календарю."""
        all_days = query.dates()
        max_days = int(ctx.params.get("max_days") or MAX_DAYS)
        if len(all_days) <= max_days:
            return all_days
        cal = await self.calendar(query.origin, query.destination, query.date_from, query.date_to, ctx)
        if not cal:
            return all_days[:max_days]
        return sorted(sorted(cal, key=cal.get)[:max_days])

    async def _search_day(self, ctx: SourceContext, q: SearchQuery, dep_id: int, arr_id: int, day: date) -> list:
        body = {
            "passengers": {"full": q.adults, "child": q.children, "infant": q.infants},
            "serviceClass": "Y",
            "routes": [{"departureCityId": dep_id, "arrivalCityId": arr_id, "departureDate": day.isoformat()}],
            "searchId": str(uuid.uuid4()),
            "sessionId": str(uuid.uuid4()),
            "pageId": str(uuid.uuid4()),
            "userData": {"referenceToken": None, "screenSize": "1920x1080"},
            "source": "offers",
            "isNewSearch": True,
            "offset": 0,
            "limit": int(ctx.params.get("limit") or 100),
        }
        resp = await ctx.http.post(OFFERS_URL, json=body, headers=HEADERS, timeout=ctx.timeout_s)
        if resp.status_code >= 400:
            raise SourceError(f"Туту: HTTP {resp.status_code}")
        try:
            return json.loads(resp.text)
        except ValueError as e:
            raise SourceError("Туту: не удалось разобрать ответ") from e

    async def calendar(
        self, origin: str, destination: str, date_from: date, date_to: date, ctx: SourceContext
    ) -> dict[date, int]:
        params = {
            "product": "avia",
            "departure_geo_id": await city_id(origin, ctx),
            "arrival_geo_id": await city_id(destination, ctx),
            "geo_mode": "avia",
            "do_best_price": "true",
            "serviceClass": "Y",
            "adult": 1,
            "child": 0,
            "infant": 0,
        }
        resp = await ctx.http.get(CALENDAR_URL, params=params, headers=HEADERS, timeout=ctx.timeout_s)
        resp.raise_for_status()
        return parse_calendar(resp.json(), date_from, date_to)


async def city_id(iata: str, ctx: SourceContext) -> int:
    if iata in _CITY_IDS:
        return _CITY_IDS[iata]
    resp = await ctx.http.get(SUGGEST_URL, params={"name": iata}, headers=HEADERS, timeout=ctx.timeout_s)
    resp.raise_for_status()
    for s in resp.json().get("suggestions", []):
        city = s.get("city") or {}
        airport = s.get("airport") or {}
        if iata in (city.get("code"), airport.get("code")) and city.get("id"):
            _CITY_IDS[iata] = int(city["id"])
            return _CITY_IDS[iata]
    raise SourceError(f"Туту: не знает город {iata}")


def parse_calendar(data: dict[str, Any], date_from: date, date_to: date) -> dict[date, int]:
    result = {}
    for key, item in data.items():
        try:
            d = datetime.strptime(key, "%d.%m.%Y").date()
        except ValueError:
            continue
        price = (item or {}).get("price")
        if price and date_from <= d <= date_to:
            result[d] = int(price)
    return result


def _amount(money: dict) -> float:
    return money["amount"] / (money.get("fraction") or 100)


def parse_offers(chunks: list) -> list[FlightOffer]:
    if not chunks:
        return []
    last = chunks[-1]
    common = last["dictionary"]["common"]
    avia = last["dictionary"]["avia"]
    points = avia.get("points", {})

    def airport(point_id: int) -> str:
        return (points.get(str(point_id)) or {}).get("airportCode") or str(point_id)

    offers = []
    for o in (last.get("offers") or {}).get("actual", {}).values():
        variants = [v for v in o.get("offerVariants") or [] if v.get("price")]
        if not variants or not o.get("routeIds"):
            continue
        cheapest = min(variants, key=lambda v: v["price"]["value"]["amount"])
        route = common["routes"].get(o["routeIds"][0])
        if not route:
            continue
        raw_segments = [common["segments"][sid] for sid in route["segmentIds"]]
        segments = [
            Segment(
                origin=airport(s["departureGeoPointId"]),
                destination=airport(s["arrivalGeoPointId"]),
                departure_at=datetime.fromisoformat(s["departureDateTime"]),
                arrival_at=datetime.fromisoformat(s["arrivalDateTime"]),
                # Номер рейса бывает и «PC-388», и «UJ–707» (длинное тире)
                airline=re.split(r"[-–—\s]", s["voyageNumber"])[0],
                flight_number=re.sub(r"[-–—\s]", "", s["voyageNumber"]),
            )
            for s in raw_segments
        ]
        transfers = [common["transfers"].get(t, {}) for t in route.get("transferIds", [])]
        # Раздельные билеты или пересадка с повторной регистрацией и получением багажа
        self_transfer = bool(o.get("isMultiPnr")) or any(
            ((t.get("rules") or {}).get("avia") or {}).get("needCheckIn") for t in transfers
        )
        total_min = int((segments[-1].arrival_at - segments[0].departure_at).total_seconds() // 60)
        offers.append(
            FlightOffer(
                source="tutu",
                price_rub=round(_amount(cheapest["price"]["value"])),
                price_original=_amount(cheapest["price"]["value"]),
                origin_airport=segments[0].origin,
                destination_airport=segments[-1].destination,
                departure_at=segments[0].departure_at,
                arrival_at=segments[-1].arrival_at,
                duration_min=total_min,
                transfers=len(segments) - 1,
                airlines=list(dict.fromkeys(s.airline for s in segments if s.airline)),
                flight_numbers=[s.flight_number for s in segments if s.flight_number],
                segments=segments,
                route_airports=[segments[0].origin] + [s.destination for s in segments],
                baggage_included=_has_baggage(cheapest, common, avia),
                self_transfer=self_transfer,
                link=o.get("pinLink") or "https://avia.tutu.ru/",
            )
        )
    return offers


def _has_baggage(variant: dict, common: dict, avia: dict) -> bool | None:
    fare_apps = common.get("fareApplications", {})
    conditions = avia.get("conditions", {})
    seen = False
    for hashes in (variant.get("fareApplications") or {}).values():
        for h in hashes:
            cond = conditions.get((fare_apps.get(h) or {}).get("segmentConditions"), {})
            kg = (cond.get("baggageKg") or {}).get("value") or 0
            pc = (cond.get("baggagePc") or {}).get("value") or 0
            if not (cond.get("baggageKg") or cond.get("baggagePc")):
                continue
            seen = True
            if not (kg or pc):
                return False
    return True if seen else None
