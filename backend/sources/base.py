"""Общий интерфейс для всех источников цен.

Каждый сайт — отдельный класс-наследник Source, зарегистрированный через @register.
Источник ничего не знает о БД, кэше и пользователях: получает запрос и контекст,
возвращает нормализованные FlightOffer.
"""

from __future__ import annotations

import hashlib
import re
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
    # False — источник знает только дату (например, чартеры из Telegram)
    time_known: bool = True
    arrival_at: datetime | None = None
    duration_min: int | None = None
    transfers: int = 0

    airlines: list[str] = Field(default_factory=list)
    flight_numbers: list[str] = Field(default_factory=list)
    # Сегменты известны не во всех источниках; без них фильтры по стыковкам пропускаются
    segments: list[Segment] = Field(default_factory=list)

    # Цепочка аэропортов, если источник знает её без сегментов (например, HRG SAW IST SVO)
    route_airports: list[str] = Field(default_factory=list)
    airport_change: bool | None = None

    baggage_included: bool | None = None
    self_transfer: bool | None = None
    link: str
    # Пояснение для пользователя: условия чартера, багаж, сколько осталось мест
    note: str | None = None
    # Другие источники, где найден тот же рейс (заполняется при склейке дублей)
    alt_links: list[tuple[str, int, str]] = Field(default_factory=list)
    # Составной маршрут: отдельные билеты (подпись, цена, ссылка) — покупать каждый
    legs_links: list[tuple[str, int, str]] = Field(default_factory=list)
    # Цена одного билета при поиске на одного пассажира, если так заметно дешевле (см. search/split.py)
    split_single_rub: int | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def departure_date(self) -> date:
        return self.departure_at.date()

    def identity(self) -> tuple:
        """Ключ одного и того же рейса в разных источниках.

        Сравниваем только первый номер рейса: некоторые источники (Aviasales API)
        отдают номер лишь первого сегмента. Вылет минута-в-минуту + первый рейс +
        аэропорт прилёта + число пересадок практически однозначно задают перелёт.
        """
        # Местное время по часам, а не UTC: источники сходятся в «17:15», но ошибаются в поясе
        # (Aviasales API даёт Египту +02 летом, Купибилет — верное +03)
        dep = self.departure_at.strftime("%Y%m%d%H%M")
        if self.legs_links:
            # Составной маршрут никогда не склеиваем с обычным билетом: иначе он «унаследует» его условия
            return ("combo", dep, tuple(self.flight_numbers))
        first = re.sub(r"[\s\-–—]", "", self.flight_numbers[0]).upper() if self.flight_numbers else None
        if first:
            return (dep, first, self.destination_airport, self.transfers)
        return (dep, self.origin_airport, self.destination_airport, tuple(self.airlines), self.transfers)

    def norm_flights(self) -> tuple[str, ...]:
        return tuple(re.sub(r"[\s\-–—]", "", f).upper() for f in self.flight_numbers if f)

    def flights_complete(self) -> bool:
        """Известны номера всех рейсов маршрута (а не только первого, как у Aviasales API)."""
        return bool(self.flight_numbers) and len(self.flight_numbers) >= self.transfers + 1

    def full_identity(self) -> tuple | None:
        """Точный ключ маршрута — все рейсы по порядку. None, если источник знает не все рейсы.

        С общим первым рейсом бывают разные стыковки (PC637 + PC388 в 12:15 или PC390 в 20:00):
        их нельзя склеивать, иначе цена берётся от одного варианта, а время в пути — от другого.
        """
        if self.legs_links or not self.flights_complete():
            return None
        return (self.departure_at.strftime("%Y%m%d%H%M"), self.norm_flights(), self.destination_airport, self.transfers)

    def detail_score(self) -> int:
        return len(self.segments) * 10 + len(self.flight_numbers) + len(self.route_airports)

    def layovers_min(self) -> list[int]:
        return [
            int((b.departure_at - a.arrival_at).total_seconds() // 60)
            for a, b in zip(self.segments, self.segments[1:])
        ]

    def has_airport_change(self) -> bool:
        if self.airport_change is not None:
            return self.airport_change
        return any(a.destination != b.origin for a, b in zip(self.segments, self.segments[1:]))


@dataclass
class SourceContext:
    http: httpx.AsyncClient
    params: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 20.0
    # Самые дешёвые дни диапазона по календарю цен — подсказка для «дорогих» источников,
    # которые ищут по одному дню. Заполняет оркестратор на длинных диапазонах.
    focus_days: list[date] | None = None


MAX_SEARCH_DAYS = 5


def focus_days(query: "SearchQuery", ctx: SourceContext, max_days: int = MAX_SEARCH_DAYS) -> list[date]:
    """Дни, по которым искать: весь короткий диапазон или самые дешёвые дни длинного."""
    days = query.dates()
    if len(days) <= max_days:
        return days
    if ctx.focus_days:
        return sorted(d for d in ctx.focus_days if query.date_from <= d <= query.date_to)[:max_days]
    # Без календаря — равномерно по диапазону, чтобы не искать только в начале
    step = len(days) / max_days
    return [days[int(i * step)] for i in range(max_days)]


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
    # Таймаут по умолчанию для нового конфига источника (дальше меняется в админке)
    default_timeout_s: ClassVar[float] = 20.0
    # Прокси по умолчанию: None — глобальный из .env, "direct" — всегда напрямую, мимо системного прокси
    default_proxy: ClassVar[str | None] = None

    @abstractmethod
    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        """Найти предложения по запросу. Ошибки — исключением, пустой список — «ничего нет»."""

    async def calendar(
        self, origin: str, destination: str, date_from: date, date_to: date, ctx: SourceContext
    ) -> dict[date, int]:
        """Минимальная цена за 1 взрослого по дням вылета. Только для supports_calendar."""
        raise NotImplementedError
