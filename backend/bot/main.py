"""Точка входа бота: python -m bot.main

Пока в одном процессе с ботом крутится и проверка подписок; на этапе с очередью
(arq) она переедет в отдельные scheduler/worker.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.handlers import search, start, subs
from bot.middlewares import UserMiddleware
from bot.notifier import BotNotifier
from bot.session import FallbackSession
from common.config import get_settings
from common.metrics import start_metrics_server
from common.telegram_send import telegram_proxy
from scheduler.checker import SubscriptionChecker
from scheduler.health import SourceHealthMonitor
from search.orchestrator import SearchService, sync_source_configs

log = logging.getLogger("aviawatch.bot")


def make_storage(redis_url: str) -> BaseStorage:
    if redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(redis_url)
    return MemoryStorage()


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.bot_token:
        sys.exit("BOT_TOKEN не задан в .env")

    start_metrics_server(settings.metrics_port)
    await sync_source_configs()

    proxy = telegram_proxy(settings.telegram_proxy)
    if proxy:
        log.info("Telegram через прокси %s", proxy.split("@")[-1])
    bot = Bot(
        settings.bot_token,
        # Прокси упал — бот переключится на прямое соединение, а не замолчит
        session=FallbackSession(proxy) if proxy else AiohttpSession(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    notifier = BotNotifier(bot, settings.admin_tg_ids)
    svc = SearchService(on_source_down=notifier.source_down)
    checker = SubscriptionChecker(svc, notifier)
    health = SourceHealthMonitor(svc, notifier.admin_message)

    dp = Dispatcher(storage=make_storage(settings.redis_url))
    dp["svc"] = svc
    dp["checker"] = checker
    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())
    dp.include_routers(start.router, search.router, subs.router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать / главное меню"),
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="help", description="Как это работает"),
        ]
    )

    checker_task = asyncio.create_task(checker.run_forever())
    health_task = asyncio.create_task(health.run_forever())
    me = await bot.get_me()
    log.info("Бот @%s запущен", me.username)
    try:
        await dp.start_polling(bot)
    finally:
        checker_task.cancel()
        health_task.cancel()
        await svc.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
