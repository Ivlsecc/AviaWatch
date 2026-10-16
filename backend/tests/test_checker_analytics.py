from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from common.db import session_scope
from common.models import PriceSnapshot, SourceConfig, Subscription, User
from scheduler.checker import SubscriptionChecker
from search.analytics import compute_stats, route_price_stats
from search.cache import MemoryCache
from search.orchestrator import SearchService, sync_source_configs
from sources.base import FlightOffer, SearchQuery, Source, SourceContext
from sources.registry import register

PRICE = {"value": 20000}
TODAY = date.today()


@register
class FakeCalendarSource(Source):
    name = "fake_cal"
    title = "Fake calendar"
    supports_calendar = True

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        dep = datetime.combine(query.date_from, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
        return [
            FlightOffer(source=self.name, price_rub=PRICE["value"] * query.passengers, origin_airport=query.origin,
                        destination_airport="SVO", departure_at=dep, duration_min=300, link="https://x")
        ]

    async def calendar(self, origin, destination, date_from, date_to, ctx):
        return {date_from + timedelta(days=i): 10000 + i * 100 for i in range(5)}


class FakeNotifier:
    def __init__(self):
        self.sent = []
        self.recs = []

    async def notify(self, sub, user, result, decision, prev_price, rec=None, new_offers=None):
        self.recs.append(rec)
        self.sent.append((sub.id, decision.events, result.offers[0].price_rub, prev_price))
        return True


async def _setup(**sub_kw) -> int:
    await sync_source_configs()
    async with session_scope() as s:
        for cfg in (await s.scalars(select(SourceConfig))).all():
            cfg.enabled = cfg.name == "fake_cal"
            cfg.retries = 0
            cfg.rate_limit_per_min = 0
        user = User(tg_id=1, default_filters={})
        s.add(user)
        await s.flush()
        sub = Subscription(user_id=user.id, origin="HRG,SSH", destination="MOW", date_from=TODAY + timedelta(days=10),
                           date_to=TODAY + timedelta(days=12), adults=2, filters={}, **sub_kw)
        s.add(sub)
        await s.flush()
        return sub.id


async def test_checker_baseline_then_drop_alert():
    sub_id = await _setup()
    notifier = FakeNotifier()
    svc = SearchService(cache=MemoryCache())
    checker = SubscriptionChecker(svc, notifier)
    try:
        PRICE["value"] = 20000
        now = datetime.now(timezone.utc)
        assert await checker.tick(now) == 1
        assert notifier.sent == []  # первая проверка — только база

        async with session_scope() as s:
            assert (await s.get(Subscription, sub_id)).last_min_price == 40000

        # Не пора — интервал ещё не прошёл
        assert await checker.tick(now + timedelta(minutes=10)) == 0

        PRICE["value"] = 18000
        svc.cache = MemoryCache()  # сбрасываем кэш поиска
        assert await checker.tick(now + timedelta(minutes=61)) == 1
        assert notifier.sent == [(sub_id, ["drop"], 36000, 40000)]
        async with session_scope() as s:
            sub = await s.get(Subscription, sub_id)
            assert sub.last_min_price == 36000 and sub.last_notified_at is not None
    finally:
        await svc.close()


async def test_expired_subscription_deactivated():
    sub_id = await _setup()
    async with session_scope() as s:
        sub = await s.get(Subscription, sub_id)
        sub.date_from = sub.date_to = TODAY - timedelta(days=1)
    svc = SearchService(cache=MemoryCache())
    try:
        assert await SubscriptionChecker(svc, FakeNotifier()).tick() == 0
    finally:
        await svc.close()
    async with session_scope() as s:
        assert not (await s.get(Subscription, sub_id)).is_active


async def test_price_stats_combines_calendar_and_history():
    await _setup()
    async with session_scope() as s:
        # История за прошлые даты: минимум по дню
        s.add_all(
            [
                PriceSnapshot(origin="HRG", destination="MOW", departure_date=TODAY - timedelta(days=3),
                              source="x", price_rub=12000),
                PriceSnapshot(origin="HRG", destination="MOW", departure_date=TODAY - timedelta(days=3),
                              source="y", price_rub=11000),
                PriceSnapshot(origin="HRG", destination="MOW", departure_date=TODAY - timedelta(days=40),
                              source="x", price_rub=1),  # вне окна
            ]
        )
    svc = SearchService(cache=MemoryCache())
    try:
        stats = await route_price_stats(svc, ["HRG", "SSH"], ["MOW"], today=TODAY)
    finally:
        await svc.close()
    # 5 будущих дней 10000..10400 + 1 прошлый день 11000
    assert stats.days == 6 and stats.past_days == 1
    assert stats.mean == round((10000 + 10100 + 10200 + 10300 + 10400 + 11000) / 6)
    async with session_scope() as s:
        cal = (await s.scalars(select(PriceSnapshot).where(PriceSnapshot.kind == "calendar"))).all()
        assert len(cal) == 10  # 5 дней × 2 направления сохранены в историю


def test_compute_stats_empty():
    st = compute_stats({}, {}, TODAY, TODAY)
    assert st.mean is None and st.days == 0
