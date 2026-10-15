"""Периодическая перепроверка подписок и рассылка уведомлений."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from common.config import get_settings
from common.db import session_scope
from common.metrics import NOTIFICATIONS
from common.models import Subscription, User
from scheduler.rules import Decision, SubState, evaluate
from search.analytics import route_price_stats
from search.filters import FilterSettings
from search.history import price_trend, roll_up_and_prune
from search.orchestrator import SearchResult, SearchService, as_utc
from search.recommend import Recommendation, recommend
from search.routes import RouteRequest, search_route

log = logging.getLogger(__name__)


class Notifier(Protocol):
    async def notify(
        self,
        sub: Subscription,
        user: User,
        result: SearchResult,
        decision: Decision,
        prev_price: int | None,
        rec: Recommendation | None = None,
    ) -> bool: ...


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
            except Exception:  # noqa: BLE001
                log.exception("history maintenance failed")
        due_before = now - timedelta(minutes=self.settings.subscription_check_minutes)
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
                if sub.date_to < now.date():
                    sub.is_active = False
        active = [sub for sub in subs if sub.date_to >= now.date()]
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
        result = await search_route(self.svc, subscription_request(sub, now.date()), FilterSettings.from_dict(sub.filters))
        min_price = result.offers[0].price_rub if result.offers else None

        state = SubState(
            last_min_price=sub.last_min_price,
            threshold_rub=sub.threshold_rub,
            notify_new_min=sub.notify_new_min,
            drop_percent=sub.drop_percent,
            digest_every_hours=sub.digest_every_hours,
            last_digest_at=as_utc(sub.last_digest_at),
            quiet_from=sub.quiet_from,
            quiet_to=sub.quiet_to,
            timezone=sub.user.timezone,
        )
        decision = evaluate(state, min_price, now)
        if force_send and min_price is not None and not decision.send:
            decision = Decision(events=["manual"], send=True, new_baseline=min_price)

        sent = False
        if decision.send:
            req = subscription_request(sub, now.date())
            rec = None
            try:
                stats = await route_price_stats(self.svc, req.origins, req.destinations, today=now.date())
                trend = await price_trend(req.origins, req.destinations, req.date_from, req.date_to, today=now.date())
                best = result.offers[0]
                rec = recommend(best.price_rub // max(req.passengers, 1), stats, trend, best.departure_date, now.date())
            except Exception:  # noqa: BLE001 — без рекомендации уведомление всё равно полезно
                log.exception("recommendation failed")
            sent = await self.notifier.notify(sub, sub.user, result, decision, sub.last_min_price, rec)
            for ev in decision.events:
                NOTIFICATIONS.labels(ev).inc()

        async with session_scope() as s:
            db_sub = await s.get(Subscription, sub.id)
            if db_sub is None:
                return decision
            db_sub.last_checked_at = now
            if decision.new_baseline is not None and (sent or not decision.send):
                db_sub.last_min_price = decision.new_baseline
            if sent:
                db_sub.last_notified_at = now
                if "digest" in decision.events:
                    db_sub.last_digest_at = now
        return decision
