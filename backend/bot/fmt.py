"""Форматирование сообщений бота (HTML)."""

from __future__ import annotations

from datetime import date
from html import escape

from search.analytics import PriceStats
from search.filters import FilterSettings
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
    return f"{d(a)} – {d(b)}"


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


def transfers_label(o: FlightOffer) -> str:
    if o.transfers == 0:
        return "прямой"
    via = o.route_airports[1:-1]
    word = plural(o.transfers, "пересадка", "пересадки", "пересадок")
    return f"{o.transfers} {word}" + (f" ({', '.join(via)})" if via else "")


def offer_line(i: int, o: FlightOffer) -> str:
    flights = ", ".join(o.flight_numbers) or ", ".join(o.airlines)
    details = " · ".join(x for x in (transfers_label(o), duration(o.duration_min), flights) if x)
    if o.legs_links:
        links = [f'<a href="{escape(link, quote=True)}">{escape(label)}</a> {rub(p)}' for label, p, link in o.legs_links]
        return (
            f"{i}. <b>{rub(o.price_rub)}</b> · {o.departure_at:%d.%m %H:%M} · {o.origin_airport}→{o.destination_airport}\n"
            f"    🧩 {' → '.join(o.route_airports)} · {duration(o.duration_min)} · {', '.join(o.flight_numbers)}\n"
            f"    ⚠️ {escape(o.note or '')}\n"
            f"    🛒 {' + '.join(links)}"
        )
    links = [f'<a href="{escape(o.link, quote=True)}">{escape(source_title(o.source))}</a>']
    links += [f'<a href="{escape(link, quote=True)}">{escape(source_title(src))} {rub(p)}</a>' for src, p, link in o.alt_links]
    when = f"{o.departure_at:%d.%m %H:%M}" if o.time_known else f"{o.departure_at:%d.%m}, время уточнять"
    text = (
        f"{i}. <b>{rub(o.price_rub)}</b> · {when} · {o.origin_airport}→{o.destination_airport}\n"
        f"    {details}\n"
    )
    if o.note:
        text += f"    ℹ️ {escape(o.note)}\n"
    return text + f"    🛒 {' · '.join(links)}"


def stats_block(stats: PriceStats | None, pax: int) -> str:
    if stats is None or stats.mean is None:
        return "📊 Средняя цена: пока недостаточно данных"
    text = (
        f"📊 Средняя цена за 1 пассажира: <b>{rub(stats.mean)}</b> (медиана {rub(stats.median)})\n"
        f"    вылеты {d(stats.window_from)}–{d(stats.window_to)}, {stats.days} "
        f"{plural(stats.days, 'день', 'дня', 'дней')} с ценами"
    )
    if pax > 1:
        text += f"\n    на {pax} пасс.: ≈ {rub(stats.mean * pax)}"
    if not stats.has_history:
        text += "\n    <i>История за прошлые дни ещё копится — пока только будущие даты</i>"
    return text


def results_text(
    req: RouteRequest,
    result: SearchResult,
    stats: PriceStats | None,
    page: int,
    rec: Recommendation | None = None,
    trend: Trend | None = None,
) -> str:
    head = (
        f"<b>{route_title(req)}</b>\n"
        f"📅 {dates_label(req.date_from, req.date_to)} · 👤 {pax_label(req.adults, req.children, req.infants)}"
        + (" · только прямые" if req.direct_only else "")
    )
    parts = [head, stats_block(stats, req.passengers)]
    if trend_line := trend_block(trend):
        parts.append(trend_line)
    if rec:
        parts.append(rec_block(rec))

    offers = result.offers
    if not offers:
        parts.append("😕 Подходящих рейсов не нашлось. Попробуйте расширить даты или ослабить фильтры.")
    else:
        start = page * PAGE_SIZE
        chunk = offers[start : start + PAGE_SIZE]
        parts.append("\n\n".join(offer_line(start + i + 1, o) for i, o in enumerate(chunk)))
        parts.append(f"<i>Показано {start + 1}–{start + len(chunk)} из {len(offers)}</i>")

    parts.append(sources_line(result))
    return "\n\n".join(parts)


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
        f"{arrow} Цена на ваши даты за {trend.days} дн.: {sparkline(values)} "
        f"{'+' if change > 0 else '−' if change < 0 else ''}{abs(change):.0f}%"
    )


def rec_block(rec: Recommendation) -> str:
    lines = [f"{rec.emoji} <b>{rec.title}</b>"]
    lines += [f"    • {escape(r)}" for r in rec.reasons[:3]]
    if rec.low_confidence:
        lines.append("    <i>данных пока мало — оценка приблизительная, точнее станет через пару дней</i>")
    return "\n".join(lines)


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
            f"• Время в пути: <b>{duration_factor_label(f)}</b>",
            f"• Стыковка: <b>{layover_label(f)}</b>",
            f"• Смена аэропорта при стыковке: <b>{'исключать' if f.exclude_airport_change else 'разрешить'}</b>",
            f"• Самостоятельная пересадка: <b>{'исключать' if f.exclude_self_transfer else 'разрешить'}</b>",
            f"• Ночные стыковки: <b>{'исключать' if f.exclude_night_layovers else 'разрешить'}</b>",
            f"• 🧩 Составные маршруты: <b>{'искать' if f.self_combos else 'нет'}</b>",
            "   <i>два отдельных билета через Стамбул/Каир/Дубай — бывает намного дешевле, но багаж и риск опоздания на вас</i>",
        ]
    )


def duration_factor_label(f: FilterSettings) -> str:
    if not f.max_duration_factor:
        return "без ограничений"
    return f"не дольше ×{f.max_duration_factor:g} от самого быстрого"


def layover_label(f: FilterSettings) -> str:
    if f.min_layover_min <= 0 and f.max_layover_min >= 24 * 60:
        return "любая"
    return f"{f.min_layover_min / 60:g}–{f.max_layover_min / 60:g} ч"
