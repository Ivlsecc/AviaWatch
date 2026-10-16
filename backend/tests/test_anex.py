import json
from datetime import date

import httpx
import pytest
import respx

from common.airports import airports
from sources import anex
from sources.base import SearchQuery, SourceContext
from tests.conftest import FIXTURES

PRICES = json.loads((FIXTURES / "anex_prices.json").read_text(encoding="utf-8"))
LINK = "https://anextour.ru/search/avia?x"

SOURCES = {"Tickets_SOURCES": [
    {"id": "225.18", "townIATA": "", "portAlias": "HRG", "stateISO": "EG"},
    {"id": "139.7", "townIATA": "", "portAlias": "SSH", "stateISO": "EG"},
    {"id": "2.6", "townIATA": "MOW", "portAlias": "DME", "stateISO": "RU"},
]}
TARGETS = {"Tickets_TARGETS": [
    {"id": "2", "townIATA": "MOW", "portAlias": ""},
    {"id": "2.130", "townIATA": "MOW", "portAlias": "VKO-A"},
    {"id": "69.19", "townIATA": "SVX", "portAlias": "SVX"},
]}


@pytest.fixture(autouse=True)
def offline_airports():
    airports.set_data({})
    anex._ports_cache = None


def test_parse_skips_sold_out_and_reads_local_time():
    offers = anex.parse_prices(PRICES, LINK)
    # 6 вариантов в ответе, у одного «нет мест»
    assert len(offers) == 5
    first = offers[0]
    assert first.flight_numbers == ["NE644"] and first.price_rub == 44600
    assert first.origin_airport == "SSH" and first.destination_airport == "VKO"
    # Октябрь: Египет на летнем времени, UTC+3
    assert first.departure_at.isoformat() == "2026-10-17T07:35:00+03:00"
    assert first.duration_min == 340 and first.transfers == 0
    assert first.baggage_included and "багаж 15kg" in first.note and "мест мало" in first.note


def test_night_flight_arrives_next_day():
    night = [o for o in anex.parse_prices(PRICES, LINK) if o.flight_numbers == ["NE642"]][0]
    assert night.departure_at.day == 19 and night.arrival_at.day == 20


def test_city_target_preferred_and_days_from_checkins():
    assert [p["id"] for p in anex.pick_points(TARGETS["Tickets_TARGETS"], "MOW")] == ["2"]
    assert [p["id"] for p in anex.pick_points(TARGETS["Tickets_TARGETS"], "VKO")] == ["2.130"]
    ci = {"startDate": "20261016", "validDates": "0330"}
    days = [date(2026, 10, d) for d in range(15, 21)]
    assert anex.available_days(ci, days) == [date(2026, 10, 17), date(2026, 10, 18)]


@respx.mock
async def test_search_asks_prices_only_for_flying_days():
    respx.get(anex.API_URL + "Sources").mock(return_value=httpx.Response(200, json=SOURCES))
    respx.get(anex.API_URL + "Targets").mock(return_value=httpx.Response(200, json=TARGETS))
    respx.get(anex.API_URL + "Checkins").mock(return_value=httpx.Response(
        200, json={"Tickets_CHECKINS": {"startDate": "20261016", "validDates": "0100"}}))
    prices = respx.get(anex.API_URL + "Prices").mock(return_value=httpx.Response(200, json=PRICES))

    q = SearchQuery(origin="SSH", destination="MOW", date_from=date(2026, 10, 16), date_to=date(2026, 10, 20), adults=2)
    async with httpx.AsyncClient() as client:
        offers = await anex.AnexSource().search(q, SourceContext(http=client))
    assert offers and prices.call_count == 1
    p = prices.calls.last.request.url.params
    assert p["source"] == "139.7" and p["target"] == "2" and p["checkin"] == "20261017" and p["adult"] == "2"
    assert "airFrom=139.7" in offers[0].link and "CHECKIN_BEG=20261017" in offers[0].link
