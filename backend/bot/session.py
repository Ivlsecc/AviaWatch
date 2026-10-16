"""Сессия Bot API с запасным маршрутом.

Бот ходит в api.telegram.org через прокси (VPN-клиент на ПК). Если прокси упал,
бот не должен молчать: переключаемся на прямое соединение, а если отвалится и
оно — обратно на прокси.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aiohttp import ClientConnectorError
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType

log = logging.getLogger(__name__)

# Не чаще раза в столько секунд прыгаем между маршрутами — иначе при полном
# отсутствии сети сессии будут переключаться на каждой ошибке
SWITCH_COOLDOWN_S = 30


def _not_sent(e: TelegramNetworkError) -> bool:
    """Запрос точно не дошёл до Telegram (нет соединения) — его можно безопасно повторить.
    Таймаут не такой: сообщение могло уйти, повтор продублирует его."""
    return isinstance(e.__cause__, ClientConnectorError)  # в т.ч. ClientProxyConnectionError


class FallbackSession(AiohttpSession):
    """Основной маршрут — через прокси; при сетевой ошибке — прямое соединение, и наоборот."""

    def __init__(self, proxy: str, **kwargs: Any) -> None:
        super().__init__(proxy=proxy, **kwargs)
        self.direct = AiohttpSession(**kwargs)
        self.use_direct = False
        self._switched_at = 0.0

    @property
    def route(self) -> str:
        return "напрямую" if self.use_direct else "через прокси"

    async def _request(self, bot: Bot, method: TelegramMethod[TelegramType], timeout: int | None) -> TelegramType:
        if self.use_direct:
            # У прямой сессии свои api/таймаут по умолчанию — берём наши, чтобы вести себя одинаково
            self.direct.api, self.direct.timeout = self.api, self.timeout
            return await self.direct.make_request(bot, method, timeout)
        return await super().make_request(bot, method, timeout)

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramType], timeout: int | None = None
    ) -> TelegramType:
        try:
            return await self._request(bot, method, timeout)
        except TelegramNetworkError as e:
            if time.monotonic() - self._switched_at < SWITCH_COOLDOWN_S:
                raise
            self.use_direct = not self.use_direct
            self._switched_at = time.monotonic()
            log.warning("Telegram недоступен (%s), переключаюсь: %s", e.message, self.route)
            if not _not_sent(e):
                raise
            return await self._request(bot, method, timeout)

    async def close(self) -> None:
        await super().close()
        await self.direct.close()
