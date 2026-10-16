"""Периодическая перепроверка подписок и рассылка уведомлений."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from common import app_settings
from common.config import get_settings
from common.db import session_scope
from common.metrics import NOTIFICATIONS
from common.models import NotificationLog, Subscription, User
from scheduler.rules import Decision, SubState, evaluate
from search.analytics import route_price_stats
from search.filters import FilterSettings
from search.history import price_trend, prune_logs, roll_up_and_prune
from search.orchestrator import SearchResult, SearchService, as_utc
from search.recommend import Recommendation, recommend
from search.routes import RouteRequest, search_route
from sources.base import FlightOffer

log = logging.getLogger(__name__)

# Даты поездок пользователи задают по местному времени; для РФ/Египта берём московское
LOCAL_TZ = ZoneInfo("Europe/Moscow")


def local_today(now: datetime) -> date:
    return now.astimezone(LOCAL_TZ).date()


class Notifier(Protocol):
    async def notify(
        self,
        sub: Subscription,
        user: User,
        result: SearchResult,
        decision: Decision,
        prev_price: int | None,
        rec: Recommendation | None = None,
        new_offers: list[FlightOffer] | None = None,
    ) -> bool: ...


# Сколько ключей рейсов помним на подписку
MAX_SEEN = 500
# Новый рейс стоит уведомления, если он прямой или среди стольких самых дешёвых в выдаче
NEW_FLIGHT_TOP = 3


def flight_key(o: FlightOffer) -> str:
    return "|".join(str(x) for x in o.identity())


def find_new_flights(offers: list[FlightOffer], seen: list[str] | None) -> list[FlightOffer]:
    """Интересные рейсы, которых раньше не было в выдаче. Первая проверка подписки ничего не считает новым."""
    if seen is None:
        return []
    known = set(seen)
    return [
        o for i, o in enumerate(offers)
        if flight_key(o) not in known and not o.legs_links and (i < NEW_FLIGHT_TOP or o.transfers == 0)
    ]


def remember_flights(seen: list[str] | None, offers: list[FlightOffer], today: date) -> list[str]:
    """Добавляет рейсы выдачи к уже виденным и забывает улетевшие. Однажды виденный рейс снова «новым» не станет,
    даже если источник, который его нашёл, на время пропадал."""
    keys = list(seen or [])
    known = set(keys)
    for o in offers:
        if (k := flight_key(o)) not in known:
            keys.append(k)
            known.add(k)
    cutoff = today.strftime("%Y%m%d")
    keys = [k for k in keys if not (m := re.search(r"(\d{8})\d{4}", k)) or m.group(1) >= cutoff]
    return keys[-MAX_SEEN:]


def subscription_request(sub: Subscription, today: date | None = None) -> RouteRequest:
    today = today or date.today()
    return RouteRequest(
        origins=sub.origins,
        destinations=sub.destinations,
        origin_names=[n for n in sub.origin_name.split(", ") if n],
        destination_names=[n for n in sub.destination_name.split(", ") if n],
        date_from=max(sub.date_from, today),
        date_to=sub.date_to,
        adults=sub.adults,
        children=sub.children,
        infants=sub.infants,
        direct_only=sub.direct_only,
    )


class SubscriptionChecker:
    def __init__(self, svc: SearchService, notifier: Notifier, concurrency: int = 4) -> None:
        self.svc = svc
        self.notifier = notifier
        self.settings = get_settings()
        self._sem = asyncio.Semaphore(concurrency)
        self._last_maintenance: datetime | None = None

    async def run_forever(self, tick_s: int = 60) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("subscription tick failed")
            await asyncio.sleep(tick_s)

    async def tick(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        if self._last_maintenance is None or now - self._last_maintenance >= timedelta(hours=24):
            self._last_maintenance = now
            try:
                await roll_up_and_prune(now=now)
                await prune_logs(now=now)
            except Exception:  # noqa: BLE001
                log.exception("history maintenance failed")
        interval = int(await app_settings.get("subscription_check_minutes") or self.settings.subscription_check_minutes)
        due_before = now - timedelta(minutes=interval)
        async with session_scope() as s:
            subs = (
                await s.scalars(
                    select(Subscription)
                    .join(User)
                    .options(selectinload(Subscription.user))
                    .where(
                        Subscription.is_active.is_(True),
                        User.is_blocked.is_(False),
                        or_(Subscription.last_checked_at.is_(None), Subscription.last_checked_at <= due_before),
                    )
                )
            ).all()
            # Даты поездки прошли — подписка больше не нужна
            for sub in subs:
                if sub.date_to < local_today(now):
                    sub.is_active = False
        active = [sub for sub in subs if sub.date_to >= local_today(now)]
        await asyncio.gather(*(self._check_guarded(sub, now) for sub in active))
        return len(active)

    async def _check_guarded(self, sub: Subscription, now: datetime) -> None:
        async with self._sem:
            try:
                await self.check(sub, now)
            except Exception:  # noqa: BLE001
                log.exception("check subscription %s failed", sub.id)

    async def check(self, sub: Subscription, now: datetime | None = None, force_send: bool = False) -> Decision:
        now = now or datetime.now(timezone.utc)
        result = await search_route(
            self.svc, subscription_request(sub, local_today(now)), FilterSettings.from_dict(sub.filters), split_check=True
        )
        # Цены из кэша, которые живые сайты не подтвердили, не должны вызывать уведомления
        result.offers = [o for o in result.offers if o.price_check != "unconfirmed"]
        min_price = result.offers[0].price_rub if result.offers else None
        new_offers = find_new_flights(result.offers, sub.seen_flights)

        state = SubState(
            last_min_price=sub.last_min_price,
            threshold_rub=sub.threshold_rub,
            notify_new_min=sub.notify_new_min,
            drop_percent=sub.drop_percent,
            digest_every_hours=sub.digest_every_hours,
            notify_new_flights=sub.notify_new_flights,
            last_digest_at=as_utc(sub.last_digest_at),
            quiet_from=sub.quiet_from,
            quiet_to=sub.quiet_to,
            timezone=sub.user.timezone,
        )
        decision = evaluate(state, min_price, now, new_flights=len(new_offers))
        if force_send and min_price is not None and not decision.send:
            decision = Decision(events=["manual"], send=True, new_baseline=min_price)

        sent = False
        if decision.send:
            req = subscription_request(sub, local_today(now))
            rec = None
            try:
                stats = await route_price_stats(self.svc, req.origins, req.destinations, today=local_today(now))
                trend = await price_trend(req.origins, req.destinations, req.date_from, req.date_to, today=local_today(now))
                best = result.offers[0]
                rec = recommend(best.price_rub // max(req.passengers, 1), stats, trend, best.departure_date, local_today(now))
            except Exception:  # noqa: BLE001 — без рекомендации уведомление всё равно полезно
                log.exception("recommendation failed")
            fresh = new_offers if "new_flight" in decision.events else None
            sent = await self.notifier.notify(sub, sub.user, result, decision, sub.last_min_price, rec, fresh)
            for ev in decision.events:
                NOTIFICATIONS.labels(ev).inc()

        async with session_scope() as s:
            db_sub = await s.get(Subscription, sub.id)
            if db_sub is None:
                return decision
            db_sub.last_checked_at = now
            if decision.new_baseline is not None and (sent or not decision.send):
                db_sub.last_min_price = decision.new_baseline
            if not decision.deferred and (sent or not decision.send):
                db_sub.seen_flights = remember_flights(sub.seen_flights, result.offers, local_today(now))
            if sent:
                db_sub.last_notified_at = now
                if "digest" in decision.events:
                    db_sub.last_digest_at = now
            if decision.send:
                s.add(
                    NotificationLog(
                        user_id=sub.user_id, subscription_id=sub.id, kind=decision.events[0], ok=sent,
                        price=result.offers[0].price_rub if result.offers else None, created_at=now,
                    )
                )
        return decision
