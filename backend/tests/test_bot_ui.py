from datetime import date, datetime, timezone

from bot import keyboards as kb
from bot.filters_logic import toggle
from bot.fmt import plural, results_text, rub
from common.models import Subscription
from search.analytics import PriceStats
from search.filters import FilterSettings
from search.orchestrator import SearchResult, SourceStatus
from search.routes import RouteRequest
from sources.base import FlightOffer, SearchQuery

REQ = RouteRequest(origins=["HRG", "SSH"], destinations=["MOW"], origin_names=["Хургада", "Шарм-эль-Шейх"],
                   destination_names=["Москва"], date_from=date(2026, 11, 20), date_to=date(2026, 11, 25), adults=2)


def _offers(n):
    dep = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)
    return [
        FlightOffer(source="aviasales_api", price_rub=30000 + i * 1000, origin_airport="HRG", destination_airport="SVO",
                    departure_at=dep, duration_min=405, transfers=1, route_airports=["HRG", "SAW", "SVO"],
                    flight_numbers=[f"PC{i}"], link=f"https://www.aviasales.ru/x?a={i}&b=<1>")
        for i in range(n)
    ]


def _all_buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


def test_callback_data_fits_telegram_limit():
    sub = Subscription(id=123456, origin="HRG", destination="MOW", date_from=date(2026, 11, 20),
                       date_to=date(2026, 11, 25), is_active=True, last_min_price=30000)
    markups = [
        kb.main_menu(), kb.calendar_kb(2026, 11, date(2026, 10, 15), date(2026, 11, 20)), kb.passengers(2, 1, 1),
        kb.summary(False), kb.filters(FilterSettings(), "wiz"), kb.filters(FilterSettings(), "menu"),
        kb.results(3, 40, 123456), kb.subs_list([sub]), kb.sub_card(sub), kb.alert(123456), kb.confirm_delete(123456),
    ]
    for m in markups:
        for b in _all_buttons(m):
            if b.callback_data:
                assert len(b.callback_data.encode()) <= 64, b.callback_data


def test_calendar_hides_past_days():
    m = kb.calendar_kb(2026, 10, date(2026, 10, 15), None)
    texts = [b.text for b in _all_buttons(m)]
    assert "14" not in texts and "15" in texts and "·" in texts


def test_results_text_pagination_and_escaping():
    result = SearchResult(SearchQuery(origin="HRG", destination="MOW", date_from=REQ.date_from, date_to=REQ.date_to),
                          _offers(7), 7, [SourceStatus("aviasales_api", True, 7)])
    stats = PriceStats(mean=18000, median=17500, days=30, past_days=0, window_from=date(2026, 9, 15),
                       window_to=date(2026, 11, 14))
    text = results_text(REQ, result, stats, page=1)
    assert "Хургада / Шарм-эль-Шейх → Москва" in text
    assert "6. <b>35" in text and "7. <b>36" in text and "1. <b>" not in text
    assert "Показано 6–7 из 7" in text
    assert "1 пересадка (SAW)" in text and "6 ч 45 мин" in text
    assert "&amp;b=&lt;1&gt;" in text  # ссылка экранирована
    assert "История за прошлые дни ещё копится" in text
    assert "на 2 пасс." in text
    assert "ниже средней" in text  # 30000/2 = 15000 < 18000


def test_results_markup_navigation():
    labels = [b.text for b in _all_buttons(kb.results(0, 12))]
    assert "Показать ещё ▸" in labels and "◂ Назад" not in labels and "🔔 Следить за ценой" in labels
    labels = [b.text for b in _all_buttons(kb.results(2, 12, subscribed_id=5))]
    assert "Показать ещё ▸" not in labels and "⚙️ Настроить уведомления" in labels


def test_filter_toggles_cycle():
    f = FilterSettings()
    assert toggle(f, "transfers").max_transfers == 2
    assert toggle(toggle(toggle(f, "transfers"), "transfers"), "transfers").max_transfers == 0
    assert toggle(f, "duration").max_duration_factor == 3.0
    assert toggle(f, "airport").exclude_airport_change is False
    assert toggle(f, "layover").min_layover_min == 45
    assert toggle(f.model_copy(update={"max_transfers": 3}), "reset") == FilterSettings()


def test_formatting_helpers():
    assert rub(16645) == "16 645 ₽"
    assert [plural(n, "день", "дня", "дней") for n in (1, 2, 5, 11, 21, 22)] == ["день", "дня", "дней", "дней", "день", "дня"]
