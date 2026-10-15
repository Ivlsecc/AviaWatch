from sources.base import FlightOffer

# Поля маршрута, которые берём у самого подробного источника (цена и ссылка — у самого дешёвого)
DETAIL_FIELDS = (
    "arrival_at", "duration_min", "flight_numbers", "airlines", "segments",
    "route_airports", "airport_change", "self_transfer", "baggage_included",
)


def merge_duplicates(offers: list[FlightOffer]) -> list[FlightOffer]:
    """Склеивает один и тот же рейс из разных источников.

    Цена и ссылка — от самого дешёвого предложения, подробности маршрута — от самого
    подробного, остальные источники попадают в alt_links. Результат отсортирован по цене.
    """
    groups: dict[tuple, list[FlightOffer]] = {}
    for o in offers:
        groups.setdefault(o.identity(), []).append(o)

    merged = []
    for group in groups.values():
        group.sort(key=lambda o: o.price_rub)
        best = group[0].model_copy()
        richest = max(group, key=lambda o: o.detail_score())
        if richest is not group[0] and richest.detail_score() > best.detail_score():
            best = best.model_copy(update={f: getattr(richest, f) for f in DETAIL_FIELDS})

        seen = {best.source}
        alts = []
        for other in group[1:]:
            if other.source in seen:
                continue
            seen.add(other.source)
            alts.append((other.source, other.price_rub, other.link))
        best.alt_links = alts
        merged.append(best)

    merged.sort(key=lambda o: (o.price_rub, o.departure_at))
    return merged
