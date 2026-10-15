from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as TgUser
from sqlalchemy import select

from common import app_settings
from common.config import get_settings
from common.db import session_scope
from common.models import User


class UserMiddleware(BaseMiddleware):
    """Создаёт/обновляет пользователя в БД и кладёт его в data['user']. Блокирует забаненных."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg: TgUser | None = data.get("event_from_user")
        if tg is None or tg.is_bot:
            return await handler(event, data)

        conf = await app_settings.get_all()
        is_admin = tg.id in get_settings().admin_tg_ids
        if conf["maintenance"] and not is_admin:
            text = conf["maintenance_text"]
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
            return None

        async with session_scope() as s:
            user = await s.scalar(select(User).where(User.tg_id == tg.id))
            if user is None:
                user = User(
                    tg_id=tg.id,
                    default_filters=dict(conf["default_filters"] or {}),
                    max_subscriptions=int(conf["default_max_subscriptions"]),
                )
                s.add(user)
            user.username = tg.username
            user.first_name = tg.first_name
            user.last_seen_at = datetime.now(timezone.utc)
        if user.is_blocked:
            if isinstance(event, CallbackQuery):
                await event.answer("Доступ к боту ограничен", show_alert=True)
            return None

        data["user"] = user
        return await handler(event, data)
