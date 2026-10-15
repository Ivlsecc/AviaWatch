from datetime import datetime, timedelta, timezone

from search.dedup import merge_duplicates
from search.filters import FilterSettings, apply_filters
from sources.base import FlightOffer, Segment

T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


def offer(price, transfers=0, duration=300, source="a", flights=None, segments=None, dep=T0, **kw):
    return FlightOffer(
        source=source,
        price_rub=price,
        origin_airport="HRG",
        destination_airport="SVO",
        departure_at=dep,
        duration_min=duration,
        transfers=transfers,
        flight_numbers=flights or [],
        segments=segments or [],
        link=f"https://example/{source}/{price}",
        **kw,
    )


def seg(o, d, dep_h, arr_h):
    return Segment(origin=o, destination=d, departure_at=T0 + timedelta(hours=dep_h), arrival_at=T0 + timedelta(hours=arr_h))


def test_max_transfers():
    res = apply_filters([offer(1, 0), offer(2, 1, 400), offer(3, 2, 500)], FilterSettings(max_transfers=1))
    assert [o.price_rub for o in res] == [1, 2]


def test_duration_factor_relative_to_fastest():
    res = apply_filters([offer(1, duration=300), offer(2, duration=600), offer(3, duration=601)], FilterSettings(max_duration_factor=2.0))
    assert [o.price_rub for o in res] == [1, 2]


def test_layover_bounds_and_airport_change():
    short = offer(1, 1, segments=[seg("HRG", "CAI", 0, 1), seg("CAI", "SVO", 1.5, 6)])
    ok = offer(2, 1, segments=[seg("HRG", "CAI", 0, 1), seg("CAI", "SVO", 3, 8)])
    long_ = offer(3, 1, segments=[seg("HRG", "CAI", 0, 1), seg("CAI", "SVO", 10, 14)])
    change = offer(4, 1, segments=[seg("HRG", "IST", 0, 2), seg("SAW", "SVO", 5, 9)])
    f = FilterSettings(max_duration_factor=None)
    assert [o.price_rub for o in apply_filters([short, ok, long_, change], f)] == [2]
    f2 = f.model_copy(update={"exclude_airport_change": False})
    assert [o.price_rub for o in apply_filters([short, ok, long_, change], f2)] == [2, 4]


def test_night_layover_and_self_transfer():
    night = offer(1, 1, dep=T0, segments=[seg("HRG", "CAI", 12, 15), seg("CAI", "SVO", 17, 22)])
    selfie = offer(2, self_transfer=True)
    f = FilterSettings(exclude_night_layovers=True, max_duration_factor=None)
    # Прибытие в CAI в 01:00 UTC (T0 10:00 + 15ч) — ночная стыковка
    assert apply_filters([night, selfie], f) == []


def test_merge_takes_details_from_richest_source():
    # Aviasales API: только первый рейс, без сегментов, дешевле
    api = offer(21458, transfers=1, duration=405, source="aviasales_api", flights=["PC5091"])
    # Туту: полный маршрут, дороже
    full = offer(21617, transfers=1, duration=775, source="tutu", flights=["PC5091", "PC1580"],
                 segments=[seg("HRG", "AYT", 0, 1.5), seg("AYT", "SVO", 7.5, 12.9)], self_transfer=True,
                 route_airports=["HRG", "AYT", "SVO"])
    [m] = merge_duplicates([api, full])
    assert m.price_rub == 21458 and m.source == "aviasales_api" and m.link == api.link
    assert m.flight_numbers == ["PC5091", "PC1580"] and m.duration_min == 775 and len(m.segments) == 2
    assert m.self_transfer and m.alt_links == [("tutu", 21617, full.link)]
    # Фильтры после склейки видят раздельные билеты
    assert apply_filters([m], FilterSettings()) == []


def test_merge_normalizes_flight_number_dashes():
    a = offer(14355, source="aviasales_api", flights=["UJ707"])
    b = offer(14306, source="tutu", flights=["UJ–707"])
    assert len(merge_duplicates([a, b])) == 1


def test_second_merge_keeps_alt_links():
    a = offer(20000, source="kupibilet", flights=["PC5091"])
    b = offer(21000, source="tutu", flights=["PC5091"])
    once = merge_duplicates([a, b])
    twice = merge_duplicates(once)
    assert twice[0].alt_links == [("tutu", 21000, b.link)]


def test_merge_keeps_cheapest_and_alt_links():
    a = offer(20000, source="aviasales", flights=["SU1840"])
    b = offer(19000, source="tbank", flights=["SU 1840"])
    c = offer(25000, source="yandex", flights=["SU1840"])
    other = offer(15000, source="aviasales", flights=["ZF702"], dep=T0 + timedelta(days=1))
    res = merge_duplicates([a, b, c, other])
    assert [o.price_rub for o in res] == [15000, 19000]
    assert res[1].source == "tbank"
    assert [x[0] for x in res[1].alt_links] == ["aviasales", "yandex"]
