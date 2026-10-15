from datetime import date, datetime

import httpx
import pytest
import respx

from common.airports import airports
from sources import telegram
from sources import ticket_egypt as te
from sources.base import SearchQuery, SourceContext
from tests.conftest import FIXTURES

PAGE = (FIXTURES / "ticket_egypt_page.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def offline():
    airports.set_data({}, names={"Эль-Дабаа": "DBB"})
    telegram._CACHE.clear()


def post(text: str, pid: int = 1, when: str = "2026-10-15T08:00:00+00:00") -> telegram.Post:
    return telegram.Post(pid, datetime.fromisoformat(when), text)


def test_parse_formats():
    deals = te.parse_post(post(
        "🔥 Чартер #Самара → Шарм-эш-Шейх:\n\n"
        "🔥11 ноября - 6794 руб. с багажом 10кг - https://avs.io/Zz1Y\n\n"
        "🔥 Прямой #Краснодар → Хургада:\n"
        "🔥18 октября - 9 454 руб. с багажом 23кг - https://avs.io/6squY\n"
        "🔥 Санкт-Петербург — Луксор с одной пересадкой:\n"
        "🔥6 ноября - 13368 руб. с ручной кладью - https://avs.io/12N2H\n"
        "🆕  Новое направление! Чартер #Москва → Эль-Дабаа:\n"
        "🔥18 ноября - 15123 руб. с багажом 10кг - https://avs.io/12Ifk\n"
        "🔥 Чартер #Сочи → Шарм-эш-Шейх → Сочи:\n"
        "🔥24 ноября - 4 декабря - 18854 руб. с багажом 10кг - https://avs.io/13p6F\n"
        "🏨 Забронируй отель с оплатой картой российского банка.\n"
    ))
    got = [(d.origin, d.destination, d.day, d.price, d.baggage_kg, d.transfers) for d in deals]
    assert got == [
        ("KUF", "SSH", date(2026, 11, 11), 6794, 10, 0),
        ("KRR", "HRG", date(2026, 10, 18), 9454, 23, 0),
        ("LED", "LXR", date(2026, 11, 6), 13368, 0, 1),
        ("MOW", "DBB", date(2026, 11, 18), 15123, 10, 0),
    ]  # туда-обратно пропущено
    assert deals[0].link == "https://avs.io/Zz1Y"


def test_hashtag_links_keep_city_name():
    html = (
        '<div class="tgme_widget_message_wrap"><div data-post="ticket_egypt/1">'
        '<div class="tgme_widget_message_text js-message_text">🔥 Чартер <a href="?q=%23%D0%A3%D1%84%D0%B0">#Уфа</a>'
        ' → Шарм-эш-Шейх:<br/>🔥10 октября - 9728 руб. с багажом 23кг - <a href="https://avs.io/6qp4J">ссылка</a></div>'
        '<time datetime="2026-10-01T10:00:00+00:00"></time></div></div>'
    )
    [p] = telegram.parse_channel_html(html, "ticket_egypt")
    [d] = te.parse_post(p)
    assert (d.origin, d.destination, d.link) == ("UFA", "SSH", "https://avs.io/6qp4J")


def test_real_page_parses():
    posts = telegram.parse_channel_html(PAGE, "ticket_egypt")
    assert len(posts) == 20
    assert te.latest_deals(posts)


@respx.mock
async def test_search_filters_route_and_marks_offer():
    respx.get(telegram.PAGE_URL.format(channel="ticket_egypt")).mock(return_value=httpx.Response(200, text=(
        '<div class="tgme_widget_message_wrap"><div data-post="ticket_egypt/7">'
        '<div class="tgme_widget_message_text">🔥 Чартер #Москва → Шарм-эш-Шейх:<br/>'
        '🔥18 октября - 4766 руб. с багажом 23кг - https://avs.io/13rRC</div>'
        '<time datetime="2026-10-15T09:00:00+00:00"></time></div></div>'
    )))
    q = SearchQuery(origin="MOW", destination="SSH", date_from=date(2026, 10, 17), date_to=date(2026, 10, 20), adults=2)
    async with httpx.AsyncClient() as client:
        [o] = await te.TicketEgyptSource().search(q, SourceContext(http=client, params={"max_age_days": 36500, "pages": 1}))
    assert o.price_rub == 9532 and not o.time_known and o.baggage_included
    assert o.link == "https://avs.io/13rRC" and "горящее" in o.note
