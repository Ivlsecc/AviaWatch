import json
from datetime import date

import httpx
import pytest
import respx

from common.airports import airports
from sources import onetwotrip as ott
from sources.base import SearchQuery, SourceContext
from tests.conftest import FIXTURES

DATA = json.loads((FIXTURES / "onetwotrip_hrg_mow.json").read_text(encoding="utf-8"))
Q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 10, 22), date_to=date(2026, 10, 22))


@pytest.fixture(autouse=True)
def offline_airports():
    airports.set_data({})  # только встроенный минимум — тесты не ходят в сеть


def test_parse_real_response_drops_junk_fares():
    offers = sorted(ott.parse_response(DATA, Q, "2210HRGMOW"), key=lambda o: o.price_rub)
    assert len(DATA["frs"]) == 18 and len(offers) == 6  # тарифы UTair за ~1 млн ₽ отброшены
    assert all(o.price_rub < 300_000 for o in offers)
    first = offers[0]
    assert first.price_rub == 44329
    assert first.flight_numbers == ["MS241", "SU401"] and first.route_airports == ["HRG", "CAI", "SVO"]
    # Местное время Хургады в октябре — летнее, UTC+3
    assert first.departure_at.isoformat() == "2026-10-22T10:25:00+03:00"
    assert first.self_transfer
    assert first.link == "https://www.onetwotrip.com/ru/f/search/2210HRGMOW?s=true&sc=E&p=1_0_0"


def test_arrival_next_day():
    data = {
        "frs": [{"dirs": [{"bg": "1PC", "trps": [{"id": 0}]}], "prcInf": {"amt": 20000, "cur": "RUB"}}],
        "trps": [{"stDt": "20261120", "stTm": "2245", "endTm": "0400", "dayChg": 1, "from": "HRG", "to": "SVO",
                  "airCmp": "SU", "fltNm": "0421"}],
    }
    [o] = ott.parse_response(data, Q, "2011HRGMOW")
    assert o.flight_numbers == ["SU421"] and o.baggage_included and o.transfers == 0
    assert o.arrival_at.isoformat() == "2026-11-21T04:00:00+03:00"
    # 22:45 Хургада (UTC+2 в ноябре) → 04:00 Москва (UTC+3): 4 ч 15 мин с учётом поясов
    assert o.duration_min == 4 * 60 + 15


@respx.mock
async def test_search_uses_route_param():
    route = respx.get(ott.SEARCH_URL).mock(return_value=httpx.Response(200, json=DATA))
    async with httpx.AsyncClient() as client:
        offers = await ott.OneTwoTripSource().search(Q, SourceContext(http=client))
    assert offers
    assert route.calls.last.request.url.params["route"] == "2210HRGMOW"
    assert route.calls.last.request.url.params["ad"] == "1"
