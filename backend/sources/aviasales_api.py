"""Aviasales Data API (Travelpayouts).

Официальный бесплатный API. Цены берутся из кэша поисков пользователей Aviasales
за последние дни, поэтому могут немного отставать от живой выдачи, зато API
стабилен и даёт календарь цен — на нём держится расчёт средней цены.

Документация: https://support.travelpayouts.com/hc/en-us/articles/203956163
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sources.base import FlightOffer, SearchQuery, Source, SourceContext, SourceError
from sources.registry import register

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
SITE_URL = "https://www.aviasales.ru"
PAGE_LIMIT = 1000


@register
class AviasalesApiSource(Source):
    name = "aviasales_api"
    title = "Aviasales (API)"
    method = "api"
    supports_calendar = True
    param_schema = {
        "token": "Токен Travelpayouts (если пусто — берётся из .env)",
        "marker": "Партнёрский маркер для ссылок (необязательно)",
        "market": "Рынок, например ru",
    }

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        items: list[dict[str, Any]] = []
        for period in _periods(query.date_from, query.date_to):
            items += await self._fetch(ctx, query.origin, query.destination, period, query.direct_only, sorting="price")

        offers = []
        for it in items:
            offer = self._to_offer(it, query, ctx)
            if offer and query.date_from <= offer.departure_date <= query.date_to:
                offers.append(offer)
        return offers

    async def calendar(
        self, origin: str, destination: str, date_from: date, date_to: date, ctx: SourceContext
    ) -> dict[date, int]:
        result: dict[date, int] = {}
        for period in _periods(date_from, date_to, prefer_month=True):
            for it in await self._fetch(ctx, origin, destination, period, direct=False, sorting="price"):
                dep = _parse_dt(it.get("departure_at"))
                price = it.get("price")
                if dep is None or price is None:
                    continue
                d = dep.date()
                if date_from <= d <= date_to and (d not in result or price < result[d]):
                    result[d] = int(price)
        return result

    async def _fetch(
        self, ctx: SourceContext, origin: str, destination: str, period: str, direct: bool, sorting: str
    ) -> list[dict[str, Any]]:
        token = ctx.params.get("token")
        if not token:
            raise SourceError("Не задан токен Travelpayouts (TRAVELPAYOUTS_TOKEN)")
        params = {
            "origin": origin,
            "destination": destination,
            "departure_at": period,
            "one_way": "true",
            "direct": str(direct).lower(),
            "currency": "rub",
            "sorting": sorting,
            "limit": PAGE_LIMIT,
            "unique": "false",
        }
        if market := ctx.params.get("market"):
            params["market"] = market
        resp = await ctx.http.get(
            API_URL,
            params=params,
            headers={"X-Access-Token": token, "Accept-Encoding": "gzip"},
            timeout=ctx.timeout_s,
        )
        if resp.status_code == 401:
            raise SourceError("Travelpayouts: неверный токен (401)")
        if resp.status_code == 429:
            raise SourceError("Travelpayouts: превышен лимит запросов (429)")
        resp.raise_for_status()
        body = resp.json()
        if not body.get("success", False):
            raise SourceError(f"Travelpayouts: {body.get('error') or 'неизвестная ошибка'}")
        return body.get("data") or []

    def _to_offer(self, it: dict[str, Any], query: SearchQuery, ctx: SourceContext) -> FlightOffer | None:
        dep = _parse_dt(it.get("departure_at"))
        price = it.get("price")
        if dep is None or price is None:
            return None

        duration = it.get("duration_to") or it.get("duration")
        arrival = dep + timedelta(minutes=duration) if duration else None
        airline = it.get("airline")
        flight = it.get("flight_number")
        flight_numbers = [f"{airline}{flight}"] if airline and flight else []

        link = it.get("link") or ""
        if link and not link.startswith("http"):
            link = SITE_URL + link
        if not link:
            link = f"{SITE_URL}/search/{query.origin}{dep:%d%m}{query.destination}1"
        if marker := ctx.params.get("marker"):
            link += ("&" if "?" in link else "?") + f"marker={marker}"

        # Цена в API — за одного взрослого. Для группы это оценка.
        total = int(price) * max(query.passengers, 1)
        return FlightOffer(
            source=self.name,
            price_rub=total,
            price_original=float(price),
            currency="RUB",
            origin_airport=it.get("origin_airport") or it.get("origin") or query.origin,
            destination_airport=it.get("destination_airport") or it.get("destination") or query.destination,
            departure_at=dep,
            arrival_at=arrival,
            duration_min=duration,
            transfers=int(it.get("transfers") or 0),
            airlines=[airline] if airline else [],
            flight_numbers=flight_numbers,
            link=link,
        )


def _periods(date_from: date, date_to: date, prefer_month: bool = False) -> list[str]:
    """Значения departure_at: конкретный день для одной даты, иначе месяцы диапазона."""
    if date_from == date_to and not prefer_month:
        return [date_from.isoformat()]
    months, cur = [], date_from.replace(day=1)
    while cur <= date_to:
        months.append(cur.strftime("%Y-%m"))
        cur = (cur + timedelta(days=32)).replace(day=1)
    return months


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
