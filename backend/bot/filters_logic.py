"""Переключение фильтров кнопками: каждое нажатие — следующее значение по кругу."""

from search.filters import FilterSettings

TRANSFERS = [0, 1, 2, 3]
DURATION = [1.5, 2.0, 2.5, 3.0, None]
LAYOVERS = [(60, 480), (45, 360), (120, 720), (0, 24 * 60)]


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
            return f.model_copy(update={"max_duration_factor": _next(DURATION, f.max_duration_factor)})
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
        case "reset":
            return FilterSettings()
    return f
