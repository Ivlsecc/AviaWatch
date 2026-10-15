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

        # Повторная склейка (например, по нескольким городам маршрута) не должна терять уже найденные ссылки
        seen = {best.source}
        alts = []
        candidates = [(o.source, o.price_rub, o.link) for o in group[1:]]
        candidates += [alt for o in group for alt in o.alt_links]
        for src, price, link in sorted(candidates, key=lambda a: a[1]):
            if src in seen:
                continue
            seen.add(src)
            alts.append((src, price, link))
        best.alt_links = alts
        merged.append(best)

    merged.sort(key=lambda o: (o.price_rub, o.departure_at))
    return merged
