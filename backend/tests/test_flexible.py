from datetime import date, timedelta

from bot import keyboards as kb
from bot.callbacks import Flex
from search.flexible import flexible_hint, pick_hint

D = date(2026, 11, 20)


def test_pick_hint_needs_real_saving():
    assert pick_hint({D: 19000}, 20000) is None  # 5% — мало
    hint = pick_hint({D: 17000, D + timedelta(days=1): 17000, D - timedelta(days=2): 18000}, 20000)
    assert hint.day == D and hint.saving_per_pax == 3000 and round(hint.saving_pct) == 15
    assert pick_hint({}, 20000) is None


class FakeSvc:
    def __init__(self, prices):
        self.prices = prices
        self.calls = []

    async def calendar(self, origin, destination, date_from, date_to):
        self.calls.append((origin, destination, date_from, date_to))
        return {d: p for d, p in self.prices.items() if date_from <= d <= date_to}


async def test_flexible_hint_looks_around_and_skips_chosen_dates():
    prices = {D - timedelta(days=4): 1000, D - timedelta(days=2): 15000, D: 9000, D + timedelta(days=3): 17000}
    svc = FakeSvc(prices)
    hint = await flexible_hint(svc, ["HRG", "SSH"], ["MOW"], D, D, best_per_pax=20000, today=date(2026, 10, 1))
    # D-4 вне окна ±3, сам D — выбранная дата, лучший вариант рядом — D-2
    assert hint.day == D - timedelta(days=2) and hint.price_per_pax == 15000
    assert {c[:2] for c in svc.calls} == {("HRG", "MOW"), ("SSH", "MOW")}
    # Окно не уходит в прошлое
    await flexible_hint(svc, ["HRG"], ["MOW"], D, D, best_per_pax=20000, today=D - timedelta(days=1))
    assert svc.calls[-1][2] == D - timedelta(days=1)


def test_flex_button_in_results_keyboard():
    markup = kb.results(0, 10, None, D)
    first = markup.inline_keyboard[0][0]
    assert first.callback_data == Flex(y=2026, m=11, d=20).pack() and "20.11" in first.text
