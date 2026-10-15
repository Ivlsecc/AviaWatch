"""Дашборд: сводка, активность по часам, здоровье источников, нагрузка на машину."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from api.auth import require_admin
from api.system import sampler
from common.db import session_scope
from common.models import NotificationLog, SearchLog, SourceConfig, SourceRunLog, Subscription, User
from search.orchestrator import as_utc
from sources.registry import all_sources

router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(require_admin)])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/dashboard/summary")
async def summary() -> dict:
    now = _now()
    day, week = now - timedelta(days=1), now - timedelta(days=7)
    async with session_scope() as s:
        users = await s.scalar(select(func.count(User.id)))
        dau = await s.scalar(select(func.count(User.id)).where(User.last_seen_at >= day))
        wau = await s.scalar(select(func.count(User.id)).where(User.last_seen_at >= week))
        new_users = await s.scalar(select(func.count(User.id)).where(User.created_at >= day))
        blocked = await s.scalar(select(func.count(User.id)).where(User.is_blocked.is_(True)))
        subs = await s.scalar(select(func.count(Subscription.id)).where(Subscription.is_active.is_(True)))
        searches = await s.scalar(select(func.count(SearchLog.id)).where(SearchLog.created_at >= day))
        cached = await s.scalar(
            select(func.count(SearchLog.id)).where(SearchLog.created_at >= day, SearchLog.from_cache.is_(True))
        )
        runs = await s.scalar(select(func.count(SourceRunLog.id)).where(SourceRunLog.created_at >= day))
        errors = await s.scalar(
            select(func.count(SourceRunLog.id)).where(SourceRunLog.created_at >= day, SourceRunLog.ok.is_(False))
        )
        notifications = await s.scalar(select(func.count(NotificationLog.id)).where(NotificationLog.created_at >= day))
        sources = (await s.scalars(select(SourceConfig))).all()
    down = [c.name for c in sources if (u := as_utc(c.disabled_until)) and u > now]
    return {
        "users": users, "dau": dau, "wau": wau, "new_users_24h": new_users, "blocked": blocked,
        "active_subscriptions": subs, "searches_24h": searches, "cache_hit_rate": round(cached / searches, 2) if searches else None,
        "source_requests_24h": runs, "source_errors_24h": errors, "notifications_24h": notifications,
        "sources_total": len([c for c in sources if c.name in all_sources()]),
        "sources_enabled": len([c for c in sources if c.enabled and c.name in all_sources()]),
        "sources_down": down,
    }


@router.get("/dashboard/activity")
async def activity(hours: int = Query(24, ge=1, le=24 * 30)) -> list[dict]:
    """Поиски, запросы к источникам, ошибки и уведомления по часам."""
    now = _now()
    since = now - timedelta(hours=hours)
    bucket_h = 1 if hours <= 48 else 6 if hours <= 24 * 7 else 24
    buckets: dict[datetime, dict] = {}

    def key(dt: datetime) -> datetime:
        dt = as_utc(dt)
        floored = dt.replace(minute=0, second=0, microsecond=0)
        return floored - timedelta(hours=floored.hour % bucket_h)

    t = key(since)
    while t <= now:
        buckets[t] = {"ts": t.isoformat(), "searches": 0, "requests": 0, "errors": 0, "notifications": 0}
        t += timedelta(hours=bucket_h)

    async with session_scope() as s:
        for (created,) in (await s.execute(select(SearchLog.created_at).where(SearchLog.created_at >= since))).all():
            if (k := key(created)) in buckets:
                buckets[k]["searches"] += 1
        for created, ok in (
            await s.execute(select(SourceRunLog.created_at, SourceRunLog.ok).where(SourceRunLog.created_at >= since))
        ).all():
            if (k := key(created)) in buckets:
                buckets[k]["requests"] += 1
                buckets[k]["errors"] += 0 if ok else 1
        for (created,) in (
            await s.execute(select(NotificationLog.created_at).where(NotificationLog.created_at >= since))
        ).all():
            if (k := key(created)) in buckets:
                buckets[k]["notifications"] += 1
    return list(buckets.values())


async def source_stats(hours: int = 24) -> dict[str, dict]:
    since = _now() - timedelta(hours=hours)
    rows: dict[str, list] = defaultdict(list)
    async with session_scope() as s:
        for name, ok, ms, offers in (
            await s.execute(
                select(SourceRunLog.source, SourceRunLog.ok, SourceRunLog.elapsed_ms, SourceRunLog.offers).where(
                    SourceRunLog.created_at >= since
                )
            )
        ).all():
            rows[name].append((ok, ms, offers))
    stats = {}
    for name, items in rows.items():
        lat = sorted(ms for _, ms, _ in items)
        oks = [o for ok, _, o in items if ok]
        stats[name] = {
            "requests": len(items),
            "errors": sum(1 for ok, _, _ in items if not ok),
            "error_rate": round(sum(1 for ok, _, _ in items if not ok) / len(items), 3),
            "latency_p50_ms": int(statistics.median(lat)),
            "latency_p95_ms": int(lat[min(len(lat) - 1, int(len(lat) * 0.95))]),
            "avg_offers": round(statistics.fmean(oks), 1) if oks else 0,
        }
    return stats


@router.get("/dashboard/sources")
async def sources_health(hours: int = Query(24, ge=1, le=24 * 30)) -> dict[str, dict]:
    return await source_stats(hours)


@router.get("/dashboard/latency")
async def latency(hours: int = Query(24, ge=1, le=24 * 7)) -> list[dict]:
    """Средняя задержка источников по часам — для графика."""
    since = _now() - timedelta(hours=hours)
    acc: dict[tuple[str, str], list[int]] = defaultdict(list)
    async with session_scope() as s:
        for name, ms, created in (
            await s.execute(
                select(SourceRunLog.source, SourceRunLog.elapsed_ms, SourceRunLog.created_at).where(
                    SourceRunLog.created_at >= since
                )
            )
        ).all():
            hour = as_utc(created).replace(minute=0, second=0, microsecond=0).isoformat()
            acc[(hour, name)].append(ms)
    by_hour: dict[str, dict] = {}
    for (hour, name), values in acc.items():
        by_hour.setdefault(hour, {"ts": hour})[name] = int(statistics.fmean(values))
    return [by_hour[h] for h in sorted(by_hour)]


@router.get("/system")
async def system(minutes: int = Query(60, ge=1, le=24 * 60)) -> dict:
    return {"info": sampler.info(), "series": sampler.series(minutes)}
