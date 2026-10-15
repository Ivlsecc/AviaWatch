from datetime import date, datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    max_subscriptions: Mapped[int] = mapped_column(Integer, default=10)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    # Фильтры поиска по умолчанию (search.filters.FilterSettings)
    default_filters: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # Маршрут. Несколько городов — через запятую: "HRG,SSH"
    origin: Mapped[str] = mapped_column(String(64))
    destination: Mapped[str] = mapped_column(String(64))
    origin_name: Mapped[str] = mapped_column(String(256), default="")
    destination_name: Mapped[str] = mapped_column(String(256), default="")
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    adults: Mapped[int] = mapped_column(Integer, default=1)
    children: Mapped[int] = mapped_column(Integer, default=0)
    infants: Mapped[int] = mapped_column(Integer, default=0)
    direct_only: Mapped[bool] = mapped_column(Boolean, default=False)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)

    # Уведомления
    threshold_rub: Mapped[int | None] = mapped_column(Integer)
    notify_new_min: Mapped[bool] = mapped_column(Boolean, default=True)
    drop_percent: Mapped[float | None] = mapped_column(Float)
    digest_every_hours: Mapped[int | None] = mapped_column(Integer)
    quiet_from: Mapped[int | None] = mapped_column(Integer)  # час 0..23
    quiet_to: Mapped[int | None] = mapped_column(Integer)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_min_price: Mapped[int | None] = mapped_column(Integer)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="subscriptions")

    @property
    def origins(self) -> list[str]:
        return [c for c in self.origin.split(",") if c]

    @property
    def destinations(self) -> list[str]:
        return [c for c in self.destination.split(",") if c]


class SourceConfig(Base):
    """Настройки источника. Редактируются в админке (конфигуратор)."""

    __tablename__ = "source_configs"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=30)
    timeout_s: Mapped[float] = mapped_column(Float, default=20.0)
    retries: Mapped[int] = mapped_column(Integer, default=1)
    proxy: Mapped[str | None] = mapped_column(String(512))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    # Позиция узла на доске конфигуратора
    board_x: Mapped[float | None] = mapped_column(Float)
    board_y: Mapped[float | None] = mapped_column(Float)

    # Состояние (circuit breaker)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    disabled_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PriceSnapshot(Base):
    """Одна цена, увиденная в источнике. Основа для истории, средней и рекомендаций."""

    __tablename__ = "price_snapshots"
    __table_args__ = (Index("ix_snap_route_dep", "origin", "destination", "departure_date"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    origin: Mapped[str] = mapped_column(String(8))
    destination: Mapped[str] = mapped_column(String(8))
    departure_date: Mapped[date] = mapped_column(Date)
    departure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64))
    price_rub: Mapped[int] = mapped_column(Integer)
    transfers: Mapped[int] = mapped_column(Integer, default=0)
    duration_min: Mapped[int | None] = mapped_column(Integer)
    airline: Mapped[str | None] = mapped_column(String(64))
    flight_numbers: Mapped[str | None] = mapped_column(String(128))
    # calendar — цена из календаря (минимум за день), search — конкретное предложение
    kind: Mapped[str] = mapped_column(String(16), default="search")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PriceDaily(Base):
    """Дневной агрегат истории: минимальная цена на дату вылета, увиденная в конкретный день.

    Сырые PriceSnapshot старше N дней сворачиваются сюда и удаляются — история
    не растёт бесконечно, а тренды и средние по-прежнему считаются.
    """

    __tablename__ = "price_daily"

    origin: Mapped[str] = mapped_column(String(8), primary_key=True)
    destination: Mapped[str] = mapped_column(String(8), primary_key=True)
    departure_date: Mapped[date] = mapped_column(Date, primary_key=True)
    collected_date: Mapped[date] = mapped_column(Date, primary_key=True)
    min_price: Mapped[int] = mapped_column(Integer)
    samples: Mapped[int] = mapped_column(Integer, default=1)


class SearchLog(Base):
    __tablename__ = "search_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    origin: Mapped[str] = mapped_column(String(8))
    destination: Mapped[str] = mapped_column(String(8))
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    results: Mapped[int] = mapped_column(Integer, default=0)
    min_price: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
