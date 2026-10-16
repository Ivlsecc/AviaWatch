from __future__ import annotations

import calendar
from datetime import date

from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.callbacks import Cal, Flex, Flt, Menu, Pax, PlacePick, Res, Sub, Wiz
from bot.fmt import PAGE_SIZE, dates_label, rub
from common.models import Subscription
from common.places import Place
from search.filters import FilterSettings

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
          "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔎 Найти маршрут", callback_data=Menu(action="search"))
    kb.button(text="🔔 Уведомления", callback_data=Menu(action="subs"))
    kb.button(text="⚙️ Фильтры", callback_data=Menu(action="filters"))
    kb.button(text="❓ Как это работает", callback_data=Menu(action="help"))
    kb.adjust(1, 2, 1)
    return kb.as_markup()


def home_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[Btn(text="🏠 Меню", callback_data=Menu(action="home").pack())]])


def wizard_nav(step: str, can_next: bool = False) -> list[Btn]:
    row = [Btn(text="← Назад", callback_data=Wiz(action="back", step=step).pack())]
    if can_next:
        row.append(Btn(text="Далее →", callback_data=Wiz(action="next", step=step).pack()))
    return row


def places(step: str, items: list[Place], has_selected: bool) -> InlineKeyboardMarkup:
    rows = [[Btn(text=p.label[:60], callback_data=PlacePick(step=step, idx=i).pack())] for i, p in enumerate(items)]
    rows.append(wizard_nav(step, can_next=has_selected))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def place_selected(step: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [Btn(text="Далее →", callback_data=Wiz(action="next", step=step).pack())],
            [
                Btn(text="← Назад", callback_data=Wiz(action="back", step=step).pack()),
                Btn(text="↺ Сбросить", callback_data=Wiz(action="reset", step=step).pack()),
            ],
        ]
    )


def calendar_kb(year: int, month: int, today: date, start: date | None) -> InlineKeyboardMarkup:
    noop = Cal(action="noop").pack()
    rows: list[list[Btn]] = []

    prev_y, prev_m = (year, month - 1) if month > 1 else (year - 1, 12)
    next_y, next_m = (year, month + 1) if month < 12 else (year + 1, 1)
    can_prev = (year, month) > (today.year, today.month)
    rows.append(
        [
            Btn(text="◀" if can_prev else " ", callback_data=Cal(action="nav", y=prev_y, m=prev_m).pack() if can_prev else noop),
            Btn(text=f"{MONTHS[month - 1]} {year}", callback_data=noop),
            Btn(text="▶", callback_data=Cal(action="nav", y=next_y, m=next_m).pack()),
        ]
    )
    rows.append([Btn(text=w, callback_data=noop) for w in WEEKDAYS])
    for week in calendar.Calendar().monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(Btn(text=" ", callback_data=noop))
                continue
            dt = date(year, month, day)
            if dt < today:
                row.append(Btn(text="·", callback_data=noop))
                continue
            label = f"[{day}]" if start == dt else str(day)
            row.append(Btn(text=label, callback_data=Cal(action="day", y=year, m=month, d=day).pack()))
        rows.append(row)
    if start:
        rows.append([Btn(text=f"✅ Только {start:%d.%m}", callback_data=Cal(action="single").pack())])
    rows.append(wizard_nav("dates"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def passengers(adults: int, children: int, infants: int) -> InlineKeyboardMarkup:
    def row(kind: str, title: str, value: int) -> list[Btn]:
        return [
            Btn(text="−", callback_data=Pax(kind=kind, delta=-1).pack()),
            Btn(text=f"{title}: {value}", callback_data=Cal(action="noop").pack()),
            Btn(text="+", callback_data=Pax(kind=kind, delta=1).pack()),
        ]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            row("adults", "Взрослые", adults),
            row("children", "Дети 2–11", children),
            row("infants", "Младенцы", infants),
            wizard_nav("pax", can_next=True),
        ]
    )


def summary(direct_only: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [Btn(text="🔎 Искать", callback_data=Wiz(action="search").pack())],
            [
                Btn(text=f"✈️ Только прямые: {'да' if direct_only else 'нет'}", callback_data=Wiz(action="direct").pack()),
                Btn(text="⚙️ Фильтры", callback_data=Wiz(action="filters").pack()),
            ],
            [
                Btn(text="← Назад", callback_data=Wiz(action="back", step="summary").pack()),
                Btn(text="✖ Отмена", callback_data=Menu(action="home").pack()),
            ],
        ]
    )


def filters(f: FilterSettings, ctx: str) -> InlineKeyboardMarkup:
    def b(text: str, field: str) -> Btn:
        return Btn(text=text, callback_data=Flt(field=field, ctx=ctx).pack())

    rows = [
        [b(f"Пересадок ≤ {f.max_transfers}", "transfers"), b("В пути: " + (f"≤ {f.max_duration_hours:g} ч" if f.max_duration_hours else "авто"), "duration")],
        [b(f"Ожидание на пересадке: {f.min_layover_min / 60:g}–{f.max_layover_min / 60:g} ч", "layover")],
        [b(("✅" if f.exclude_airport_change else "⬜") + " Без смены аэропорта", "airport")],
        [b(("✅" if f.exclude_self_transfer else "⬜") + " Без самост. пересадки", "self")],
        [b(("✅" if f.exclude_night_layovers else "⬜") + " Без ночных стыковок", "night")],
        [b(("✅" if f.self_combos else "⬜") + " 🧩 Составные маршруты (лайфхак)", "combos")],
    ]
    if ctx == "wiz":
        rows.append([b("💾 Сделать фильтрами по умолчанию", "save")])
        rows.append([b("← К поиску", "done")])
    else:
        rows.append([b("↺ Сбросить к стандартным", "reset")])
        rows.append([Btn(text="🏠 Меню", callback_data=Menu(action="home").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def results(page: int, total: int, subscribed_id: int | None = None, flex_day: date | None = None) -> InlineKeyboardMarkup:
    rows = []
    if flex_day:
        rows.append([Btn(text=f"💡 Искать на {flex_day:%d.%m}", callback_data=Flex(y=flex_day.year, m=flex_day.month, d=flex_day.day).pack())])
    nav = []
    if page > 0:
        nav.append(Btn(text="◂ Назад", callback_data=Res(action="page", page=page - 1).pack()))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(Btn(text="Показать ещё ▸", callback_data=Res(action="page", page=page + 1).pack()))
    if nav:
        rows.append(nav)
    if subscribed_id:
        rows.append([Btn(text="⚙️ Настроить уведомления", callback_data=Sub(action="open", id=subscribed_id).pack())])
    else:
        rows.append([Btn(text="🔔 Следить за ценой", callback_data=Res(action="subscribe").pack())])
    rows.append(
        [
            Btn(text="🔄 Обновить", callback_data=Res(action="refresh", page=0).pack()),
            Btn(text="✏️ Изменить", callback_data=Wiz(action="back", step="results").pack()),
            Btn(text="🏠 Меню", callback_data=Menu(action="home").pack()),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subs_list(subs: list[Subscription]) -> InlineKeyboardMarkup:
    rows = []
    for s in subs:
        mark = "🟢" if s.is_active else "⏸"
        price = f" · {rub(s.last_min_price)}" if s.last_min_price else ""
        text = f"{mark} {s.origin}→{s.destination} · {dates_label(s.date_from, s.date_to)}{price}"
        rows.append([Btn(text=text[:60], callback_data=Sub(action="open", id=s.id).pack())])
    rows.append([Btn(text="🔎 Новый поиск", callback_data=Menu(action="search").pack())])
    rows.append([Btn(text="🏠 Меню", callback_data=Menu(action="home").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sub_card(s: Subscription) -> InlineKeyboardMarkup:
    def b(text: str, action: str) -> Btn:
        return Btn(text=text, callback_data=Sub(action=action, id=s.id).pack())

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [b("🎯 Порог цены", "threshold"), b("📉 Снижение", "drop")],
            [b("🗞 Сводка", "digest"), b("🌙 Тихие часы", "quiet")],
            [b("📋 Все варианты", "results"), b("🔍 Проверить сейчас", "check")],
            [b("⏸ Пауза" if s.is_active else "▶️ Возобновить", "toggle"), b("🗑 Удалить", "delete")],
            [Btn(text="← К списку", callback_data=Menu(action="subs").pack())],
        ]
    )


def confirm_delete(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                Btn(text="🗑 Да, удалить", callback_data=Sub(action="delete_yes", id=sub_id).pack()),
                Btn(text="Отмена", callback_data=Sub(action="open", id=sub_id).pack()),
            ]
        ]
    )


def alert(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                Btn(text="📋 Все варианты", callback_data=Sub(action="results", id=sub_id).pack()),
                Btn(text="⚙️ Подписка", callback_data=Sub(action="open", id=sub_id).pack()),
            ]
        ]
    )


def back_to_sub(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[Btn(text="← К подписке", callback_data=Sub(action="open", id=sub_id).pack())]]
    )
