from datetime import date, datetime, timezone

import httpx
import pytest
import respx

from sources import egyptticket as et
from sources.base import SearchQuery, SourceContext, SourceError
from tests.conftest import FIXTURES

PAGE = (FIXTURES / "egyptticket_page.html").read_text(encoding="utf-8")
URL = et.PAGE_URL.format(channel=et.CHANNEL)
EVERYTHING = {"max_age_days": 36500, "pages": 1}  # фикстура «стареет», возраст постов в тестах не важен


@pytest.fixture(autouse=True)
def clear_cache():
    et._CACHE.clear()


def post(text: str, pid: int = 1, when: str = "2026-10-15T08:00:00+00:00") -> et.Post:
    return et.Post(pid, datetime.fromisoformat(when), text)


def test_parse_real_channel_page():
    posts = et.parse_channel_html(PAGE)
    assert len(posts) == 20 and posts[0].id == 13944
    fares = {(f.origin, f.destination, f.day, f.business): f for f in et.latest_fares(posts)}
    vko = fares[("HRG", "VKO", date(2026, 10, 19), False)]
    assert (vko.price, vko.baggage_kg, vko.hand_kg, vko.destination_city) == (12000, 20, 5, "MOW")
    biz = fares[("HRG", "DME", date(2026, 10, 22), True)]
    assert biz.price == 28100 and biz.seats_left == 1
    assert fares[("KZN", "HRG", date(2026, 10, 20), False)].sold_out
    # Каждый пост с ценами распознан
    assert all(et.parse_post(p) for p in posts if "руб" in p.text and "=" in p.text)


def test_header_variants_and_fare_details():
    fares = et.parse_post(post(
        "ШАРМ-ЭЛЬ-ШЕЙХ - ВНУКОВО/рег.блок\n"
        "05.11 = 15 500 руб 20+5/ 2 места\n"
        "ХУРГАДА - МИН ВОДЫ /рег.блок\n"
        "06.11 = 9900 руб\n"
        "Для бронирования пишите по номеру: +201122002341\n"
        "НЕИЗВЕСТНЫЙГОРОД - ХУРГАДА\n"
        "07.11 = 1000 руб\n"
    ))
    assert [(f.origin, f.destination, f.day, f.price, f.seats_left) for f in fares] == [
        ("SSH", "VKO", date(2026, 11, 5), 15500, 2),
        ("HRG", "MRV", date(2026, 11, 6), 9900, None),
    ]


def test_year_rollover():
    [f] = et.parse_post(post("ХУРГАДА - ВНУКОВО\n05.01 = 20000 руб", when="2026-12-20T10:00:00+00:00"))
    assert f.day == date(2027, 1, 5)


def test_latest_post_wins():
    old = post("ХУРГАДА - ВНУКОВО\n19.10 = 15000 руб 20+5", pid=1)
    new = post("ХУРГАДА - ВНУКОВО\n19.10 = 12000 руб 20+5 ПРОДАНО", pid=2)
    [f] = et.latest_fares([new, old])
    assert f.price == 12000 and f.sold_out


@respx.mock
async def test_search_matches_city_code_and_dates():
    respx.get(URL).mock(return_value=httpx.Response(200, text=PAGE))
    q = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 10, 19), date_to=date(2026, 10, 22), adults=2)
    async with httpx.AsyncClient() as client:
        offers = await et.EgyptTicketSource().search(q, SourceContext(http=client, params=EVERYTHING))
    got = sorted((o.destination_airport, o.departure_at.date(), o.price_rub) for o in offers)
    assert got == [
        ("DME", date(2026, 10, 20), 30800),
        ("DME", date(2026, 10, 22), 38000),
        ("DME", date(2026, 10, 22), 56200),
        ("SVO", date(2026, 10, 21), 29000),
        ("VKO", date(2026, 10, 19), 24000),
    ]
    vko = next(o for o in offers if o.destination_airport == "VKO")
    assert not vko.time_known and vko.transfers == 0 and vko.baggage_included
    assert vko.link == "https://t.me/egyptticket/13964"
    assert "багаж 20 кг" in vko.note and "бронь через продавца" in vko.note


@respx.mock
async def test_old_posts_ignored_and_cache_used():
    route = respx.get(URL).mock(return_value=httpx.Response(200, text=PAGE))
    q = SearchQuery(origin="HRG", destination="VKO", date_from=date(2026, 10, 19), date_to=date(2026, 10, 19))
    async with httpx.AsyncClient() as client:
        ctx = SourceContext(http=client, params={"max_age_days": 0, "pages": 1})
        assert await et.EgyptTicketSource().search(q, ctx) == []
        await et.EgyptTicketSource().search(q, ctx)
    assert route.call_count == 1  # вторая выборка — из кэша


@respx.mock
async def test_unavailable_channel_raises():
    respx.get(URL).mock(return_value=httpx.Response(302, headers={"Location": "https://t.me/egyptticket"}))
    q = SearchQuery(origin="HRG", destination="VKO", date_from=date(2026, 10, 19), date_to=date(2026, 10, 19))
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceError, match="недоступен"):
            await et.EgyptTicketSource().search(q, SourceContext(http=client, params=EVERYTHING))


def test_offer_without_time_renders_date_only():
    from bot.fmt import offer_line

    o = et.to_offer(
        et.latest_fares([post("ХУРГАДА - ВНУКОВО\n19.10 = 12000 руб 20+5")])[0],
        SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 10, 19), date_to=date(2026, 10, 19)),
        "egyptticket",
    )
    line = offer_line(1, o)
    assert "19 окт, пн" in line and "время уточнять" in line and "12:00" not in line and "<i>чартер" in line
    assert o.departure_at.tzinfo == timezone.utc
