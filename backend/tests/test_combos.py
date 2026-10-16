from datetime import datetime, timedelta, timezone

import pytest

from bot.fmt import offer_line
from common.airports import airports
from search.combos import combine, worth_showing
from search.dedup import merge_duplicates
from search.filters import FilterSettings, apply_filters
from sources.base import FlightOffer, Segment

T0 = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def offline():
    airports.set_data({})


def leg(o, d, dep_h, dur_h, price, fn, source="kupibilet"):
    dep = T0 + timedelta(hours=dep_h)
    arr = dep + timedelta(hours=dur_h)
    return FlightOffer(
        source=source, price_rub=price, origin_airport=o, destination_airport=d, departure_at=dep, arrival_at=arr,
        duration_min=int(dur_h * 60), flight_numbers=[fn], segments=[Segment(origin=o, destination=d, departure_at=dep,
        arrival_at=arr, flight_number=fn)], route_airports=[o, d], link=f"https://x/{fn}",
    )


def test_combine_respects_connection_rules():
    first = [leg("HRG", "IST", 0, 2.5, 8000, "PC1"), leg("HRG", "SAW", 0, 2.5, 7000, "PC2")]
    second = [
        leg("IST", "SVO", 3, 4, 9000, "SU1"),     # стыковка 30 мин — мало
        leg("IST", "SVO", 6, 4, 10000, "SU2"),    # 3.5 ч в IST — ок; из SAW (смена аэропорта) — мало
        leg("IST", "VKO", 9, 4, 11000, "TK3"),    # 6.5 ч — ок и со сменой аэропорта
        leg("IST", "SVO", 30, 4, 5000, "SU4"),    # 27.5 ч — слишком долго
        leg("AYT", "SVO", 6, 4, 1000, "PC5"),     # другой город
    ]
    combos = combine(first, second)
    got = [(c.flight_numbers, c.price_rub, c.airport_change) for c in combos]
    assert got == [
        (["PC1", "SU2"], 18000, False),
        (["PC2", "TK3"], 18000, True),
        (["PC1", "TK3"], 19000, False),
    ]
    c = combos[0]
    assert c.self_transfer and c.transfers == 1 and c.route_airports == ["HRG", "IST", "SVO"]
    assert [lbl for lbl, _, _ in c.legs_links] == ["1-й билет", "2-й билет"]
    assert "2 отдельных билета" in c.note


def test_combo_never_merges_with_regular_ticket():
    combo = combine([leg("HRG", "IST", 0, 2.5, 8000, "PC1")], [leg("IST", "SVO", 6, 4, 10000, "SU2")])[0]
    regular = leg("HRG", "SVO", 0, 12, 30000, "PC1", source="tutu").model_copy(update={"transfers": 1, "destination_airport": "SVO"})
    merged = merge_duplicates([combo, regular])
    assert len(merged) == 2 and any(o.legs_links for o in merged)


def test_worth_showing_requires_saving():
    combo = combine([leg("HRG", "IST", 0, 2.5, 8000, "PC1")], [leg("IST", "SVO", 6, 4, 10000, "SU2")])[0]
    assert worth_showing([combo], [leg("HRG", "SVO", 0, 5, 19000, "SU9")]) == []  # экономия < 7%
    assert worth_showing([combo], [leg("HRG", "SVO", 0, 5, 25000, "SU9")]) == [combo]
    assert worth_showing([combo], []) == [combo]


def test_default_filters_hide_combos_but_flag_shows_them():
    combo = combine([leg("HRG", "IST", 0, 2.5, 8000, "PC1")], [leg("IST", "SVO", 6, 4, 10000, "SU2")])[0]
    assert apply_filters([combo], FilterSettings()) == []
    assert apply_filters([combo], FilterSettings(exclude_self_transfer=False)) == [combo]


def test_combo_rendering():
    combo = combine([leg("HRG", "IST", 0, 2.5, 8000, "PC1")], [leg("IST", "SVO", 6, 4, 10000, "SU2")])[0]
    line = offer_line(1, combo)
    assert "🧩 HRG → IST → SVO" in line and "1-й билет</a>" in line and "составной маршрут" in line
