"""Источники: список с состоянием, правка конфига, тестовый запуск, сброс circuit breaker, доска."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.auth import require_admin
from api.dashboard import source_stats
from common import app_settings
from common.db import session_scope
from common.models import SourceConfig
from search.orchestrator import SearchService, as_utc
from search.runner import RunSettings
from sources.base import SearchQuery
from sources.registry import all_sources, get_source

router = APIRouter(prefix="/api", tags=["sources"], dependencies=[Depends(require_admin)])


def _status(cfg: SourceConfig) -> str:
    if not cfg.enabled:
        return "disabled"
    if (u := as_utc(cfg.disabled_until)) and u > datetime.now(timezone.utc):
        return "down"
    if cfg.consecutive_failures:
        return "degraded"
    return "ok"


def _serialize(cfg: SourceConfig, stats: dict | None = None) -> dict[str, Any]:
    cls = all_sources().get(cfg.name)
    return {
        "name": cfg.name,
        "title": cls.title if cls else cfg.name,
        "method": cls.method if cls else "?",
        "supports_calendar": bool(cls and cls.supports_calendar),
        "param_schema": cls.param_schema if cls else {},
        "registered": cls is not None,
        "status": _status(cfg),
        "enabled": cfg.enabled,
        "priority": cfg.priority,
        "interval_minutes": cfg.interval_minutes,
        "rate_limit_per_min": cfg.rate_limit_per_min,
        "timeout_s": cfg.timeout_s,
        "retries": cfg.retries,
        "proxy": cfg.proxy,
        "params": cfg.params or {},
        "board_x": cfg.board_x,
        "board_y": cfg.board_y,
        "consecutive_failures": cfg.consecutive_failures,
        "disabled_until": as_utc(cfg.disabled_until).isoformat() if cfg.disabled_until else None,
        "last_success_at": as_utc(cfg.last_success_at).isoformat() if cfg.last_success_at else None,
        "last_error": cfg.last_error,
        "last_error_at": as_utc(cfg.last_error_at).isoformat() if cfg.last_error_at else None,
        "stats_24h": stats or {"requests": 0, "errors": 0, "error_rate": 0, "latency_p50_ms": 0, "latency_p95_ms": 0, "avg_offers": 0},
    }


@router.get("/sources")
async def list_sources() -> list[dict]:
    stats = await source_stats(24)
    async with session_scope() as s:
        configs = (await s.scalars(select(SourceConfig).order_by(SourceConfig.priority, SourceConfig.name))).all()
    return [_serialize(c, stats.get(c.name)) for c in configs if c.name in all_sources()]


class SourcePatch(BaseModel):
    enabled: bool | None = None
    priority: int | None = None
    interval_minutes: int | None = Field(None, ge=1)
    rate_limit_per_min: int | None = Field(None, ge=0)
    timeout_s: float | None = Field(None, gt=0, le=300)
    retries: int | None = Field(None, ge=0, le=5)
    proxy: str | None = None
    params: dict[str, Any] | None = None
    board_x: float | None = None
    board_y: float | None = None


@router.patch("/sources/{name}")
async def patch_source(name: str, body: SourcePatch) -> dict:
    changes = body.model_dump(exclude_unset=True)
    async with session_scope() as s:
        cfg = await s.get(SourceConfig, name)
        if cfg is None:
            raise HTTPException(404, "Источник не найден")
        for k, v in changes.items():
            if k == "proxy" and v is not None and not v.strip():
                v = None  # пустая строка = глобальный прокси
            setattr(cfg, k, v)
    stats = await source_stats(24)
    return _serialize(cfg, stats.get(name))


@router.post("/sources/{name}/reset")
async def reset_source(name: str) -> dict:
    async with session_scope() as s:
        cfg = await s.get(SourceConfig, name)
        if cfg is None:
            raise HTTPException(404, "Источник не найден")
        cfg.consecutive_failures = 0
        cfg.disabled_until = None
    return _serialize(cfg)


class TestIn(BaseModel):
    origin: str = "HRG"
    destination: str = "MOW"
    date: date
    date_to: date | None = None
    adults: int = 1


@router.post("/sources/{name}/test")
async def test_source(name: str, body: TestIn, request: Request) -> dict:
    """Пробный запрос через источник с его текущими настройками (даже если источник выключен)."""
    svc: SearchService = request.app.state.svc
    async with session_scope() as s:
        cfg = await s.get(SourceConfig, name)
    if cfg is None or name not in all_sources():
        raise HTTPException(404, "Источник не найден")
    query = SearchQuery(
        origin=body.origin.upper(), destination=body.destination.upper(),
        date_from=body.date, date_to=body.date_to or body.date, adults=body.adults,
    )
    rs: RunSettings = svc._run_settings(cfg)
    rs.retries = 0
    res = await svc.runner.run(get_source(name), query, rs)
    offers = sorted(res.offers, key=lambda o: o.price_rub)
    return {
        "ok": res.ok,
        "error": res.error,
        "elapsed_s": round(res.elapsed_s, 2),
        "offers": len(offers),
        "sample": [
            {
                "price_rub": o.price_rub,
                "departure_at": o.departure_at.isoformat(),
                "time_known": o.time_known,
                "route": " → ".join(o.route_airports or [o.origin_airport, o.destination_airport]),
                "flights": o.flight_numbers,
                "transfers": o.transfers,
                "self_transfer": o.self_transfer,
                "link": o.link,
                "note": o.note,
            }
            for o in offers[:15]
        ],
    }


class BoardIn(BaseModel):
    layout: dict[str, dict[str, float]] = {}
    proxy_pools: list[dict[str, str]] | None = None


@router.get("/board")
async def get_board() -> dict:
    conf = await app_settings.get_all(fresh=True)
    return {"layout": conf["board_layout"], "proxy_pools": conf["proxy_pools"]}


@router.put("/board")
async def put_board(body: BoardIn) -> dict:
    changes: dict[str, Any] = {"board_layout": body.layout}
    if body.proxy_pools is not None:
        for p in body.proxy_pools:
            if not p.get("name") or not p.get("url"):
                raise HTTPException(422, "У пула прокси нужны name и url")
        changes["proxy_pools"] = body.proxy_pools
    conf = await app_settings.update(changes)
    return {"layout": conf["board_layout"], "proxy_pools": conf["proxy_pools"]}
