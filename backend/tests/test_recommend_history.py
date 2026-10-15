from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from common.db import session_scope
from common.models import PriceDaily, PriceSnapshot
from search.analytics import PriceStats
from search.history import Trend, past_daily_min, price_trend, roll_up_and_prune
from search.recommend import BUY, NEUTRAL, WAIT, recommend

TODAY = date(2026, 10, 15)
STATS = PriceStats(mean=20000, median=20000, days=40, past_days=10, window_from=TODAY, window_to=TODAY, p25=17000)


def trend(*prices):
    return Trend([(TODAY - timedelta(days=len(prices) - 1 - i), p) for i, p in enumerate(prices)])


def test_cheap_price_is_buy():
    r = recommend(16500, STATS, trend(16500, 16500), TODAY + timedelta(days=40), TODAY)
    assert r.verdict == BUY and "нижней четверти" in r.reasons[0] and not r.low_confidence


def test_expensive_far_departure_and_falling_is_wait():
    r = recommend(25000, STATS, trend(28000, 25000), TODAY + timedelta(days=70), TODAY)
    assert r.verdict == WAIT
    assert any("дороже" in x for x in r.reasons) and any("снизилась" in x for x in r.reasons)


def test_close_departure_pushes_to_buy_even_if_pricey():
    r = recommend(23000, STATS, None, TODAY + timedelta(days=2), TODAY)
    assert r.verdict == BUY and any("до вылета 2" in x for x in r.reasons)
    assert r.low_confidence  # нет тренда


def test_average_price_is_neutral():
    r = recommend(20500, STATS, trend(20500, 20400), TODAY + timedelta(days=30), TODAY)
    assert r.verdict == NEUTRAL


def test_rising_trend_adds_to_buy():
    r = recommend(19500, STATS, trend(18000, 19500), TODAY + timedelta(days=30), TODAY)
    assert r.verdict == BUY and any("выросла" in x for x in r.reasons)


def test_no_price_no_recommendation():
    assert recommend(None, STATS, None, TODAY, TODAY) is None


def _snap(dep: date, price: int, collected: datetime, origin="HRG"):
    return PriceSnapshot(origin=origin, destination="MOW", departure_date=dep, source="x", price_rub=price,
                         collected_at=collected)


async def test_trend_daily_min_by_collected_day():
    dep = TODAY + timedelta(days=20)
    base = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
    async with session_scope() as s:
        s.add_all([
            _snap(dep, 21000, base), _snap(dep, 20000, base + timedelta(hours=5)),  # 12.10 → 20000
            _snap(dep, 19000, base + timedelta(days=2)),  # 14.10
            _snap(dep, 18500, base + timedelta(days=3), origin="SSH"),  # 15.10, другой город группы
            _snap(dep + timedelta(days=30), 1000, base + timedelta(days=3)),  # не наши даты
            _snap(dep, 500, base - timedelta(days=10)),  # слишком давно
        ])
    t = await price_trend(["HRG", "SSH"], ["MOW"], dep, dep, days=7, today=TODAY)
    assert t.points == [(date(2026, 10, 12), 20000), (date(2026, 10, 14), 19000), (date(2026, 10, 15), 18500)]
    assert round(t.change_pct, 1) == -7.5 and t.days == 3


async def test_roll_up_keeps_history_queryable():
    dep = date(2026, 9, 1)
    old = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    fresh = datetime(2026, 10, 14, 10, tzinfo=timezone.utc)
    async with session_scope() as s:
        s.add_all([_snap(dep, 15000, old), _snap(dep, 14000, old + timedelta(hours=3)),
                   _snap(dep, 16000, old + timedelta(days=1)), _snap(dep, 13000, fresh)])

    deleted = await roll_up_and_prune(keep_days=30, now=datetime(2026, 10, 15, tzinfo=timezone.utc))
    assert deleted == 3
    async with session_scope() as s:
        assert await s.scalar(select(func.count(PriceSnapshot.id))) == 1
        rows = (await s.scalars(select(PriceDaily).order_by(PriceDaily.collected_date))).all()
        assert [(r.collected_date, r.min_price, r.samples) for r in rows] == [
            (date(2026, 8, 1), 14000, 2), (date(2026, 8, 2), 16000, 1)
        ]
    # Минимум по дате вылета учитывает и агрегаты, и свежие снимки
    assert await past_daily_min(["HRG"], ["MOW"], dep, dep) == {dep: 13000}

    # Повторная свёртка ничего не ломает
    assert await roll_up_and_prune(keep_days=30, now=datetime(2026, 10, 15, tzinfo=timezone.utc)) == 0


async def test_prune_logs_removes_only_old_rows():
    from common.models import SearchLog, SourceRunLog
    from search.history import prune_logs

    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    async with session_scope() as s:
        s.add_all([
            SourceRunLog(source="x", ok=True, elapsed_ms=1, created_at=now - timedelta(days=40)),
            SourceRunLog(source="x", ok=True, elapsed_ms=1, created_at=now - timedelta(days=1)),
            SearchLog(origin="HRG", destination="MOW", date_from=TODAY, date_to=TODAY, created_at=now - timedelta(days=31)),
        ])
    assert await prune_logs(keep_days=30, now=now) == 2
    async with session_scope() as s:
        assert await s.scalar(select(func.count(SourceRunLog.id))) == 1
