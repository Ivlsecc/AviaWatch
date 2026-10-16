"""Чартеры «только перелёт» из Telegram-канала Egypt-Ticket (t.me/egyptticket).

Продавец публикует места в чартерных блоках в почти машинном формате:

    ХУРГАДА - ВНУКОВО/рег.блок
    19.10 = 12000 руб 20+5
    25.10 = 21850 руб 10+5 ПРОДАНО
    22.10 = 28100 руб 30+8/ бизнес/ 1 место

Читаем открытую веб-версию канала t.me/s/<канал> — без входа и без капчи.
Бронирование — через продавца (WhatsApp/Telegram), поэтому ссылка ведёт на пост.
Цены за одного пассажира; время вылета в постах не указано.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sources.base import FlightOffer, SearchQuery, Source, SourceContext
from sources.registry import register
from sources import telegram
from sources.telegram import _CACHE, PAGE_URL, Post, fetch_posts, infer_day, resolve_place  # noqa: F401

CHANNEL = "egyptticket"

# Города разделены дефисом С ПРОБЕЛАМИ: «ШАРМ-ЭЛЬ-ШЕЙХ - ВНУКОВО» не режется по дефису в названии
HEADER_RE = re.compile(r"^\s*([А-ЯЁ][А-ЯЁ.\s\-]*?)\s+[-–—]\s+([А-ЯЁ][А-ЯЁ.\s\-]*?)\s*(?:/.*)?$")
FARE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\s*=\s*(\d[\d\s]*?)\s*руб(.*)$", re.I)
BAG_RE = re.compile(r"(\d+)\s*\+\s*(\d+)")
SEATS_RE = re.compile(r"(\d+)\s*мест")


def parse_channel_html(page: str, channel: str = CHANNEL) -> list[Post]:
    return telegram.parse_channel_html(page, channel)


@dataclass
class CharterFare:
    origin: str  # аэропорт/город из PLACES
    origin_city: str
    destination: str
    destination_city: str
    origin_name: str
    destination_name: str
    day: date
    price: int  # за одного пассажира
    baggage_kg: int | None
    hand_kg: int | None
    seats_left: int | None
    business: bool
    sold_out: bool
    post_id: int
    posted_at: datetime


@register
class EgyptTicketSource(Source):
    name = "egyptticket"
    title = "Чартеры Egypt-Ticket"
    method = "json"
    may_be_empty = True
    param_schema = {
        "channel": f"Username канала (по умолчанию {CHANNEL})",
        "pages": "Сколько страниц истории читать, по 20 постов (по умолчанию 3)",
        "max_age_days": "Не учитывать посты старше N дней (по умолчанию 10)",
    }

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        channel = ctx.params.get("channel") or CHANNEL
        posts = await fetch_posts(ctx, channel, int(ctx.params.get("pages", 3)))
        max_age = timedelta(days=int(ctx.params.get("max_age_days", 10)))
        now = datetime.now(timezone.utc)
        fares = latest_fares(p for p in posts if now - p.posted_at <= max_age)
        return [
            to_offer(f, query, channel)
            for f in fares
            if not f.sold_out
            and query.origin in (f.origin, f.origin_city)
            and query.destination in (f.destination, f.destination_city)
            and query.date_from <= f.day <= query.date_to
        ]


def parse_post(post: Post) -> list[CharterFare]:
    fares: list[CharterFare] = []
    route = None
    for line in post.text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if (m := HEADER_RE.match(line)) and "=" not in line:
            a, b = resolve_place(m.group(1)), resolve_place(m.group(2))
            route = (a, b, m.group(1).strip().title(), m.group(2).strip().title()) if a and b else None
            continue
        if route and (m := FARE_RE.match(line)):
            (o, oc), (d, dc), oname, dname = route
            day = infer_day(int(m.group(1)), int(m.group(2)), post.posted_at.date())
            if day is None:
                continue
            rest = m.group(4)
            bag = BAG_RE.search(rest)
            seats = SEATS_RE.search(rest)
            fares.append(
                CharterFare(
                    origin=o, origin_city=oc, destination=d, destination_city=dc,
                    origin_name=oname, destination_name=dname, day=day,
                    price=int(re.sub(r"\s", "", m.group(3))),
                    baggage_kg=int(bag.group(1)) if bag else None,
                    hand_kg=int(bag.group(2)) if bag else None,
                    seats_left=int(seats.group(1)) if seats else None,
                    business="бизнес" in rest.lower(),
                    sold_out="продан" in rest.lower(),
                    post_id=post.id,
                    posted_at=post.posted_at,
                )
            )
    return fares


def latest_fares(posts) -> list[CharterFare]:
    """Для каждой пары «маршрут + дата + класс» — цена из самого свежего поста."""
    latest: dict[tuple, CharterFare] = {}
    for post in sorted(posts, key=lambda p: p.id):
        for f in parse_post(post):
            latest[(f.origin, f.destination, f.day, f.business)] = f
    return list(latest.values())


def to_offer(f: CharterFare, query: SearchQuery, channel: str) -> FlightOffer:
    notes = ["чартер, бронь через продавца"]
    if f.baggage_kg is not None:
        notes.append(f"багаж {f.baggage_kg} кг + ручная кладь {f.hand_kg} кг")
    if f.seats_left:
        notes.append(f"осталось мест: {f.seats_left}")
    if f.business:
        notes.append("бизнес-класс")
    posted = f.posted_at.astimezone(timezone(timedelta(hours=3)))
    notes.append(f"цена из поста {posted:%d.%m %H:%M} МСК")
    return FlightOffer(
        source="egyptticket",
        price_rub=f.price * max(query.passengers, 1),
        price_original=float(f.price),
        origin_airport=f.origin,
        destination_airport=f.destination,
        # Время в постах не указано — ставим полдень UTC, чтобы дата не «съезжала»
        departure_at=datetime(f.day.year, f.day.month, f.day.day, 12, 0, tzinfo=timezone.utc),
        time_known=False,
        transfers=0,
        route_airports=[f.origin, f.destination],
        baggage_included=(f.baggage_kg or 0) > 0 if f.baggage_kg is not None else None,
        self_transfer=False,
        link=f"https://t.me/{channel}/{f.post_id}",
        note="; ".join(notes),
    )
