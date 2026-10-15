from datetime import datetime, timedelta, timezone

from scheduler.rules import SubState, evaluate, in_quiet_hours

# 12:00 МСК
NOON = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
# 02:00 МСК
NIGHT = datetime(2026, 11, 1, 23, 0, tzinfo=timezone.utc)


def test_first_check_sets_baseline_silently():
    d = evaluate(SubState(last_min_price=None), 20000, NOON)
    assert not d.send and d.new_baseline == 20000


def test_any_new_min_notifies():
    d = evaluate(SubState(last_min_price=20000), 19900, NOON)
    assert d.send and d.events == ["drop"] and d.new_baseline == 19900


def test_price_rise_updates_baseline_without_alert():
    d = evaluate(SubState(last_min_price=20000), 23000, NOON)
    assert not d.send and d.new_baseline == 23000


def test_drop_percent_ignores_small_drops():
    st = SubState(last_min_price=20000, drop_percent=5)
    assert not evaluate(st, 19500, NOON).send  # −2.5%
    assert evaluate(st, 19000, NOON).events == ["drop"]  # −5%


def test_new_min_disabled():
    assert not evaluate(SubState(last_min_price=20000, notify_new_min=False), 15000, NOON).send


def test_threshold_only_on_crossing_or_further_drop():
    st = SubState(last_min_price=21000, threshold_rub=20000, notify_new_min=False)
    assert evaluate(st, 19500, NOON).events == ["threshold"]  # пересекли порог
    st.last_min_price = 19500
    assert not evaluate(st, 19500, NOON).send  # стоит на месте — молчим
    assert not evaluate(st, 19800, NOON).send  # подросла, но ниже порога — молчим
    assert evaluate(st, 19000, NOON).events == ["threshold"]  # ещё дешевле


def test_threshold_on_first_check():
    d = evaluate(SubState(last_min_price=None, threshold_rub=20000), 18000, NOON)
    assert d.send and d.events == ["threshold"]


def test_digest_interval():
    st = SubState(last_min_price=20000, digest_every_hours=6, last_digest_at=NOON - timedelta(hours=5))
    assert not evaluate(st, 20000, NOON).send
    st.last_digest_at = NOON - timedelta(hours=6)
    assert evaluate(st, 20000, NOON).events == ["digest"]


def test_quiet_hours_defer_and_keep_baseline():
    st = SubState(last_min_price=20000, quiet_from=23, quiet_to=8)
    d = evaluate(st, 18000, NIGHT)
    assert not d.send and d.deferred and d.new_baseline is None
    # Утром снижение всё ещё видно относительно старой базы
    assert evaluate(st, 18000, NOON).events == ["drop"]


def test_quiet_hours_window():
    assert in_quiet_hours(NIGHT, "Europe/Moscow", 23, 8)
    assert not in_quiet_hours(NOON, "Europe/Moscow", 23, 8)
    assert in_quiet_hours(NOON, "Europe/Moscow", 10, 14)
    assert not in_quiet_hours(NOON, "Europe/Moscow", None, None)


def test_no_offers_no_change():
    d = evaluate(SubState(last_min_price=20000), None, NOON)
    assert not d.send and d.new_baseline is None
