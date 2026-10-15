"""Общий интерфейс для всех источников цен.

Каждый сайт — отдельный класс-наследник Source, зарегистрированный через @register.
Источник ничего не знает о БД, кэше и пользователях: получает запрос и контекст,
возвращает нормализованные FlightOffer.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field


class SearchQuery(BaseModel, frozen=True):
    origin: str  # IATA города или аэропорта
    destination: str
    date_from: date
    date_to: date
    adults: int = 1
    children: int = 0
    infants: int = 0
    direct_only: bool = False

    @property
    def passengers(self) -> int:
        # Младенцы без места обычно почти бесплатны, в общую стоимость не считаем
        return self.adults + self.children

    def dates(self) -> list[date]:
        days = (self.date_to - self.date_from).days
        return [date.fromordinal(self.date_from.toordinal() + i) for i in range(days + 1)]

    def cache_key(self) -> str:
        raw = self.model_dump_json()
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


class Segment(BaseModel):
    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime
    airline: str | None = None
    flight_number: str | None = None


class FlightOffer(BaseModel):
    source: str
    price_rub: int  # за всех пассажиров
    price_original: float | None = None
    currency: str = "RUB"

    origin_airport: str
    destination_airport: str
    departure_at: datetime
    arrival_at: datetime | None = None
    duration_min: int | None = None
    transfers: int = 0

    airlines: list[str] = Field(default_factory=list)
    flight_numbers: list[str] = Field(default_factory=list)
    # Сегменты известны не во всех источниках; без них фильтры по стыковкам пропускаются
    segments: list[Segment] = Field(default_factory=list)

    baggage_included: bool | None = None
    self_transfer: bool | None = None
    link: str
    # Другие источники, где найден тот же рейс (заполняется при склейке дублей)
    alt_links: list[tuple[str, int, str]] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def departure_date(self) -> date:
        return self.departure_at.date()

    def identity(self) -> tuple:
        """Ключ одного и того же рейса в разных источниках."""
        dep = self.departure_at.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
        if self.flight_numbers:
            return (dep, tuple(f.replace(" ", "").upper() for f in self.flight_numbers))
        return (dep, self.origin_airport, self.destination_airport, tuple(self.airlines), self.transfers)

    def layovers_min(self) -> list[int]:
        return [
            int((b.departure_at - a.arrival_at).total_seconds() // 60)
            for a, b in zip(self.segments, self.segments[1:])
        ]

    def has_airport_change(self) -> bool:
        return any(a.destination != b.origin for a, b in zip(self.segments, self.segments[1:]))


@dataclass
class SourceContext:
    http: httpx.AsyncClient
    params: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 20.0


class SourceError(Exception):
    pass


class Source(ABC):
    name: ClassVar[str]
    title: ClassVar[str]
    # api | json | browser — для отображения в конфигураторе
    method: ClassVar[str] = "json"
    # Какие параметры источник принимает в SourceConfig.params (для формы в админке)
    param_schema: ClassVar[dict[str, str]] = {}
    supports_calendar: ClassVar[bool] = False

    @abstractmethod
    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        """Найти предложения по запросу. Ошибки — исключением, пустой список — «ничего нет»."""

    async def calendar(
        self, origin: str, destination: str, date_from: date, date_to: date, ctx: SourceContext
    ) -> dict[date, int]:
        """Минимальная цена за 1 взрослого по дням вылета. Только для supports_calendar."""
        raise NotImplementedError
