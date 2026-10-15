"""Настройки приложения, редактируемые из админки (таблица app_settings).

Бот и планировщик читают их с коротким кэшем — изменения применяются без перезапуска.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select

from common.db import session_scope
from common.models import AppSetting

DEFAULTS: dict[str, Any] = {
    # Тексты бота: пусто — встроенные тексты из bot/texts.py
    "welcome_text": "",
    "help_text": "",
    # Техработы: бот отвечает этим текстом всем, кроме админов
    "maintenance": False,
    "maintenance_text": "🛠 Бот на техническом обслуживании. Скоро вернёмся!",
    # Как часто перепроверять подписки, минуты
    "subscription_check_minutes": 60,
    # Сколько подписок можно новому пользователю
    "default_max_subscriptions": 10,
    # Фильтры по умолчанию для новых пользователей (поверх встроенных)
    "default_filters": {},
    # Пулы прокси для конфигуратора: [{"name": "...", "url": "..."}]
    "proxy_pools": [],
    # Позиции узлов пайплайна на доске конфигуратора
    "board_layout": {},
}

TTL_S = 15
_cache: tuple[float, dict[str, Any]] | None = None


async def get_all(fresh: bool = False) -> dict[str, Any]:
    global _cache
    if not fresh and _cache and time.monotonic() - _cache[0] < TTL_S:
        return _cache[1]
    async with session_scope() as s:
        rows = (await s.scalars(select(AppSetting))).all()
    values = {**DEFAULTS, **{r.key: r.value for r in rows}}
    _cache = (time.monotonic(), values)
    return values


async def get(key: str) -> Any:
    return (await get_all()).get(key, DEFAULTS.get(key))


async def update(values: dict[str, Any]) -> dict[str, Any]:
    global _cache
    unknown = set(values) - set(DEFAULTS)
    if unknown:
        raise KeyError(f"Неизвестные настройки: {', '.join(sorted(unknown))}")
    async with session_scope() as s:
        for key, value in values.items():
            row = await s.get(AppSetting, key)
            if row is None:
                s.add(AppSetting(key=key, value=value))
            else:
                row.value = value
    _cache = None
    return await get_all(fresh=True)


def invalidate() -> None:
    global _cache
    _cache = None
