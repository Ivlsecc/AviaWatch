"""Переключение фильтров кнопками: каждое нажатие — следующее значение по кругу."""

from search.filters import FilterSettings

TRANSFERS = [0, 1, 2, 3]
# Лимит всего времени в пути, ч; None — авто (×max_duration_factor от самого быстрого)
DURATION_HOURS = [None, 8, 12, 16, 24]
LAYOVERS = [(60, 480), (45, 360), (120, 720), (0, 24 * 60)]
ARRIVAL = [None, "no_night", "day"]
# Города, где аэропорт прилёта важен: до Внуково и до Домодедово добираться по-разному
CITY_AIRPORTS = {
    "MOW": ["SVO", "VKO", "DME", "ZIA"],
    "IST": ["IST", "SAW"],
}


def airport_choices(destinations: list[str]) -> list[str]:
    """Аэропорты прилёта, между которыми можно выбирать в фильтре (только для городов с несколькими)."""
    found: list[str] = []
    for d in destinations:
        for code in CITY_AIRPORTS.get(d, []):
            if code not in found:
                found.append(code)
    return found if len(found) > 1 else []


def _next(values: list, current):
    try:
        return values[(values.index(current) + 1) % len(values)]
    except ValueError:
        return values[0]


def toggle(f: FilterSettings, field: str) -> FilterSettings:
    match field:
        case "transfers":
            return f.model_copy(update={"max_transfers": _next(TRANSFERS, f.max_transfers)})
        case "duration":
            return f.model_copy(update={"max_duration_hours": _next(DURATION_HOURS, f.max_duration_hours)})
        case "layover":
            lo, hi = _next(LAYOVERS, (f.min_layover_min, f.max_layover_min))
            return f.model_copy(update={"min_layover_min": lo, "max_layover_min": hi})
        case "airport":
            return f.model_copy(update={"exclude_airport_change": not f.exclude_airport_change})
        case "self":
            return f.model_copy(update={"exclude_self_transfer": not f.exclude_self_transfer})
        case "night":
            return f.model_copy(update={"exclude_night_layovers": not f.exclude_night_layovers})
        case "combos":
            return f.model_copy(update={"self_combos": not f.self_combos})
        case "arrival":
            return f.model_copy(update={"arrival_window": _next(ARRIVAL, f.arrival_window)})
        case "reset":
            return FilterSettings()
    if field.startswith("apt_"):
        code = field[4:]
        chosen = [a for a in f.arrival_airports if a != code]
        if code not in f.arrival_airports:
            chosen.append(code)
        return f.model_copy(update={"arrival_airports": chosen})
    return f
