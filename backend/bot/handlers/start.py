from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from bot import keyboards as kb
from bot import texts
from bot.callbacks import Cal, Menu
from bot.fmt import source_title
from bot.utils import show
from common import app_settings
from common.config import get_settings
from common.db import session_scope
from common.models import SearchLog, SourceConfig, Subscription, User
from search.orchestrator import as_utc

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = f", {escape(message.from_user.first_name)}" if message.from_user.first_name else ""
    template = (await app_settings.get("welcome_text")) or texts.WELCOME
    try:
        text = template.format(name=name)
    except (KeyError, IndexError, ValueError):  # в тексте из админки могут быть лишние {}
        text = template
    await message.answer(text, reply_markup=kb.main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.MENU, reply_markup=kb.main_menu())


@router.callback_query(Menu.filter(F.action == "home"))
async def cb_home(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show(cb, texts.MENU, kb.main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer((await app_settings.get("help_text")) or texts.HELP, reply_markup=kb.home_button())


@router.callback_query(Menu.filter(F.action == "help"))
async def cb_help(cb: CallbackQuery) -> None:
    await show(cb, (await app_settings.get("help_text")) or texts.HELP, kb.home_button())


@router.callback_query(Cal.filter(F.action == "noop"))
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if message.from_user.id not in get_settings().admin_tg_ids:
        return
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    async with session_scope() as s:
        users = await s.scalar(select(func.count(User.id)))
        active_users = await s.scalar(select(func.count(User.id)).where(User.last_seen_at >= day_ago))
        subs = await s.scalar(select(func.count(Subscription.id)).where(Subscription.is_active.is_(True)))
        searches = await s.scalar(select(func.count(SearchLog.id)).where(SearchLog.created_at >= day_ago))
        sources = (await s.scalars(select(SourceConfig).order_by(SourceConfig.priority))).all()

    now = datetime.now(timezone.utc)
    lines = [
        "📈 <b>Статистика</b>",
        f"Пользователей: {users} (активны за сутки: {active_users})",
        f"Активных подписок: {subs}",
        f"Поисков за сутки: {searches}",
        "",
        "<b>Источники:</b>",
    ]
    for src in sources:
        until = as_utc(src.disabled_until)
        if not src.enabled:
            mark = "⚪ выключен"
        elif until and until > now:
            mark = f"🔴 отключён до {until:%H:%M} UTC"
        else:
            mark = "🟢 работает"
        line = f"{escape(source_title(src.name))}: {mark}"
        if src.last_error:
            line += f"\n    <i>последняя ошибка: {escape(src.last_error[:120])}</i>"
        lines.append(line)
    await message.answer("\n".join(lines))
