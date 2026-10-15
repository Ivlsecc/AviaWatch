"""Рекомендация «покупать сейчас или подождать».

Простая прозрачная эвристика — каждый фактор даёт очки и человекочитаемую причину:
• где лучшая цена относительно медианы и нижней четверти цен по маршруту;
• сколько дней до вылета (чем ближе, тем рискованнее ждать);
• куда движется цена на ваши даты в последние дни.
Итог: buy / wait / neutral + уверенность (мало данных → низкая).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from search.analytics import PriceStats
from search.history import Trend

BUY, WAIT, NEUTRAL = "buy", "wait", "neutral"


@dataclass
class Recommendation:
    verdict: str
    score: int
    reasons: list[str] = field(default_factory=list)
    low_confidence: bool = False

    @property
    def emoji(self) -> str:
        return {BUY: "🟢", WAIT: "🟡", NEUTRAL: "⚪"}[self.verdict]

    @property
    def title(self) -> str:
        return {
            BUY: "Стоит покупать",
            WAIT: "Можно подождать",
            NEUTRAL: "Цена обычная",
        }[self.verdict]


def recommend(
    best_per_pax: int | None,
    stats: PriceStats | None,
    trend: Trend | None,
    departure: date,
    today: date | None = None,
) -> Recommendation | None:
    if best_per_pax is None:
        return None
    today = today or date.today()
    days_left = (departure - today).days
    score = 0
    reasons: list[str] = []

    # 1. Цена относительно рынка
    ref = stats.median if stats and stats.median else None
    if ref:
        rel = (best_per_pax - ref) / ref * 100
        if stats.p25 and best_per_pax <= stats.p25:
            score += 30
            reasons.append(f"цена в нижней четверти по маршруту ({abs(rel):.0f}% ниже обычной)")
        elif rel <= -8:
            score += 20
            reasons.append(f"на {abs(rel):.0f}% дешевле обычной цены")
        elif rel >= 20:
            score -= 25
            reasons.append(f"на {rel:.0f}% дороже обычной цены")
        elif rel >= 8:
            score -= 12
            reasons.append(f"на {rel:.0f}% дороже обычной цены")
        else:
            reasons.append("цена около обычной для маршрута")

    # 2. Сколько осталось до вылета
    if days_left <= 3:
        score += 35
        reasons.append(f"до вылета {days_left} дн. — дальше обычно только дороже")
    elif days_left <= 10:
        score += 20
        reasons.append(f"до вылета {days_left} дн. — ждать рискованно")
    elif days_left <= 21:
        score += 8
    elif days_left > 60:
        score -= 8
        reasons.append(f"до вылета ещё {days_left} дн. — время на ожидание есть")

    # 3. Тренд на ваши даты
    change = trend.change_pct if trend else None
    if change is not None:
        if change <= -5:
            score -= 15 if days_left > 10 else 5
            reasons.append(f"за {trend.days} дн. цена снизилась на {abs(change):.0f}% — возможно, будет ещё ниже")
        elif change >= 5:
            score += 15
            reasons.append(f"за {trend.days} дн. цена выросла на {change:.0f}%")

    if score >= 15:
        verdict = BUY
    elif score <= -12:
        verdict = WAIT
    else:
        verdict = NEUTRAL

    low_conf = not ref or (stats.days < 10) or change is None
    return Recommendation(verdict, score, reasons, low_conf)
