"""Отсев «мусорных» маршрутов. Все пороги настраиваются пользователем."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from common.airports import airports
from sources.base import FlightOffer

NIGHT_HOURS = range(0, 6)
# Окна времени прилёта (местное время аэропорта прибытия): [с, до) в часах
ARRIVAL_WINDOWS: dict[str, tuple[int, int]] = {
    "no_night": (6, 24),  # не ночью
    "day": (8, 22),  # днём, чтобы спокойно добраться из аэропорта
}


class FilterSettings(BaseModel):
    max_transfers: int = 1
    # Не дольше чем во столько раз самого быстрого варианта в выдаче (None — без ограничения).
    # Работает, только пока пользователь не задал явный лимит в часах.
    max_duration_factor: float | None = 2.5
    max_duration_hours: float | None = None
    min_layover_min: int = 60
    max_layover_min: int = 8 * 60
    exclude_airport_change: bool = True
    exclude_self_transfer: bool = True
    exclude_night_layovers: bool = False
    baggage_required: bool = False
    # Ключ из ARRIVAL_WINDOWS; None — прилёт в любое время
    arrival_window: str | None = None
    # Только эти аэропорты прилёта (например, Внуково и Шереметьево); пусто — любые
    arrival_airports: list[str] = Field(default_factory=list)
    # Искать составные маршруты из отдельных билетов через хабы (Стамбул, Каир, Дубай…)
    self_combos: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> "FilterSettings":
        return cls.model_validate(data or {})


def apply_filters(offers: list[FlightOffer], f: FilterSettings) -> list[FlightOffer]:
    result = [o for o in offers if _passes(o, f)]

    if f.max_duration_factor and not f.max_duration_hours:
        durations = [o.duration_min for o in result if o.duration_min]
        if durations:
            limit = min(durations) * f.max_duration_factor
            result = [o for o in result if not o.duration_min or o.duration_min <= limit]
    return result


def _passes(o: FlightOffer, f: FilterSettings) -> bool:
    if o.transfers > f.max_transfers:
        return False
    if f.max_duration_hours and o.duration_min and o.duration_min > f.max_duration_hours * 60:
        return False
    if f.baggage_required and o.baggage_included is False:
        return False
    if f.exclude_self_transfer and o.self_transfer:
        return False
    if f.exclude_airport_change and o.has_airport_change():
        return False
    if f.arrival_airports and o.destination_airport not in f.arrival_airports:
        return False
    if f.arrival_window in ARRIVAL_WINDOWS and o.time_known and (arr := local_arrival(o)):
        lo, hi = ARRIVAL_WINDOWS[f.arrival_window]
        if not lo <= arr.hour < hi:
            return False

    # Проверки длительности стыковок — только если источник отдал сегменты
    if len(o.segments) > 1:
        for minutes in o.layovers_min():
            if minutes < f.min_layover_min or minutes > f.max_layover_min:
                return False
        if f.exclude_night_layovers:
            for a in o.segments[:-1]:
                if a.arrival_at.hour in NIGHT_HOURS:
                    return False
    return True


def local_arrival(o: FlightOffer) -> datetime | None:
    """Прилёт по местному времени аэропорта прибытия (у источников бывает пояс вылета)."""
    if not o.arrival_at:
        return None
    tz = airports.tz(o.destination_airport)
    if not tz or o.arrival_at.tzinfo is None:
        return o.arrival_at
    try:
        return o.arrival_at.astimezone(ZoneInfo(tz))
    except Exception:  # noqa: BLE001 — неизвестный пояс: показываем как есть
        return o.arrival_at
