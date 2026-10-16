"""Покупка билетов по одному вместо одной брони на всех.

Места на рейсе продаются корзинами тарифов. Если по дешёвому тарифу осталось
одно место, бронь на двоих целиком уходит в следующий, более дорогой тариф —
и сайт показывает дорогую цену за обоих. Поиск на одного пассажира покажет
дешёвый тариф: один билет можно взять по нему, остальные — как обычно.

Сколько дешёвых мест осталось, мы не знаем, поэтому экономию считаем
осторожно: «от» — дёшево купили один билет, «до» — дёшево купили все.
"""

from __future__ import annotations

from dataclasses import dataclass

from sources.base import FlightOffer

# Меньше этого за один билет — не повод возиться с отдельными бронями
MIN_SAVING_RUB = 300


@dataclass(frozen=True)
class SplitSaving:
    single_price: int  # один билет при поиске на одного
    together_each: int  # за одного при брони на всех
    saving_min: int  # дешёвый тариф достался одному
    saving_max: int  # дешёвый тариф достался всем


def split_saving(offer: FlightOffer, pax: int) -> SplitSaving | None:
    if pax < 2 or offer.split_single_rub is None:
        return None
    each = round(offer.price_rub / pax)
    saving_min = each - offer.split_single_rub
    if saving_min < MIN_SAVING_RUB:
        return None
    return SplitSaving(offer.split_single_rub, each, saving_min, offer.price_rub - offer.split_single_rub * pax)


def mark_split_prices(offers: list[FlightOffer], singles: list[FlightOffer], pax: int) -> int:
    """Проставляет offer.split_single_rub, если на одного выходит заметно дешевле. Возвращает число таких рейсов."""
    if pax < 2:
        return 0
    best: dict[tuple, int] = {}
    for s in singles:
        if s.legs_links:
            continue
        key = s.identity()
        if key not in best or s.price_rub < best[key]:
            best[key] = s.price_rub
    marked = 0
    for o in offers:
        single = best.get(o.identity()) if not o.legs_links else None
        o.split_single_rub = single
        if split_saving(o, pax):
            marked += 1
        else:
            o.split_single_rub = None
    return marked
