"""Форматирование сообщений бота (HTML)."""

from __future__ import annotations

from datetime import date, datetime
from html import escape

from common.airports import airports

from search.analytics import PriceStats
from search.filters import ARRIVAL_WINDOWS, NIGHT_HOURS, FilterSettings, local_arrival
from search.flexible import FlexHint
from search.split import split_saving
from search.history import Trend
from search.recommend import Recommendation
from search.orchestrator import SearchResult
from search.routes import RouteRequest
from sources.base import FlightOffer
from sources.registry import all_sources

PAGE_SIZE = 5
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]


def rub(n: int | float | None) -> str:
    if n is None:
        return "—"
    return f"{int(n):,}".replace(",", " ") + " ₽"


def d(day: date) -> str:
    return day.strftime("%d.%m")


def dates_label(a: date, b: date) -> str:
    if a == b:
        return f"{a.day} {MONTHS_GEN[a.month - 1]}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {MONTHS_GEN[a.month - 1]}"
    return f"{a.day} {MONTHS_GEN[a.month - 1]} – {b.day} {MONTHS_GEN[b.month - 1]}"


def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def pax_label(adults: int, children: int, infants: int) -> str:
    parts = [f"{adults} взр."]
    if children:
        parts.append(f"{children} реб.")
    if infants:
        parts.append(f"{infants} млад.")
    return ", ".join(parts)


def route_title(req: RouteRequest) -> str:
    o = " / ".join(req.origin_names or req.origins)
    t = " / ".join(req.destination_names or req.destinations)
    return f"{escape(o)} → {escape(t)}"


def duration(minutes: int | None) -> str:
    if not minutes:
        return ""
    h, m = divmod(minutes, 60)
    return f"{h} ч {m:02d} мин" if m else f"{h} ч"


def source_title(name: str) -> str:
    if name == "combo":
        return "Составные маршруты"
    cls = all_sources().get(name)
    return cls.title if cls else name


MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "нояб", "дек"]
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def day_label(day: date) -> str:
    """«4 нояб, ср» — дата с днём недели: так проще сверить с календарём."""
    return f"{day.day} {MONTHS_SHORT[day.month - 1]}, {WEEKDAYS[day.weekday()]}"


def times_label(o: FlightOffer) -> str:
    if not o.time_known:
        return f"{o.origin_airport} → {o.destination_airport}, время уточнять у продавца"
    text = f"{o.departure_at:%H:%M} {o.origin_airport} → "
    arr = local_arrival(o)
    if arr:
        shift = (arr.date() - o.departure_at.date()).days
        text += f"{arr:%H:%M}{f' (+{shift})' if shift > 0 else ''} "
    return text + o.destination_airport


def transfers_label(o: FlightOffer) -> str:
    if o.transfers == 0:
        return "прямой"
    word = plural(o.transfers, "пересадка", "пересадки", "пересадок")
    if len(o.segments) > 1:
        # Где и сколько ждать — главное, по чему решают, брать ли рейс с пересадкой
        stops = [
            f"{a.destination} {duration(m)}" + (", ночью" if a.arrival_at.hour in NIGHT_HOURS else "")
            for a, m in zip(o.segments, o.layovers_min())
        ]
        return f"{o.transfers} {word} ({'; '.join(stops)})"
    via = o.route_airports[1:-1]
    return f"{o.transfers} {word}" + (f" ({', '.join(via)})" if via else "")


MAX_ALT_LINKS = 2


def price_check_line(o: FlightOffer) -> str | None:
    """Итог сверки цены из кэша Aviasales с живыми сайтами (search/verify.py)."""
    match o.price_check:
        case "confirmed":
            return "✓ <i>цена подтверждена на живом сайте</i>"
        case "updated":
            return f"↻ <i>в кэше Aviasales было {rub(o.cached_price_rub)}, на сайтах сейчас дороже</i>"
        case "unconfirmed":
            return "⚠️ <i>цена из кэша Aviasales, на живых сайтах рейс не нашёлся — проверьте по ссылке</i>"
    return None


def offer_line(i: int, o: FlightOffer, pax: int = 1) -> str:
    each = f" · {rub(round(o.price_rub / pax))} за чел." if pax > 1 else ""
    head = f"<b>{i}. {rub(o.price_rub)}</b>{each}"
    when = f"<b>{day_label(o.departure_at.date())}</b> · {times_label(o)}"
    if o.duration_min:
        when += f" · {duration(o.duration_min)}"

    if o.legs_links:
        links = [f'<a href="{escape(link, quote=True)}">{escape(label)}</a> {rub(p)}' for label, p, link in o.legs_links]
        return (
            f"{head}\n{when}\n"
            f"🧩 {' → '.join(o.route_airports)} · {', '.join(o.flight_numbers)}\n"
            f"<i>{escape(o.note or '')}</i>\n"
            f"Купить по отдельности: {' + '.join(links)}"
        )

    flights = ", ".join(o.flight_numbers) or ", ".join(o.airlines)
    route = " · ".join(x for x in (transfers_label(o), flights) if x)
    lines = [head, when, route]
    if o.baggage_included is True:
        lines[-1] += " · с багажом"
    elif o.baggage_included is False:
        lines[-1] += " · без багажа"
    if o.note:
        lines.append(f"<i>{escape(o.note)}</i>")
    if check := price_check_line(o):
        lines.append(check)
    if sp := split_saving(o, pax):
        saving = rub(sp.saving_min)
        if sp.saving_max > sp.saving_min:
            saving = f"{saving.removesuffix(' ₽')}–{rub(sp.saving_max)}"
        lines.append(f"👥 По одному дешевле: билет от {rub(sp.single_price)} вместо {rub(sp.together_each)}, экономия {saving}")

    buy = f'<a href="{escape(o.link, quote=True)}">{escape(source_title(o.source))}</a>'
    alts = [f'<a href="{escape(link, quote=True)}">{escape(source_title(src))}</a> {rub(p)}' for src, p, link in o.alt_links[:MAX_ALT_LINKS]]
    more = len(o.alt_links) - MAX_ALT_LINKS
    tail = f" · ещё {more}" if more > 0 else ""
    lines.append(f"→ {buy}" + (f"   <i>также: {' · '.join(alts)}{tail}</i>" if alts else ""))
    return "\n".join(lines)


def stats_block(stats: PriceStats | None, pax: int, trend: Trend | None = None) -> str:
    if stats is None or stats.mean is None:
        line = "Средняя цена: пока мало данных"
    else:
        line = f"Обычно <b>{rub(stats.mean)}</b> за человека"
        if pax > 1:
            line += f" · на {pax}: ≈ {rub(stats.mean * pax)}"
        line += f"\n<i>по вылетам {d(stats.window_from)}–{d(stats.window_to)}"
        if not stats.has_history:
            line += ", история ещё копится"
        line += "</i>"
    if t := trend_block(trend):
        line += f"\n{t}"
    return line


def results_text(
    req: RouteRequest,
    result: SearchResult,
    stats: PriceStats | None,
    page: int,
    rec: Recommendation | None = None,
    trend: Trend | None = None,
    flex: FlexHint | None = None,
) -> str:
    head = (
        f"✈️ <b>{route_title(req)}</b>\n"
        f"{dates_label(req.date_from, req.date_to)} · {pax_label(req.adults, req.children, req.infants)}"
        + (" · только прямые" if req.direct_only else "")
    )
    parts = [head]
    summary = []
    if rec:
        summary.append(rec_block(rec))
    summary.append(stats_block(stats, req.passengers, trend))
    parts.append("\n".join(summary))

    hints = []
    if flex:
        hints.append(
            f"💡 {day_label(flex.day)} — от {rub(flex.price_per_pax)} за человека, "
            f"на {flex.saving_pct:.0f}% дешевле <i>(по календарю цен, уточнится при поиске)</i>"
        )

    offers = result.offers
    if not offers:
        parts += hints
        parts.append("Подходящих рейсов не нашлось. Попробуйте расширить даты или ослабить фильтры.")
    else:
        if split_count := sum(1 for o in offers if split_saving(o, req.adults)):
            hints.append(
                f"👥 На {split_count} {plural(split_count, 'рейсе', 'рейсах', 'рейсах')} дешёвый тариф остался не на всех — "
                "берите билеты отдельными бронями, по одной на человека"
            )
        parts += ["\n".join(hints)] if hints else []
        start = page * PAGE_SIZE
        chunk = offers[start : start + PAGE_SIZE]
        parts += [offer_line(start + i + 1, o, req.adults) for i, o in enumerate(chunk)]
        parts.append(footer(result, start, len(chunk), len(offers)))
    if not offers:
        parts.append(footer(result, 0, 0, 0))
    return "\n\n".join(parts)


def footer(result: SearchResult, start: int, shown: int, total: int) -> str:
    asked = [st for st in result.statuses if not st.skipped and st.source != "combo"]
    ok = sum(1 for st in asked if st.ok)
    text = f"{start + 1}–{start + shown} из {total} · " if total else ""
    text += f"ответили {ok} из {len(asked)} сайтов"
    failed = [source_title(st.source) for st in asked if not st.ok]
    if failed:
        text += f" (нет ответа: {escape(', '.join(failed))})"
    if result.from_cache:
        text += " · из кэша"
    return f"<i>{text}</i>"


SPARKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[int]) -> str:
    lo, hi = min(values), max(values)
    if hi == lo:
        return SPARKS[3] * len(values)
    return "".join(SPARKS[round((v - lo) / (hi - lo) * (len(SPARKS) - 1))] for v in values)


def trend_block(trend: Trend | None) -> str | None:
    if not trend or not trend.enough:
        return None
    change = trend.change_pct
    arrow = "📉" if change < -1 else ("📈" if change > 1 else "➡️")
    values = [p for _, p in trend.points[-14:]]
    return (
        f"{arrow} за {trend.days} {plural(trend.days, 'день', 'дня', 'дней')} {sparkline(values)} "
        f"{'+' if change > 0 else '−' if change < 0 else ''}{abs(change):.0f}%"
    )


def rec_block(rec: Recommendation) -> str:
    reasons = "; ".join(escape(r) for r in rec.reasons[:2])
    text = f"{rec.emoji} <b>{rec.title}</b>" + (f" — {reasons}" if reasons else "")
    if rec.low_confidence:
        text += " <i>(данных пока мало)</i>"
    return text


def sources_line(result: SearchResult) -> str:
    items = []
    for st in result.statuses:
        mark = "✅" if st.ok else ("⏸" if st.skipped else "⚠️")
        items.append(f"{mark} {escape(source_title(st.source))}")
    suffix = " · из кэша" if result.from_cache else ""
    return "<i>Источники: " + (", ".join(items) or "нет активных") + suffix + "</i>"


def filters_text(f: FilterSettings) -> str:
    return "\n".join(
        [
            "⚙️ <b>Фильтры маршрутов</b>",
            "Отсекают неудобные варианты: много пересадок, огромные стыковки, смену аэропорта.",
            "",
            f"• Пересадок не больше: <b>{f.max_transfers}</b>",
            f"• Время в пути (от вылета до прилёта): <b>{duration_factor_label(f)}</b>",
            f"• Ожидание на одной пересадке: <b>{layover_label(f)}</b>",
            f"• Смена аэропорта при стыковке: <b>{'исключать' if f.exclude_airport_change else 'разрешить'}</b>",
            f"• Самостоятельная пересадка: <b>{'исключать' if f.exclude_self_transfer else 'разрешить'}</b>",
            f"• Ночные стыковки: <b>{'исключать' if f.exclude_night_layovers else 'разрешить'}</b>",
            f"• Прилёт: <b>{arrival_label(f)}</b>",
            f"• 🧩 Составные маршруты: <b>{'искать' if f.self_combos else 'нет'}</b>",
            "   <i>два отдельных билета через Стамбул/Каир/Дубай — бывает намного дешевле, но багаж и риск опоздания на вас</i>",
        ]
    )


ARRIVAL_TITLES = {None: "в любое время", "no_night": "не ночью, 06–24", "day": "днём, 08–22"}


def arrival_label(f: FilterSettings) -> str:
    text = ARRIVAL_TITLES.get(f.arrival_window, "в любое время")
    if f.arrival_airports:
        text += ", только " + ", ".join(f.arrival_airports)
    return text


def duration_factor_label(f: FilterSettings) -> str:
    if f.max_duration_hours:
        return f"всего не дольше {f.max_duration_hours:g} ч"
    if not f.max_duration_factor:
        return "без ограничений"
    return f"авто — не дольше ×{f.max_duration_factor:g} от самого быстрого рейса"


def layover_label(f: FilterSettings) -> str:
    if f.min_layover_min <= 0 and f.max_layover_min >= 24 * 60:
        return "любое"
    return f"от {f.min_layover_min / 60:g} до {f.max_layover_min / 60:g} ч"
