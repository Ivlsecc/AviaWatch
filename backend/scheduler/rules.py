"""Решение «слать ли уведомление» по подписке. Чистые функции — легко тестировать."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass
class SubState:
    last_min_price: int | None  # базовая цена, с которой сравниваем
    threshold_rub: int | None = None
    notify_new_min: bool = True
    drop_percent: float | None = None
    digest_every_hours: int | None = None
    notify_new_flights: bool = True
    last_digest_at: datetime | None = None
    quiet_from: int | None = None
    quiet_to: int | None = None
    timezone: str = "Europe/Moscow"


@dataclass
class Decision:
    events: list[str] = field(default_factory=list)  # threshold | drop | new_flight | digest
    send: bool = False
    # Новая база для сравнения; None — не трогать (уведомление отложено тихими часами)
    new_baseline: int | None = None
    deferred: bool = False


def in_quiet_hours(now: datetime, tz: str, q_from: int | None, q_to: int | None) -> bool:
    if q_from is None or q_to is None or q_from == q_to:
        return False
    hour = now.astimezone(ZoneInfo(tz)).hour
    if q_from < q_to:
        return q_from <= hour < q_to
    return hour >= q_from or hour < q_to  # окно через полночь, например 23–8


def evaluate(st: SubState, min_price: int | None, now: datetime, new_flights: int = 0) -> Decision:
    """new_flights — сколько интересных рейсов впервые появилось в выдаче (считает checker)."""
    if min_price is None:
        return Decision(new_baseline=None)

    prev = st.last_min_price
    events: list[str] = []

    if st.threshold_rub is not None and min_price <= st.threshold_rub:
        # Только при пересечении порога или дальнейшем снижении — без спама каждый час
        if prev is None or prev > st.threshold_rub or min_price < prev:
            events.append("threshold")

    if prev is not None and min_price < prev and "threshold" not in events:
        if st.drop_percent:
            if min_price <= prev * (1 - st.drop_percent / 100):
                events.append("drop")
        elif st.notify_new_min:
            events.append("drop")

    if new_flights and st.notify_new_flights:
        events.append("new_flight")

    if st.digest_every_hours and (
        st.last_digest_at is None or now - st.last_digest_at >= timedelta(hours=st.digest_every_hours)
    ):
        events.append("digest")

    if not events:
        return Decision(new_baseline=min_price)

    if in_quiet_hours(now, st.timezone, st.quiet_from, st.quiet_to):
        # Базу не двигаем: после тихих часов снижение всё ещё будет заметно
        return Decision(events=events, send=False, new_baseline=None, deferred=True)

    return Decision(events=events, send=True, new_baseline=min_price)
