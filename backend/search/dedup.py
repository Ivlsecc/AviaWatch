from sources.base import FlightOffer


def merge_duplicates(offers: list[FlightOffer]) -> list[FlightOffer]:
    """Склеивает один и тот же рейс из разных источников.

    Остаётся самое дешёвое предложение, остальные источники попадают в alt_links.
    Результат отсортирован по цене.
    """
    groups: dict[tuple, list[FlightOffer]] = {}
    for o in offers:
        groups.setdefault(o.identity(), []).append(o)

    merged = []
    for group in groups.values():
        group.sort(key=lambda o: o.price_rub)
        best = group[0].model_copy()
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
