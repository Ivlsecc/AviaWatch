from __future__ import annotations

import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from bot import keyboards as kb
from bot.fmt import dates_label, offer_line, rub
from common.db import session_scope
from common.models import Subscription, User
from scheduler.rules import Decision
from search.orchestrator import SearchResult
from search.recommend import Recommendation

log = logging.getLogger(__name__)

HEADERS = {
    "threshold": "🎯 <b>Цена ниже вашего порога!</b>",
    "drop": "📉 <b>Цена снизилась</b>",
    "digest": "🗞 <b>Сводка по маршруту</b>",
    "manual": "🔍 <b>Текущие цены</b>",
}


def alert_text(
    sub: Subscription, result: SearchResult, decision: Decision, prev: int | None, rec: Recommendation | None = None
) -> str:
    head = next((HEADERS[e] for e in ("threshold", "drop", "manual", "digest") if e in decision.events), HEADERS["digest"])
    route = f"{escape(sub.origin_name or sub.origin)} → {escape(sub.destination_name or sub.destination)}"
    price = result.offers[0].price_rub if result.offers else None
    line = f"Сейчас от <b>{rub(price)}</b>"
    if prev and price and price != prev:
        pct = (price - prev) / prev * 100
        line += f" (было {rub(prev)}, {'−' if pct < 0 else '+'}{abs(pct):.1f}%)"
    if "threshold" in decision.events and sub.threshold_rub:
        line += f"\nВаш порог: {rub(sub.threshold_rub)}"
    if rec:
        line += f"\n{rec.emoji} <b>{rec.title}</b>" + (f": {escape(rec.reasons[0])}" if rec.reasons else "")
    offers = "\n\n".join(offer_line(i + 1, o) for i, o in enumerate(result.offers[:3]))
    return f"{head}\n<b>{route}</b> · {dates_label(sub.date_from, sub.date_to)}\n{line}\n\n{offers or 'Подходящих рейсов сейчас нет.'}"


class BotNotifier:
    def __init__(self, bot: Bot, admin_ids: list[int]) -> None:
        self.bot = bot
        self.admin_ids = admin_ids

    async def notify(
        self,
        sub: Subscription,
        user: User,
        result: SearchResult,
        decision: Decision,
        prev_price: int | None,
        rec: Recommendation | None = None,
    ) -> bool:
        try:
            text = alert_text(sub, result, decision, prev_price, rec)
            await self.bot.send_message(user.tg_id, text, reply_markup=kb.alert(sub.id))
            return True
        except TelegramForbiddenError:
            # Пользователь заблокировал бота — ставим его подписки на паузу
            log.info("user %s blocked the bot, pausing subscriptions", user.tg_id)
            async with session_scope() as s:
                db_sub = await s.get(Subscription, sub.id)
                if db_sub:
                    db_sub.is_active = False
            return False
        except Exception:  # noqa: BLE001
            log.exception("send alert failed")
            return False

    async def source_down(self, name: str, error: str) -> None:
        text = f"🔴 Источник <b>{escape(name)}</b> временно отключён после серии ошибок.\n<code>{escape(error[:500])}</code>"
        for admin in self.admin_ids:
            try:
                await self.bot.send_message(admin, text)
            except Exception:  # noqa: BLE001
                log.exception("admin alert failed")
