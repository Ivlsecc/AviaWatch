from sources.base import FlightOffer

# Поля маршрута, которые берём у самого подробного источника (цена и ссылка — у самого дешёвого).
# Багажа здесь нет: это свойство тарифа, а не рейса — у дешёвого тарифа своё значение.
DETAIL_FIELDS = (
    "arrival_at", "duration_min", "flight_numbers", "airlines", "segments",
    "route_airports", "airport_change", "self_transfer",
)


def group_same_flights(offers: list[FlightOffer]) -> list[list[FlightOffer]]:
    """Делит предложения на группы «один и тот же маршрут».

    Предложения с полным списком рейсов совпадают, только если совпали все рейсы.
    Неполное (известен лишь первый рейс) присоединяется к полной группе, только когда
    такая группа ровно одна; иначе неполные группируются между собой по первому рейсу.
    """
    full: dict[tuple, list[FlightOffer]] = {}
    partial: list[FlightOffer] = []
    for o in offers:
        key = o.full_identity()
        if key is None:
            partial.append(o)
        else:
            full.setdefault(key, []).append(o)

    by_loose: dict[tuple, list[tuple]] = {}
    for key, group in full.items():
        by_loose.setdefault(group[0].identity(), []).append(key)

    leftovers: dict[tuple, list[FlightOffer]] = {}
    for o in partial:
        loose = o.identity()
        candidates = by_loose.get(loose, []) if not o.legs_links else []
        if len(candidates) == 1:
            full[candidates[0]].append(o)
        else:
            leftovers.setdefault(loose, []).append(o)
    return [*full.values(), *leftovers.values()]


def merge_duplicates(offers: list[FlightOffer]) -> list[FlightOffer]:
    """Склеивает один и тот же рейс из разных источников.

    Цена и ссылка — от самого дешёвого предложения, подробности маршрута — от самого
    подробного, остальные источники попадают в alt_links. Результат отсортирован по цене.
    """
    merged = []
    for group in group_same_flights(offers):
        group.sort(key=lambda o: o.price_rub)
        best = group[0].model_copy()
        richest = max(group, key=lambda o: o.detail_score())
        if richest is not group[0] and richest.detail_score() > best.detail_score():
            best = best.model_copy(update={f: getattr(richest, f) for f in DETAIL_FIELDS})
        if best.baggage_included is None:
            # Багаж неизвестен — берём только у варианта по той же цене
            same = [o.baggage_included for o in group if o.price_rub == best.price_rub and o.baggage_included is not None]
            best.baggage_included = same[0] if same else None

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
