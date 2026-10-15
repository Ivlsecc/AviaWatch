import json
from datetime import date

import httpx
import pytest
import respx

from search.filters import FilterSettings, apply_filters
from sources import tutu
from sources.base import SearchQuery, SourceContext, SourceError
from tests.conftest import FIXTURES

OFFERS = json.loads((FIXTURES / "tutu_offers.json").read_text(encoding="utf-8"))
CALENDAR = json.loads((FIXTURES / "tutu_calendar.json").read_text(encoding="utf-8"))
SUGGEST_HRG = json.loads((FIXTURES / "tutu_suggest_hrg.json").read_text(encoding="utf-8"))
SUGGEST_MOW = {"suggestions": [{"geo_type": "LOCALITY", "city": {"id": "491", "code": "MOW"}, "airport": None}]}


@pytest.fixture(autouse=True)
def clear_city_cache():
    tutu._CITY_IDS.clear()


def _mock_suggest():
    def handler(request: httpx.Request):
        name = request.url.params["name"]
        return httpx.Response(200, json={"HRG": SUGGEST_HRG, "MOW": SUGGEST_MOW}.get(name, {"suggestions": []}))

    respx.get(tutu.SUGGEST_URL).mock(side_effect=handler)


def test_parse_offers_from_real_response():
    offers = sorted(tutu.parse_offers(OFFERS), key=lambda o: o.price_rub)
    assert len(offers) == 10
    cheapest = offers[0]
    assert cheapest.price_rub == 21617
    assert cheapest.route_airports == ["HRG", "AYT", "VKO"]
    assert cheapest.flight_numbers == ["PC5091", "PC1580"] and cheapest.airlines == ["PC"]
    assert cheapest.transfers == 1 and len(cheapest.segments) == 2
    assert cheapest.departure_at.isoformat() == "2026-11-20T00:20:00+02:00"
    assert cheapest.link.startswith("https://avia.tutu.ru/offers/")
    assert not cheapest.self_transfer

    direct = [o for o in offers if o.transfers == 0]
    assert [o.flight_numbers for o in direct] == [["NE490"], ["SU425"], ["SU421"]]

    # Раздельные билеты через Каир (перерегистрация + получение багажа)
    split = [o for o in offers if o.self_transfer]
    assert len(split) == 3 and all(o.route_airports == ["HRG", "CAI", "SVO"] for o in split)


def test_default_filters_drop_split_tickets():
    offers = tutu.parse_offers(OFFERS)
    kept = apply_filters(offers, FilterSettings(max_duration_factor=None, min_layover_min=0, max_layover_min=24 * 60))
    assert not any(o.self_transfer for o in kept)
    assert len(kept) == 7


def test_parse_calendar_window():
    cal = tutu.parse_calendar(CALENDAR, date(2026, 11, 1), date(2026, 11, 30))
    assert cal and all(date(2026, 11, 1) <= d <= date(2026, 11, 30) for d in cal)
    assert cal[date(2026, 11, 1)] == 25376


@respx.mock
async def test_search_builds_request_and_uses_city_ids():
    _mock_suggest()
    route = respx.post(tutu.OFFERS_URL).mock(return_value=httpx.Response(200, text=json.dumps(OFFERS)))
    q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 20), adults=2)
    async with httpx.AsyncClient() as client:
        offers = await tutu.TutuSource().search(q, SourceContext(http=client))
    assert len(offers) == 10
    body = json.loads(route.calls.last.request.content)
    assert body["routes"] == [{"departureCityId": 460, "arrivalCityId": 491, "departureDate": "2026-11-20"}]
    assert body["passengers"] == {"full": 2, "child": 0, "infant": 0}
    assert body["limit"] == 100


@respx.mock
async def test_long_range_searches_only_cheapest_days():
    _mock_suggest()
    respx.get(tutu.CALENDAR_URL).mock(return_value=httpx.Response(200, json=CALENDAR))
    route = respx.post(tutu.OFFERS_URL).mock(return_value=httpx.Response(200, text=json.dumps(OFFERS)))
    q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 1), date_to=date(2026, 11, 30))
    async with httpx.AsyncClient() as client:
        await tutu.TutuSource().search(q, SourceContext(http=client, params={"max_days": 3}))
    days = sorted(json.loads(c.request.content)["routes"][0]["departureDate"] for c in route.calls)
    cal = tutu.parse_calendar(CALENDAR, q.date_from, q.date_to)
    expected = sorted(d.isoformat() for d in sorted(cal, key=cal.get)[:3])
    assert days == expected


@respx.mock
async def test_unknown_city_raises():
    _mock_suggest()
    q = SearchQuery(origin="XXX", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 20))
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceError, match="XXX"):
            await tutu.TutuSource().search(q, SourceContext(http=client))


@respx.mock
async def test_http_error_raises():
    _mock_suggest()
    respx.post(tutu.OFFERS_URL).mock(return_value=httpx.Response(503))
    q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 20))
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceError, match="503"):
            await tutu.TutuSource().search(q, SourceContext(http=client))
