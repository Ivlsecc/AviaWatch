from search.split import mark_split_prices, split_saving
from tests.test_filters_dedup import offer


def test_single_ticket_cheaper_is_marked():
    # На двоих 44 600 (по 22 300), на одного — 19 800: дешёвый тариф остался не на всех
    together = offer(44600, source="anex", flights=["NE644"])
    other = offer(30000, source="kupibilet", flights=["SU101"])
    singles = [offer(19800, source="kupibilet", flights=["NE 644"]), offer(15000, source="tutu", flights=["SU101"])]
    assert mark_split_prices([together, other], singles, pax=2) == 1
    sp = split_saving(together, 2)
    assert (sp.single_price, sp.together_each, sp.saving_min, sp.saving_max) == (19800, 22300, 2500, 5000)
    # Ровно половина цены на двоих — экономии нет, отметки нет
    assert other.split_single_rub is None and split_saving(other, 2) is None


def test_tiny_difference_and_single_pax_ignored():
    o = offer(40000, flights=["NE644"])
    assert mark_split_prices([o], [offer(19900, flights=["NE644"])], pax=2) == 0
    assert mark_split_prices([o], [offer(10000, flights=["NE644"])], pax=1) == 0
    assert o.split_single_rub is None


def test_offer_line_shows_split_hint():
    from bot.fmt import offer_line, rub

    o = offer(44600, flights=["NE644"])
    mark_split_prices([o], [offer(19800, flights=["NE644"])], pax=2)
    text = offer_line(1, o, pax=2)
    assert "👥 По одному дешевле: билет от" in text and f"{rub(2500)[:-2]}–{rub(5000)}" in text
    assert "👥" not in offer_line(1, o, pax=1)
