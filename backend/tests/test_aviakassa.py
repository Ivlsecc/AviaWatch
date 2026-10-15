import json
from datetime import date

import httpx
import respx

from search.dedup import merge_duplicates
from sources import aviakassa as ak
from sources.base import SearchQuery, SourceContext
from sources.kupibilet import parse_response as kupibilet_parse
from tests.conftest import FIXTURES

DATA = json.loads((FIXTURES / "aviakassa_hrg_mow.json").read_text(encoding="utf-8"))
Q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 20))
DAY = date(2026, 11, 20)


def test_parse_real_response():
    offers = sorted(ak.parse_response(DATA, Q, DAY), key=lambda o: o.price_rub)
    first = offers[0]
    assert first.price_rub == 26031
    assert first.flight_numbers == ["PC5091", "PC1580"] and first.route_airports == ["HRG", "AYT", "VKO"]
    # Местное время берём строкой: 00:20 в Хургаде (UTC+2 зимой), а не сдвинутый ts
    assert first.departure_at.isoformat() == "2026-11-20T00:20:00+02:00"
    assert first.duration_min == 775
    assert first.baggage_included and not first.self_transfer
    assert any(o.self_transfer for o in offers)  # is_vtrip
    assert first.link.startswith("https://www.aviakassa.com/avia/search?")
    assert "segments%5B0%5D%5B0%5D%5Bdate%5D=20.11.2026" in first.link


def test_same_flight_merges_with_kupibilet():
    kupi = kupibilet_parse(json.loads((FIXTURES / "kupibilet_hrg_mow.json").read_text(encoding="utf-8")), Q, "2026-11-20")
    merged = merge_duplicates(ak.parse_response(DATA, Q, DAY) + kupi)
    pc = [o for o in merged if o.flight_numbers[:1] == ["PC5091"] and o.transfers == 1 and o.destination_airport == "VKO"]
    assert len(pc) == 1
    assert pc[0].price_rub == 20849 and {a[0] for a in pc[0].alt_links} == {"aviakassa"}


@respx.mock
async def test_search_params():
    route = respx.get(ak.API_URL).mock(return_value=httpx.Response(200, json=DATA))
    async with httpx.AsyncClient() as client:
        offers = await ak.AviakassaSource().search(Q, SourceContext(http=client))
    assert offers
    p = route.calls.last.request.url.params
    assert p["segments[0][0][from]"] == "HRG" and p["segments[0][0][date]"] == "20.11.2026"
    assert p["partner"] == "AKV4" and p["page[limit]"] == "100"
