"""Отсев «мусорных» маршрутов. Все пороги настраиваются пользователем."""

from __future__ import annotations

from pydantic import BaseModel

from sources.base import FlightOffer

NIGHT_HOURS = range(0, 6)


class FilterSettings(BaseModel):
    max_transfers: int = 1
    # Не дольше чем во столько раз самого быстрого варианта в выдаче (None — без ограничения)
    max_duration_factor: float | None = 2.0
    max_duration_hours: float | None = None
    min_layover_min: int = 60
    max_layover_min: int = 8 * 60
    exclude_airport_change: bool = True
    exclude_self_transfer: bool = True
    exclude_night_layovers: bool = False
    baggage_required: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> "FilterSettings":
        return cls.model_validate(data or {})


def apply_filters(offers: list[FlightOffer], f: FilterSettings) -> list[FlightOffer]:
    result = [o for o in offers if _passes(o, f)]

    if f.max_duration_factor:
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

    # Проверки стыковок — только если источник отдал сегменты
    if len(o.segments) > 1:
        if f.exclude_airport_change and o.has_airport_change():
            return False
        for minutes in o.layovers_min():
            if minutes < f.min_layover_min or minutes > f.max_layover_min:
                return False
        if f.exclude_night_layovers:
            for a in o.segments[:-1]:
                if a.arrival_at.hour in NIGHT_HOURS:
                    return False
    return True
