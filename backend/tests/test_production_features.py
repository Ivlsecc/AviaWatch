"""Фильтры прилёта, сверка цен из кэша, новые рейсы в подписках, автопроверка источников, запасной маршрут бота."""

from datetime import date, datetime, timedelta, timezone

import pytest
from aiohttp import ClientConnectorError
from aiogram.exceptions import TelegramNetworkError

from bot.filters_logic import airport_choices, toggle
from bot.fmt import offer_line
from scheduler.checker import find_new_flights, flight_key, remember_flights
from scheduler.health import find_problems, report
from scheduler.rules import SubState, evaluate
from search.filters import FilterSettings, apply_filters
from search.orchestrator import SearchResult, SourceStatus
from search.verify import verify_cached_prices
from sources.base import FlightOffer, SearchQuery

UTC = timezone.utc
CAIRO = timezone(timedelta(hours=2))
DAY = date(2026, 11, 20)


def offer(price, source="kupibilet", dep_h=10, arr=None, dest="SVO", flights=("PC1",), transfers=0, **kw):
    dep = datetime(2026, 11, 20, dep_h, 0, tzinfo=CAIRO)
    return FlightOffer(
        source=source, price_rub=price, origin_airport="HRG", destination_airport=dest, departure_at=dep,
        arrival_at=arr, duration_min=300, transfers=transfers, flight_numbers=list(flights),
        link=f"https://example/{source}/{price}", **kw,
    )


# ---------- фильтры прилёта ----------

def test_arrival_window_uses_local_time_of_arrival_airport():
    # 21:30 UTC = 00:30 по Москве — ночной прилёт
    night = offer(1, arr=datetime(2026, 11, 20, 21, 30, tzinfo=UTC))
    evening = offer(2, arr=datetime(2026, 11, 20, 17, 0, tzinfo=UTC), flights=("PC2",))  # 20:00 МСК
    unknown = offer(3, flights=("PC3",))  # прилёт неизвестен — не отсекаем
    f = FilterSettings(arrival_window="no_night", max_duration_factor=None)
    assert [o.price_rub for o in apply_filters([night, evening, unknown], f)] == [2, 3]
    f_day = f.model_copy(update={"arrival_window": "day"})
    assert [o.price_rub for o in apply_filters([night, evening, unknown], f_day)] == [2, 3]


def test_arrival_airports_filter_and_toggles():
    offers = [offer(1, dest="DME"), offer(2, dest="VKO", flights=("PC2",)), offer(3, dest="SVO", flights=("PC3",))]
    f = toggle(toggle(FilterSettings(max_duration_factor=None), "apt_VKO"), "apt_SVO")
    assert f.arrival_airports == ["VKO", "SVO"]
    assert [o.price_rub for o in apply_filters(offers, f)] == [2, 3]
    assert toggle(f, "apt_VKO").arrival_airports == ["SVO"]
    assert toggle(FilterSettings(), "arrival").arrival_window == "no_night"
    assert airport_choices(["MOW"]) == ["SVO", "VKO", "DME", "ZIA"]
    assert airport_choices(["HRG"]) == []


# ---------- сверка цен из кэша ----------

class StubSvc:
    def __init__(self, live_offers=None):
        self.live_offers = live_offers or []
        self.searched = []

    async def _focus_days(self, q):
        return []

    async def search(self, q, filters=None, user_id=None, use_cache=True, only_sources=None, log_search=True, progress=None):
        self.searched.append((q, only_sources))
        return SearchResult(q, list(self.live_offers), len(self.live_offers))


LIVE_OK = [SourceStatus("kupibilet", True, 3), SourceStatus("aviasales_api", True, 1)]


async def test_cached_price_updated_from_live_alt():
    cached = offer(20000, source="aviasales_api", alt_links=[("kupibilet", 26000, "https://kb")])
    q = SearchQuery(origin="HRG", destination="SVO", date_from=DAY, date_to=DAY)
    res = await verify_cached_prices(StubSvc(), [q], [cached], FilterSettings(), LIVE_OK)
    o = res[0]
    assert (o.price_check, o.price_rub, o.cached_price_rub, o.source) == ("updated", 26000, 20000, "kupibilet")
    assert o.alt_links == []
    assert "в кэше Aviasales было 20" in offer_line(1, o)


async def test_cached_price_confirmed_within_tolerance():
    cached = offer(20000, source="aviasales_api", alt_links=[("tutu", 20300, "https://tutu")])
    q = SearchQuery(origin="HRG", destination="SVO", date_from=DAY, date_to=DAY)
    res = await verify_cached_prices(StubSvc(), [q], [cached], FilterSettings(), LIVE_OK)
    assert res[0].price_check == "confirmed" and res[0].price_rub == 20000


async def test_cached_price_unconfirmed_when_live_searched_that_day():
    cached = offer(15000, source="aviasales_api", flights=("UT758",))
    q = SearchQuery(origin="HRG", destination="SVO", date_from=DAY, date_to=DAY + timedelta(days=2))
    svc = StubSvc()
    res = await verify_cached_prices(svc, [q], [cached, offer(30000)], FilterSettings(), LIVE_OK)
    assert res[0].price_check == "unconfirmed"
    assert svc.searched == []  # короткий диапазон живые сайты уже искали целиком
    assert "не нашёлся" in offer_line(1, res[0])


async def test_long_range_triggers_one_day_live_search():
    cached = offer(15000, source="aviasales_api", flights=("UT758",))
    live = offer(18000, source="tutu", flights=("UT758",))
    q = SearchQuery(origin="HRG", destination="SVO", date_from=DAY - timedelta(days=5), date_to=DAY + timedelta(days=5))
    svc = StubSvc([live])
    res = await verify_cached_prices(svc, [q], [cached], FilterSettings(), LIVE_OK)
    assert len(svc.searched) == 1
    searched_q, only = svc.searched[0]
    assert searched_q.date_from == searched_q.date_to == DAY
    assert "aviasales_api" not in only and "kupibilet" in only
    assert (res[0].price_check, res[0].price_rub) == ("updated", 18000)


async def test_no_verification_when_live_sources_all_failed():
    cached = offer(15000, source="aviasales_api")
    q = SearchQuery(origin="HRG", destination="SVO", date_from=DAY, date_to=DAY)
    statuses = [SourceStatus("kupibilet", False, 0, "boom"), SourceStatus("aviasales_api", True, 1)]
    res = await verify_cached_prices(StubSvc(), [q], [cached], FilterSettings(), statuses)
    assert res[0].price_check is None


# ---------- новые рейсы в подписках ----------

def test_new_flights_detection():
    old = offer(10000, flights=("PC1",), transfers=1)
    new_cheap = offer(11000, flights=("ZF77",), dep_h=12)
    known = offer(30000, flights=("X1",), dep_h=5, transfers=1)
    new_direct = offer(40000, flights=("SU400",), dep_h=14)
    new_pricey = offer(50000, flights=("TK9",), dep_h=16, transfers=1)
    offers = [old, new_cheap, known, new_direct, new_pricey]
    assert find_new_flights(offers, None) == []  # первая проверка — ничего не «новое»
    assert find_new_flights(offers, [flight_key(old), flight_key(known)]) == [new_cheap, new_direct]


def test_remember_flights_forgets_departed():
    seen = remember_flights(["202611011000|PC5|SVO|0"], [offer(1)], DAY)
    assert seen == [flight_key(offer(1))]


def test_evaluate_new_flight_event():
    st = SubState(last_min_price=10000)
    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    assert evaluate(st, 10000, now, new_flights=1).events == ["new_flight"]
    assert evaluate(st, 10000, now).send is False
    st_off = SubState(last_min_price=10000, notify_new_flights=False)
    assert evaluate(st_off, 10000, now, new_flights=2).send is False


def test_alert_text_shows_new_flights_first():
    from bot.notifier import alert_text
    from common.models import Subscription
    from scheduler.rules import Decision

    sub = Subscription(id=1, origin="HRG", destination="MOW", origin_name="Хургада", destination_name="Москва",
                       date_from=DAY, date_to=DAY, adults=1, children=0)
    cheap, fresh = offer(10000), offer(30000, flights=("ZF1",), dep_h=12)
    q = SearchQuery(origin="HRG", destination="MOW", date_from=DAY, date_to=DAY)
    text = alert_text(sub, SearchResult(q, [cheap, fresh], 2), Decision(events=["new_flight"], send=True), 10000,
                      new_offers=[fresh])
    assert text.startswith("🆕 <b>Появился новый рейс</b>")
    assert text.index("ZF1") < text.index("PC1")
    assert "🆕 <b>1." in text


# ---------- автопроверка источников ----------

def test_health_problems_and_report():
    statuses = [
        SourceStatus("kupibilet", True, 0),  # молчит — подозрительно
        SourceStatus("anex", True, 0),  # чартеры: пусто — нормально
        SourceStatus("tutu", False, 0, "HTTP 500"),
        SourceStatus("aviakassa", True, 12),
    ]
    problems = find_problems(statuses)
    assert set(problems) == {"kupibilet", "tutu"}
    first = report(problems, None, "HRG-MOW")
    assert "Сломались" in first and "0 вариантов" in first
    assert report(problems, problems, "HRG-MOW") is None  # ничего не изменилось — не пишем
    fixed = report({"tutu": problems["tutu"]}, problems, "HRG-MOW")
    assert "Снова работают" in fixed and "Купибилет" in fixed and "Всё ещё не работают" in fixed


# ---------- запасной маршрут бота ----------

def _connect_error() -> ClientConnectorError:
    from aiohttp.client_reqrep import ConnectionKey

    key = ConnectionKey("127.0.0.1", 3067, False, True, None, None, None)
    return ClientConnectorError(key, OSError("refused"))


async def test_fallback_session_switches_to_direct(monkeypatch):
    from aiogram.client.session.aiohttp import AiohttpSession

    from bot.session import FallbackSession

    calls = []

    async def fake_request(self, bot, method, timeout=None):
        calls.append(self.proxy)
        if self.proxy:
            raise TelegramNetworkError(method=method, message="proxy down") from _connect_error()
        return "ok"

    monkeypatch.setattr(AiohttpSession, "make_request", fake_request)
    session = FallbackSession("http://127.0.0.1:3067")
    assert await session.make_request(None, object()) == "ok"
    assert calls == ["http://127.0.0.1:3067", None]
    assert session.use_direct
    assert await session.make_request(None, object()) == "ok"  # дальше сразу напрямую
    assert calls[-1] is None


async def test_fallback_session_does_not_resend_after_timeout(monkeypatch):
    from aiogram.client.session.aiohttp import AiohttpSession

    from bot.session import FallbackSession

    async def timeout_request(self, bot, method, timeout=None):
        raise TelegramNetworkError(method=method, message="Request timeout error") from TimeoutError()

    monkeypatch.setattr(AiohttpSession, "make_request", timeout_request)
    session = FallbackSession("http://127.0.0.1:3067")
    with pytest.raises(TelegramNetworkError):
        await session.make_request(None, object())
    assert session.use_direct  # следующий запрос пойдёт напрямую, но этот не повторяем
