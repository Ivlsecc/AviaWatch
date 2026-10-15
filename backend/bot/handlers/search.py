"""Мастер «Найти маршрут» и выдача результатов."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from bot import keyboards as kb
from bot import texts
from bot.callbacks import Cal, Flt, Menu, Pax, PlacePick, Res, Wiz
from bot.filters_logic import toggle
from bot.fmt import PAGE_SIZE, dates_label, filters_text, layover_label, pax_label, results_text, route_title
from bot.states import Wizard
from bot.utils import safe_edit, show
from common.db import session_scope
from common.models import Subscription, User
from common.places import Place, find_places
from search.analytics import route_price_stats
from search.filters import FilterSettings
from search.history import price_trend
from search.orchestrator import SearchService
from search.recommend import recommend
from search.routes import RouteRequest, search_route

log = logging.getLogger(__name__)
router = Router(name="search")

MAX_RANGE_DAYS = 60
STEP_KEYS = {"from": ("origins", "origin_names"), "to": ("destinations", "destination_names")}


# ---------- старт и выбор мест ----------

@router.callback_query(Menu.filter(F.action == "search"))
async def start_wizard(cb: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.clear()
    await state.set_data(
        {
            "origins": [], "origin_names": [], "destinations": [], "destination_names": [],
            "adults": 1, "children": 0, "infants": 0, "direct_only": False,
            "filters": FilterSettings.from_dict(user.default_filters).model_dump(),
        }
    )
    await ask_place(cb, state, "from")


async def ask_place(target: Message | CallbackQuery, state: FSMContext, step: str) -> None:
    await state.set_state(Wizard.origin if step == "from" else Wizard.destination)
    data = await state.get_data()
    codes, names = (data[k] for k in STEP_KEYS[step])
    if codes:
        await show(target, _selected_text(step, names, codes), kb.place_selected(step))
    else:
        text = texts.ASK_ORIGIN if step == "from" else texts.ASK_DESTINATION
        await show(target, text, InlineKeyboardMarkup(inline_keyboard=[kb.wizard_nav(step)]))


def _selected_text(step: str, names: list[str], codes: list[str]) -> str:
    title = "🛫 Откуда" if step == "from" else "🛬 Куда"
    places = ", ".join(f"{escape(n)} ({c})" for n, c in zip(names, codes))
    return (
        f"{title}: <b>{places}</b>\n\n"
        "Можно добавить ещё город — просто напишите его название "
        "(например, если подходит и Хургада, и Шарм). Или нажмите «Далее»."
    )


@router.message(Wizard.origin, F.text)
@router.message(Wizard.destination, F.text)
async def place_text(message: Message, state: FSMContext) -> None:
    step = "from" if await state.get_state() == Wizard.origin.state else "to"
    try:
        found = await find_places(message.text)
    except Exception:  # noqa: BLE001
        log.exception("autocomplete failed")
        found = []
    if not found:
        await message.answer(texts.NOT_FOUND)
        return
    await state.update_data(places=[p.model_dump() for p in found])
    data = await state.get_data()
    await message.answer("Выберите вариант 👇", reply_markup=kb.places(step, found, bool(data[STEP_KEYS[step][0]])))


@router.callback_query(PlacePick.filter())
async def place_pick(cb: CallbackQuery, callback_data: PlacePick, state: FSMContext) -> None:
    data = await state.get_data()
    places = data.get("places") or []
    if callback_data.idx >= len(places):
        await cb.answer(texts.SESSION_EXPIRED, show_alert=True)
        return
    place = Place.model_validate(places[callback_data.idx])
    codes_key, names_key = STEP_KEYS[callback_data.step]
    codes, names = list(data[codes_key]), list(data[names_key])
    if place.code not in codes:
        if len(codes) >= 3:
            await cb.answer("Не больше 3 городов", show_alert=True)
            return
        codes.append(place.code)
        names.append(place.name)
    await state.update_data({codes_key: codes, names_key: names})
    await show(cb, _selected_text(callback_data.step, names, codes), kb.place_selected(callback_data.step))


# ---------- навигация мастера ----------

@router.callback_query(Wiz.filter(F.action == "next"))
async def wiz_next(cb: CallbackQuery, callback_data: Wiz, state: FSMContext) -> None:
    match callback_data.step:
        case "from":
            await ask_place(cb, state, "to")
        case "to":
            await ask_dates(cb, state)
        case "pax":
            await show_summary(cb, state)


@router.callback_query(Wiz.filter(F.action == "back"))
async def wiz_back(cb: CallbackQuery, callback_data: Wiz, state: FSMContext) -> None:
    match callback_data.step:
        case "from":
            await state.clear()
            await show(cb, texts.MENU, kb.main_menu())
        case "to":
            await ask_place(cb, state, "from")
        case "dates":
            await ask_place(cb, state, "to")
        case "pax":
            await ask_dates(cb, state)
        case "summary" | "results":
            if not (await state.get_data()).get("origins"):
                await show(cb, texts.SESSION_EXPIRED, kb.main_menu())
                return
            if callback_data.step == "summary":
                await ask_pax(cb, state)
            else:
                await show_summary(cb, state)


@router.callback_query(Wiz.filter(F.action == "reset"))
async def wiz_reset(cb: CallbackQuery, callback_data: Wiz, state: FSMContext) -> None:
    codes_key, names_key = STEP_KEYS[callback_data.step]
    await state.update_data({codes_key: [], names_key: []})
    await ask_place(cb, state, callback_data.step)


# ---------- даты ----------

async def ask_dates(target: CallbackQuery, state: FSMContext, year: int = 0, month: int = 0) -> None:
    data = await state.get_data()
    if not data.get("destinations"):
        await target.answer("Сначала выберите, куда летим", show_alert=True)
        return
    await state.set_state(Wizard.dates)
    today = date.today()
    start = date.fromisoformat(data["cal_start"]) if data.get("cal_start") else None
    if not year:
        anchor = start or (date.fromisoformat(data["date_from"]) if data.get("date_from") else today)
        year, month = anchor.year, anchor.month
    text = texts.ASK_DATES
    if start:
        text += f"\n\nНачало: <b>{start:%d.%m}</b>. Выберите последнюю дату или нажмите «Только {start:%d.%m}»."
    await show(target, text, kb.calendar_kb(year, month, today, start))


@router.callback_query(Cal.filter(F.action == "nav"))
async def cal_nav(cb: CallbackQuery, callback_data: Cal, state: FSMContext) -> None:
    await ask_dates(cb, state, callback_data.y, callback_data.m)


@router.callback_query(Cal.filter(F.action == "day"))
async def cal_day(cb: CallbackQuery, callback_data: Cal, state: FSMContext) -> None:
    picked = date(callback_data.y, callback_data.m, callback_data.d)
    data = await state.get_data()
    if not data.get("cal_start"):
        await state.update_data(cal_start=picked.isoformat())
        await ask_dates(cb, state, picked.year, picked.month)
        return
    start = date.fromisoformat(data["cal_start"])
    a, b = sorted((start, picked))
    if (b - a).days > MAX_RANGE_DAYS:
        await cb.answer(f"Диапазон не больше {MAX_RANGE_DAYS} дней", show_alert=True)
        return
    await state.update_data(date_from=a.isoformat(), date_to=b.isoformat(), cal_start=None)
    await ask_pax(cb, state)


@router.callback_query(Cal.filter(F.action == "single"))
async def cal_single(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("cal_start"):
        await cb.answer()
        return
    await state.update_data(date_from=data["cal_start"], date_to=data["cal_start"], cal_start=None)
    await ask_pax(cb, state)


# ---------- пассажиры ----------

async def ask_pax(target: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Wizard.passengers)
    data = await state.get_data()
    await show(target, texts.ASK_PAX, kb.passengers(data["adults"], data["children"], data["infants"]))


@router.callback_query(Pax.filter())
async def pax_change(cb: CallbackQuery, callback_data: Pax, state: FSMContext) -> None:
    data = await state.get_data()
    a, c, i = data["adults"], data["children"], data["infants"]
    match callback_data.kind:
        case "adults":
            a = min(max(a + callback_data.delta, 1), 9)
        case "children":
            c = min(max(c + callback_data.delta, 0), 8)
        case "infants":
            i = max(i + callback_data.delta, 0)
    i = min(i, a)  # младенец без места — один на взрослого
    if a + c > 9:
        await cb.answer("Не больше 9 пассажиров с местом")
        return
    await state.update_data(adults=a, children=c, infants=i)
    await ask_pax(cb, state)


# ---------- сводка и фильтры ----------

def request_from_data(data: dict) -> RouteRequest:
    return RouteRequest(
        origins=data["origins"],
        destinations=data["destinations"],
        origin_names=data["origin_names"],
        destination_names=data["destination_names"],
        date_from=date.fromisoformat(data["date_from"]),
        date_to=date.fromisoformat(data["date_to"]),
        adults=data["adults"],
        children=data["children"],
        infants=data["infants"],
        direct_only=data["direct_only"],
    )


async def show_summary(target: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("date_from"):
        await target.answer("Сначала выберите даты", show_alert=True)
        return
    await state.set_state(Wizard.summary)
    req = request_from_data(data)
    f = FilterSettings.from_dict(data["filters"])
    text = (
        "🧾 <b>Проверьте поиск</b>\n\n"
        f"<b>{route_title(req)}</b>\n"
        f"📅 {dates_label(req.date_from, req.date_to)}\n"
        f"👤 {pax_label(req.adults, req.children, req.infants)}\n"
        f"⚙️ пересадок ≤ {0 if req.direct_only else f.max_transfers}, стыковка {layover_label(f)}"
        + (", без смены аэропорта" if f.exclude_airport_change else "")
    )
    await show(target, text, kb.summary(req.direct_only))


@router.callback_query(Wiz.filter(F.action == "direct"))
async def wiz_direct(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(direct_only=not data.get("direct_only", False))
    await show_summary(cb, state)


@router.callback_query(Wiz.filter(F.action == "filters"))
async def wiz_filters(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Wizard.filters)
    f = FilterSettings.from_dict((await state.get_data())["filters"])
    await show(cb, filters_text(f), kb.filters(f, "wiz"))


@router.callback_query(Flt.filter(F.ctx == "wiz"))
async def wiz_filter_toggle(cb: CallbackQuery, callback_data: Flt, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    if "filters" not in data:
        await show(cb, texts.SESSION_EXPIRED, kb.main_menu())
        return
    f = FilterSettings.from_dict(data["filters"])
    if callback_data.field == "done":
        await show_summary(cb, state)
        return
    if callback_data.field == "save":
        async with session_scope() as s:
            db_user = await s.get(User, user.id)
            db_user.default_filters = f.model_dump()
        await cb.answer("Сохранено: эти фильтры будут применяться ко всем новым поискам", show_alert=True)
        return
    f = toggle(f, callback_data.field)
    await state.update_data(filters=f.model_dump())
    await show(cb, filters_text(f), kb.filters(f, "wiz"))


# ---------- поиск и выдача ----------

@router.callback_query(Wiz.filter(F.action == "search"))
async def wiz_search(cb: CallbackQuery, state: FSMContext, svc: SearchService, user: User) -> None:
    await render_results(cb, state, svc, user, page=0, use_cache=True, loading=True)


@router.callback_query(Res.filter(F.action.in_({"page", "refresh"})))
async def res_page(cb: CallbackQuery, callback_data: Res, state: FSMContext, svc: SearchService, user: User) -> None:
    refresh = callback_data.action == "refresh"
    await render_results(cb, state, svc, user, page=callback_data.page, use_cache=not refresh, loading=refresh)


async def render_results(
    cb: CallbackQuery,
    state: FSMContext,
    svc: SearchService,
    user: User,
    page: int,
    use_cache: bool,
    loading: bool,
    target: Message | None = None,
) -> None:
    """Рисует выдачу в сообщении с кнопками (или в target, если передан)."""
    data = await state.get_data()
    if not data.get("date_from"):
        await show(cb, texts.SESSION_EXPIRED, kb.main_menu())
        return
    req = request_from_data(data)
    filters = FilterSettings.from_dict(data["filters"])
    if target is None:
        target = cb.message
        if loading:
            await show(cb, texts.SEARCHING)
        else:
            await cb.answer()

    try:
        result, stats = await asyncio.gather(
            search_route(svc, req, filters, user.id, use_cache=use_cache),
            route_price_stats(svc, req.origins, req.destinations),
        )
    except Exception:  # noqa: BLE001 — пользователь должен увидеть ответ, а не вечное «Ищу…»
        log.exception("search failed")
        await safe_edit(target, texts.SEARCH_FAILED, kb.home_button())
        return

    trend, rec = None, None
    try:
        trend = await price_trend(req.origins, req.destinations, req.date_from, req.date_to)
        best = result.offers[0] if result.offers else None
        rec = recommend(
            best.price_rub // max(req.passengers, 1) if best else None,
            stats,
            trend,
            best.departure_date if best else req.date_from,
        )
    except Exception:  # noqa: BLE001 — без рекомендации выдача всё равно полезна
        log.exception("recommendation failed")

    await state.set_state(Wizard.results)
    page = min(page, max((len(result.offers) - 1) // PAGE_SIZE, 0))
    await state.update_data(page=page)
    sub_id = data.get("subscribed_id")
    await safe_edit(target, results_text(req, result, stats, page, rec, trend), kb.results(page, len(result.offers), sub_id))


@router.callback_query(Res.filter(F.action == "subscribe"))
async def res_subscribe(cb: CallbackQuery, state: FSMContext, svc: SearchService, user: User) -> None:
    data = await state.get_data()
    if not data.get("date_from"):
        await show(cb, texts.SESSION_EXPIRED, kb.main_menu())
        return
    req = request_from_data(data)
    filters = FilterSettings.from_dict(data["filters"])

    async with session_scope() as s:
        count = await s.scalar(
            select(func.count(Subscription.id)).where(Subscription.user_id == user.id, Subscription.is_active.is_(True))
        )
    if count >= user.max_subscriptions:
        await cb.answer(f"Можно следить максимум за {user.max_subscriptions} маршрутами", show_alert=True)
        return
    # Поиск — вне транзакции: он сам пишет в БД (история, логи), а SQLite не любит долгие блокировки
    result = await search_route(svc, req, filters, user.id)
    async with session_scope() as s:
        sub = Subscription(
            user_id=user.id,
            origin=",".join(req.origins),
            destination=",".join(req.destinations),
            origin_name=", ".join(req.origin_names),
            destination_name=", ".join(req.destination_names),
            date_from=req.date_from,
            date_to=req.date_to,
            adults=req.adults,
            children=req.children,
            infants=req.infants,
            direct_only=req.direct_only,
            filters=filters.model_dump(),
            notify_new_min=True,
            last_min_price=result.offers[0].price_rub if result.offers else None,
        )
        s.add(sub)
        await s.flush()
        sub_id = sub.id

    await state.update_data(subscribed_id=sub_id)
    await cb.answer("🔔 Готово! Напишу, когда цена снизится. Настроить порог и сводки — кнопка ниже.", show_alert=True)
    await safe_edit(cb.message, None, kb.results(data.get("page", 0), len(result.offers), sub_id))
