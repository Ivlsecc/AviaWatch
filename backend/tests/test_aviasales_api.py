import json
from datetime import date

import httpx
import pytest
import respx

from sources.aviasales_api import API_URL, AviasalesApiSource
from sources.base import SearchQuery, SourceContext, SourceError
from tests.conftest import FIXTURES

FIXTURE = json.loads((FIXTURES / "aviasales_prices_for_dates.json").read_text(encoding="utf-8"))


def _ctx(client, **params):
    return SourceContext(http=client, params={"token": "t", **params})


@respx.mock
async def test_search_parses_and_filters_by_dates():
    route = respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 25), adults=2)
    async with httpx.AsyncClient() as client:
        offers = await AviasalesApiSource().search(q, _ctx(client, marker="m1"))

    # Рейс 2 декабря вне диапазона
    assert len(offers) == 4
    su = next(o for o in offers if o.flight_numbers == ["SU1840"])
    assert su.price_rub == 21500 * 2  # цена за двоих
    assert su.destination_airport == "SVO"
    assert su.duration_min == 300
    assert su.arrival_at is not None and (su.arrival_at - su.departure_at).seconds == 300 * 60
    assert su.link.startswith("https://www.aviasales.ru/search/HRG2011MOW1")
    assert su.link.endswith("&marker=m1")

    req = route.calls.last.request
    assert req.headers["X-Access-Token"] == "t"
    assert req.url.params["departure_at"] == "2026-11"
    assert req.url.params["one_way"] == "true"


@respx.mock
async def test_single_date_queries_exact_day():
    route = respx.get(API_URL).mock(return_value=httpx.Response(200, json={"success": True, "data": []}))
    q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 20))
    async with httpx.AsyncClient() as client:
        assert await AviasalesApiSource().search(q, _ctx(client)) == []
    assert route.calls.last.request.url.params["departure_at"] == "2026-11-20"


@respx.mock
async def test_range_across_months_queries_each_month():
    route = respx.get(API_URL).mock(return_value=httpx.Response(200, json={"success": True, "data": []}))
    q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 28), date_to=date(2026, 12, 3))
    async with httpx.AsyncClient() as client:
        await AviasalesApiSource().search(q, _ctx(client))
    assert [c.request.url.params["departure_at"] for c in route.calls] == ["2026-11", "2026-12"]


@respx.mock
async def test_api_error_raises():
    respx.get(API_URL).mock(return_value=httpx.Response(200, json={"success": False, "error": "bad origin"}))
    q = SearchQuery(origin="XXX", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 20))
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceError, match="bad origin"):
            await AviasalesApiSource().search(q, _ctx(client))


async def test_missing_token_raises():
    q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 20))
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceError, match="токен"):
            await AviasalesApiSource().search(q, SourceContext(http=client, params={}))


@respx.mock
async def test_calendar_min_per_day():
    respx.get(API_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    async with httpx.AsyncClient() as client:
        cal = await AviasalesApiSource().calendar("HRG", "MOW", date(2026, 11, 1), date(2026, 11, 30), _ctx(client))
    assert cal == {date(2026, 11, 20): 15200, date(2026, 11, 21): 18900}
