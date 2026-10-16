"""Уведомления: список подписок, карточка, настройки. Плюс фильтры из главного меню."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot import keyboards as kb
from bot.callbacks import Flt, Menu, Sub
from bot.filters_logic import _next, toggle
from bot.fmt import dates_label, filters_text, pax_label, rub
from bot.handlers.search import render_results
from bot.states import SubEdit, Wizard
from bot.utils import show
from common.db import session_scope
from common.models import Subscription, User
from scheduler.checker import SubscriptionChecker
from search.filters import FilterSettings
from search.orchestrator import SearchService, as_utc

log = logging.getLogger(__name__)
router = Router(name="subs")

DROP_OPTIONS = [(True, None), (True, 3.0), (True, 5.0), (True, 10.0), (False, None)]
DIGEST_OPTIONS = [None, 3, 6, 12, 24]
QUIET_OPTIONS = [(None, None), (23, 8), (0, 9), (22, 7)]


# ---------- фильтры из главного меню ----------

@router.callback_query(Menu.filter(F.action == "filters"))
async def menu_filters(cb: CallbackQuery, user: User) -> None:
    f = FilterSettings.from_dict(user.default_filters)
    await show(cb, filters_text(f) + "\n\n<i>Применяются ко всем новым поискам.</i>", kb.filters(f, "menu"))


@router.callback_query(Flt.filter(F.ctx == "menu"))
async def menu_filter_toggle(cb: CallbackQuery, callback_data: Flt, user: User) -> None:
    async with session_scope() as s:
        db_user = await s.get(User, user.id)
        f = toggle(FilterSettings.from_dict(db_user.default_filters), callback_data.field)
        db_user.default_filters = f.model_dump()
    await show(cb, filters_text(f) + "\n\n<i>Применяются ко всем новым поискам.</i>", kb.filters(f, "menu"))


# ---------- список и карточка ----------

@router.callback_query(Menu.filter(F.action == "subs"))
async def subs_list(cb: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.clear()
    async with session_scope() as s:
        subs = (
            await s.scalars(select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.id))
        ).all()
    if not subs:
        text = (
            "🔔 <b>Уведомления</b>\n\nВы пока ни за чем не следите.\n"
            "Найдите маршрут и нажмите «🔔 Следить за ценой» под результатами — "
            "я буду проверять цену каждый час и напишу, когда она снизится."
        )
    else:
        text = "🔔 <b>Ваши подписки</b>\n🟢 — активна, ⏸ — на паузе. Нажмите, чтобы настроить."
    await show(cb, text, kb.subs_list(subs))


async def _load(sub_id: int, user: User) -> Subscription | None:
    async with session_scope() as s:
        sub = await s.get(Subscription, sub_id)
        if sub is None or sub.user_id != user.id:
            return None
        return sub


def card_text(sub: Subscription) -> str:
    route = f"{escape(sub.origin_name or sub.origin)} → {escape(sub.destination_name or sub.destination)}"
    checked = as_utc(sub.last_checked_at)
    lines = [
        f"<b>{route}</b>",
        f"📅 {dates_label(sub.date_from, sub.date_to)} · 👤 {pax_label(sub.adults, sub.children, sub.infants)}"
        + (" · только прямые" if sub.direct_only else ""),
        f"💰 Текущий минимум: <b>{rub(sub.last_min_price)}</b>"
        + (f" <i>(проверено {checked:%d.%m %H:%M} UTC)</i>" if checked else ""),
        "",
        "<b>Когда писать:</b>",
        f"🎯 Порог: {rub(sub.threshold_rub) + ' и ниже' if sub.threshold_rub else 'не задан'}",
        f"📉 Снижение: {_drop_label(sub)}",
        f"🆕 Новые рейсы: {'писать, если появится прямой или дешёвый' if sub.notify_new_flights else 'выкл'}",
        f"🗞 Сводка: {f'каждые {sub.digest_every_hours} ч' if sub.digest_every_hours else 'выкл'}",
        f"🌙 Тихие часы: {_quiet_label(sub)}",
        "",
        "Статус: " + ("🟢 активна" if sub.is_active else "⏸ на паузе"),
    ]
    if sub.date_to < date.today():
        lines.append("<i>Даты поездки прошли — подписка больше не проверяется.</i>")
    return "\n".join(lines)


def _drop_label(sub: Subscription) -> str:
    if sub.drop_percent:
        return f"если цена упала на {sub.drop_percent:g}% и больше"
    return "при любом новом минимуме" if sub.notify_new_min else "выкл"


def _quiet_label(sub: Subscription) -> str:
    if sub.quiet_from is None or sub.quiet_to is None:
        return "выкл"
    return f"{sub.quiet_from:02d}:00–{sub.quiet_to:02d}:00 (МСК)"


async def open_card(target: CallbackQuery | Message, sub: Subscription) -> None:
    await show(target, card_text(sub), kb.sub_card(sub))


@router.callback_query(Sub.filter(F.action == "open"))
async def sub_open(cb: CallbackQuery, callback_data: Sub, state: FSMContext, user: User) -> None:
    await state.set_state(None)
    sub = await _load(callback_data.id, user)
    if sub is None:
        await cb.answer("Подписка не найдена", show_alert=True)
        return
    await open_card(cb, sub)


# ---------- настройки ----------

async def _update(sub_id: int, user: User, **changes) -> Subscription | None:
    async with session_scope() as s:
        sub = await s.get(Subscription, sub_id)
        if sub is None or sub.user_id != user.id:
            return None
        for k, v in changes.items():
            setattr(sub, k, v)
        return sub


@router.callback_query(Sub.filter(F.action.in_({"drop", "digest", "quiet", "toggle", "newfl"})))
async def sub_cycle(cb: CallbackQuery, callback_data: Sub, user: User) -> None:
    sub = await _load(callback_data.id, user)
    if sub is None:
        await cb.answer("Подписка не найдена", show_alert=True)
        return
    match callback_data.action:
        case "drop":
            new_min, pct = _next(DROP_OPTIONS, (sub.notify_new_min, sub.drop_percent))
            sub = await _update(sub.id, user, notify_new_min=new_min, drop_percent=pct)
        case "digest":
            sub = await _update(sub.id, user, digest_every_hours=_next(DIGEST_OPTIONS, sub.digest_every_hours))
        case "quiet":
            q_from, q_to = _next(QUIET_OPTIONS, (sub.quiet_from, sub.quiet_to))
            sub = await _update(sub.id, user, quiet_from=q_from, quiet_to=q_to)
        case "toggle":
            sub = await _update(sub.id, user, is_active=not sub.is_active)
        case "newfl":
            sub = await _update(sub.id, user, notify_new_flights=not sub.notify_new_flights)
    await open_card(cb, sub)


@router.callback_query(Sub.filter(F.action == "threshold"))
async def sub_threshold_ask(cb: CallbackQuery, callback_data: Sub, state: FSMContext, user: User) -> None:
    sub = await _load(callback_data.id, user)
    if sub is None:
        await cb.answer("Подписка не найдена", show_alert=True)
        return
    await state.set_state(SubEdit.threshold)
    await state.update_data(sub_id=sub.id)
    hint = f"Сейчас минимум — {rub(sub.last_min_price)}.\n" if sub.last_min_price else ""
    await show(
        cb,
        f"🎯 <b>Порог цены</b>\n{hint}Напишите сумму в рублях за всех пассажиров, например <code>30000</code>.\n"
        "Я напишу, как только цена станет такой или ниже. <code>0</code> — убрать порог.",
        kb.back_to_sub(sub.id),
    )


@router.message(SubEdit.threshold, F.text)
async def sub_threshold_set(message: Message, state: FSMContext, user: User) -> None:
    raw = "".join(ch for ch in message.text if ch.isdigit())
    if not raw:
        await message.answer("Нужно число, например <code>30000</code>")
        return
    value = int(raw)
    sub_id = (await state.get_data()).get("sub_id")
    await state.set_state(None)
    sub = await _update(sub_id, user, threshold_rub=value or None)
    if sub is None:
        await message.answer("Подписка не найдена", reply_markup=kb.home_button())
        return
    await message.answer("✅ Порог сохранён" if value else "Порог убран")
    await open_card(message, sub)


@router.callback_query(Sub.filter(F.action == "delete"))
async def sub_delete(cb: CallbackQuery, callback_data: Sub) -> None:
    await show(cb, "Удалить подписку? Уведомления по этому маршруту прекратятся.", kb.confirm_delete(callback_data.id))


@router.callback_query(Sub.filter(F.action == "delete_yes"))
async def sub_delete_yes(cb: CallbackQuery, callback_data: Sub, state: FSMContext, user: User) -> None:
    async with session_scope() as s:
        sub = await s.get(Subscription, callback_data.id)
        if sub is not None and sub.user_id == user.id:
            await s.delete(sub)
    await cb.answer("Подписка удалена")
    await subs_list(cb, state, user)


@router.callback_query(Sub.filter(F.action == "check"))
async def sub_check(cb: CallbackQuery, callback_data: Sub, user: User, checker: SubscriptionChecker) -> None:
    async with session_scope() as s:
        sub = await s.get(Subscription, callback_data.id)
        if sub is None or sub.user_id != user.id:
            await cb.answer("Подписка не найдена", show_alert=True)
            return
        await s.refresh(sub, ["user"])
    await cb.answer("🔍 Проверяю, пришлю результат отдельным сообщением")
    asyncio.create_task(_check_and_log(checker, sub))


async def _check_and_log(checker: SubscriptionChecker, sub: Subscription) -> None:
    try:
        await checker.check(sub, force_send=True)
    except Exception:  # noqa: BLE001
        log.exception("manual check failed")


@router.callback_query(Sub.filter(F.action == "results"))
async def sub_results(cb: CallbackQuery, callback_data: Sub, state: FSMContext, user: User, svc: SearchService) -> None:
    sub = await _load(callback_data.id, user)
    if sub is None:
        await cb.answer("Подписка не найдена", show_alert=True)
        return
    today = date.today()
    await state.set_state(Wizard.results)
    await state.set_data(
        {
            "origins": sub.origins,
            "destinations": sub.destinations,
            "origin_names": [n for n in sub.origin_name.split(", ") if n] or sub.origins,
            "destination_names": [n for n in sub.destination_name.split(", ") if n] or sub.destinations,
            "date_from": max(sub.date_from, today).isoformat(),
            "date_to": sub.date_to.isoformat(),
            "adults": sub.adults,
            "children": sub.children,
            "infants": sub.infants,
            "direct_only": sub.direct_only,
            "filters": FilterSettings.from_dict(sub.filters).model_dump(),
            "subscribed_id": sub.id,
        }
    )
    # Уведомление не трогаем — результаты отдельным сообщением
    await cb.answer()
    msg = await cb.message.answer("⏳ Ищу билеты…")
    await render_results(cb, state, svc, user, page=0, use_cache=True, loading=False, target=msg)
