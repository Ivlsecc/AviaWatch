import json
from datetime import date

import httpx
import respx

from search.filters import FilterSettings, apply_filters
from sources import kupibilet as kb
from sources.base import SearchQuery, SourceContext, focus_days
from tests.conftest import FIXTURES

DATA = json.loads((FIXTURES / "kupibilet_hrg_mow.json").read_text(encoding="utf-8"))
Q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 20))


def test_parse_real_response():
    offers = sorted(kb.parse_response(DATA, Q, "2026-11-20"), key=lambda o: o.price_rub)
    cheapest = offers[0]
    assert cheapest.price_rub == 20849
    assert cheapest.flight_numbers == ["PC5091", "PC1580"]
    assert cheapest.route_airports == ["HRG", "AYT", "VKO"]
    assert cheapest.transfers == 1 and not cheapest.self_transfer and cheapest.baggage_included is False
    assert cheapest.duration_min == 775  # 00:20 +02 → 14:15 +03
    assert cheapest.link.startswith("https://www.kupibilet.ru/search?route[0]=iatax:HRG_2026-11-20")

    # Самостоятельная пересадка через Стамбул (SAW→IST) распознана
    split = [o for o in offers if o.flight_numbers[1:2] == ["PC2023"]]
    assert split and all(o.self_transfer for o in split)
    # Чартер помечен, поезда отброшены
    assert any(o.note and "чартер" in o.note for o in offers)
    assert all(len(o.segments) == len(o.flight_numbers) for o in offers)


def test_default_filters_drop_virtual_connections():
    kept = apply_filters(kb.parse_response(DATA, Q, "2026-11-20"), FilterSettings())
    assert kept and not any(o.self_transfer for o in kept)


@respx.mock
async def test_search_request_body_and_focus_days():
    route = respx.post(kb.SEARCH_URL).mock(return_value=httpx.Response(200, json=DATA))
    q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 1), date_to=date(2026, 11, 30), adults=2,
                    direct_only=True)
    focus = [date(2026, 11, 20), date(2026, 11, 3), date(2026, 12, 5)]
    async with httpx.AsyncClient() as client:
        await kb.KupibiletSource().search(q, SourceContext(http=client, focus_days=focus))
    bodies = [json.loads(c.request.content) for c in route.calls]
    assert sorted(b["trips"][0]["date"] for b in bodies) == ["2026-11-03", "2026-11-20"]  # 05.12 вне диапазона
    assert bodies[0]["travelers"]["adult"] == 2
    assert bodies[0]["filters"] == {"transfer_count": [{"max": 0}]}


def test_focus_days_spread_without_calendar():
    q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 1), date_to=date(2026, 11, 30))
    days = focus_days(q, SourceContext(http=None))
    assert len(days) == 5 and days[0] == date(2026, 11, 1) and days[-1] >= date(2026, 11, 20)
    short = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 1), date_to=date(2026, 11, 3))
    assert focus_days(short, SourceContext(http=None)) == short.dates()
