"""Пользователи, подписки, рассылка, настройки бота, логи."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from api.auth import require_admin
from common import app_settings
from common.db import session_scope
from common.models import NotificationLog, SearchLog, SourceRunLog, Subscription, User
from common.telegram_send import TelegramSender
from search.orchestrator import as_utc

router = APIRouter(prefix="/api", tags=["users"], dependencies=[Depends(require_admin)])


def _iso(dt: datetime | None) -> str | None:
    return as_utc(dt).isoformat() if dt else None


def _user(u: User, subs: int = 0, searches: int = 0) -> dict:
    return {
        "id": u.id, "tg_id": u.tg_id, "username": u.username, "first_name": u.first_name,
        "is_blocked": u.is_blocked, "max_subscriptions": u.max_subscriptions,
        "created_at": _iso(u.created_at), "last_seen_at": _iso(u.last_seen_at),
        "subscriptions": subs, "searches": searches,
    }


def _sub(s: Subscription) -> dict:
    return {
        "id": s.id, "user_id": s.user_id, "origin": s.origin, "destination": s.destination,
        "origin_name": s.origin_name, "destination_name": s.destination_name,
        "date_from": s.date_from.isoformat(), "date_to": s.date_to.isoformat(),
        "adults": s.adults, "children": s.children, "infants": s.infants, "direct_only": s.direct_only,
        "threshold_rub": s.threshold_rub, "notify_new_min": s.notify_new_min, "drop_percent": s.drop_percent,
        "digest_every_hours": s.digest_every_hours, "quiet_from": s.quiet_from, "quiet_to": s.quiet_to,
        "is_active": s.is_active, "last_min_price": s.last_min_price,
        "last_checked_at": _iso(s.last_checked_at), "last_notified_at": _iso(s.last_notified_at),
        "created_at": _iso(s.created_at),
    }


@router.get("/users")
async def list_users(q: str = "", page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)) -> dict:
    async with session_scope() as s:
        stmt = select(User)
        if q.strip():
            like = f"%{q.strip()}%"
            conds = [User.username.ilike(like), User.first_name.ilike(like)]
            if q.strip().isdigit():
                conds.append(User.tg_id == int(q.strip()))
            stmt = stmt.where(or_(*conds))
        total = await s.scalar(select(func.count()).select_from(stmt.subquery()))
        users = (await s.scalars(stmt.order_by(User.last_seen_at.desc()).offset((page - 1) * size).limit(size))).all()
        ids = [u.id for u in users]
        subs = dict((await s.execute(
            select(Subscription.user_id, func.count(Subscription.id)).where(Subscription.user_id.in_(ids)).group_by(Subscription.user_id)
        )).all()) if ids else {}
        searches = dict((await s.execute(
            select(SearchLog.user_id, func.count(SearchLog.id)).where(SearchLog.user_id.in_(ids)).group_by(SearchLog.user_id)
        )).all()) if ids else {}
    return {"total": total, "items": [_user(u, subs.get(u.id, 0), searches.get(u.id, 0)) for u in users]}


@router.get("/users/{user_id}")
async def get_user(user_id: int) -> dict:
    async with session_scope() as s:
        u = await s.get(User, user_id)
        if u is None:
            raise HTTPException(404, "Пользователь не найден")
        subs = (await s.scalars(select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.id))).all()
        recent = (await s.scalars(
            select(SearchLog).where(SearchLog.user_id == user_id).order_by(SearchLog.created_at.desc()).limit(30)
        )).all()
        notes = (await s.scalars(
            select(NotificationLog).where(NotificationLog.user_id == user_id).order_by(NotificationLog.created_at.desc()).limit(30)
        )).all()
    return {
        "user": _user(u, len(subs), len(recent)),
        "subscriptions": [_sub(x) for x in subs],
        "searches": [
            {"route": f"{x.origin}→{x.destination}", "dates": f"{x.date_from}…{x.date_to}", "results": x.results,
             "min_price": x.min_price, "ms": x.duration_ms, "cached": x.from_cache, "at": _iso(x.created_at)}
            for x in recent
        ],
        "notifications": [{"kind": n.kind, "ok": n.ok, "price": n.price, "at": _iso(n.created_at)} for n in notes],
    }


class UserPatch(BaseModel):
    is_blocked: bool | None = None
    max_subscriptions: int | None = Field(None, ge=0, le=1000)


@router.patch("/users/{user_id}")
async def patch_user(user_id: int, body: UserPatch) -> dict:
    async with session_scope() as s:
        u = await s.get(User, user_id)
        if u is None:
            raise HTTPException(404, "Пользователь не найден")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(u, k, v)
    return _user(u)


class SubPatch(BaseModel):
    is_active: bool | None = None
    threshold_rub: int | None = None


@router.patch("/subscriptions/{sub_id}")
async def patch_sub(sub_id: int, body: SubPatch) -> dict:
    async with session_scope() as s:
        sub = await s.get(Subscription, sub_id)
        if sub is None:
            raise HTTPException(404, "Подписка не найдена")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(sub, k, v)
    return _sub(sub)


@router.delete("/subscriptions/{sub_id}")
async def delete_sub(sub_id: int) -> dict:
    async with session_scope() as s:
        sub = await s.get(Subscription, sub_id)
        if sub is None:
            raise HTTPException(404, "Подписка не найдена")
        await s.delete(sub)
    return {"ok": True}


@router.get("/subscriptions")
async def list_subs(active: bool | None = None, limit: int = Query(200, le=1000)) -> list[dict]:
    async with session_scope() as s:
        stmt = select(Subscription).order_by(Subscription.created_at.desc()).limit(limit)
        if active is not None:
            stmt = stmt.where(Subscription.is_active.is_(active))
        return [_sub(x) for x in (await s.scalars(stmt)).all()]


# ---------- настройки бота ----------

@router.get("/settings")
async def get_settings_api() -> dict:
    return await app_settings.get_all(fresh=True)


@router.put("/settings")
async def put_settings(body: dict[str, Any]) -> dict:
    try:
        return await app_settings.update(body)
    except KeyError as e:
        raise HTTPException(422, str(e)) from None


# ---------- рассылка ----------

_JOBS: dict[str, dict] = {}


class BroadcastIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    only_active_days: int | None = Field(None, ge=1, description="Только тем, кто заходил за N дней")
    dry_run: bool = False


@router.post("/broadcast")
async def broadcast(body: BroadcastIn) -> dict:
    async with session_scope() as s:
        stmt = select(User).where(User.is_blocked.is_(False))
        if body.only_active_days:
            stmt = stmt.where(User.last_seen_at >= datetime.now(timezone.utc) - timedelta(days=body.only_active_days))
        users = (await s.scalars(stmt)).all()
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "total": len(users), "sent": 0, "failed": 0, "errors": [], "done": body.dry_run, "dry_run": body.dry_run}
    _JOBS[job_id] = job
    if not body.dry_run:
        asyncio.create_task(_run_broadcast(job, [(u.id, u.tg_id) for u in users], body.text))
    return job


async def _run_broadcast(job: dict, recipients: list[tuple[int, int]], text: str) -> None:
    sender = TelegramSender()
    try:
        for user_id, tg_id in recipients:
            try:
                ok, err = await sender.send(tg_id, text)
            except Exception as e:  # noqa: BLE001
                ok, err = False, str(e)
            job["sent" if ok else "failed"] += 1
            if err and len(job["errors"]) < 20:
                job["errors"].append({"tg_id": tg_id, "error": err})
            async with session_scope() as s:
                s.add(NotificationLog(user_id=user_id, kind="broadcast", ok=ok))
            await asyncio.sleep(0.05)  # ~20 сообщений в секунду — в пределах лимитов Telegram
    finally:
        job["done"] = True
        await sender.close()


@router.get("/broadcast/{job_id}")
async def broadcast_status(job_id: str) -> dict:
    if job_id not in _JOBS:
        raise HTTPException(404, "Рассылка не найдена")
    return _JOBS[job_id]


# ---------- логи ----------

@router.get("/logs/errors")
async def source_errors(limit: int = Query(100, le=500), source: str | None = None) -> list[dict]:
    async with session_scope() as s:
        stmt = select(SourceRunLog).where(SourceRunLog.ok.is_(False)).order_by(SourceRunLog.created_at.desc()).limit(limit)
        if source:
            stmt = stmt.where(SourceRunLog.source == source)
        rows = (await s.scalars(stmt)).all()
    return [{"source": r.source, "error": r.error, "route": r.route, "ms": r.elapsed_ms, "at": _iso(r.created_at)} for r in rows]


@router.get("/logs/searches")
async def recent_searches(limit: int = Query(100, le=500)) -> list[dict]:
    async with session_scope() as s:
        rows = (await s.execute(
            select(SearchLog, User.username, User.first_name).outerjoin(User, User.id == SearchLog.user_id)
            .order_by(SearchLog.created_at.desc()).limit(limit)
        )).all()
    return [
        {"route": f"{x.origin}→{x.destination}", "dates": f"{x.date_from}…{x.date_to}", "results": x.results,
         "min_price": x.min_price, "ms": x.duration_ms, "cached": x.from_cache, "at": _iso(x.created_at),
         "user": uname or fname or (f"#{x.user_id}" if x.user_id else "система")}
        for x, uname, fname in rows
    ]
