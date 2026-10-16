"""Горящие чартеры в Египет из Telegram-канала t.me/ticket_egypt.

Канал публикует самые дешёвые чартеры из выдачи Aviasales — их легко пропустить,
потому что цена держится считанные часы. Формат:

    🔥 Чартер #Самара → Шарм-эш-Шейх:
    🔥11 сентября - 6794 руб. с багажом 10кг - https://avs.io/Zz1Y
    🔥 Санкт-Петербург — Луксор с одной пересадкой:
    🔥6 ноября - 13368 руб. с ручной кладью - https://avs.io/12N2H

Маршруты «туда-обратно» (три города в заголовке) пропускаем. Цены за 1 пассажира.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sources.base import FlightOffer, SearchQuery, Source, SourceContext
from sources.registry import register
from sources.telegram import MONTHS_GEN, Post, fetch_posts, infer_day, resolve_place

CHANNEL = "ticket_egypt"

# «🔥 Чартер #Самара → Шарм:», «🔥 Прямой #Краснодар → Хургада:», «🆕 Новое направление! Чартер #Москва → Эль-Дабаа:»
HEADER_RE = re.compile(
    r"^[^\wА-ЯЁа-яё#]*(?:.*?!\s*)?(?:(?:Чартер|Прямой|Регулярный|Рейс)\s+)?#?(?P<route>[^:!]+?)"
    r"(?P<tail>\s+с\s+\w+\s+пересадк\w+)?\s*:\s*$",
    re.I,
)
ARROW_RE = re.compile(r"\s*(?:→|->|—|–)\s*")
FARE_RE = re.compile(
    r"^\W*(?P<d>\d{1,2})\s+(?P<m>[а-яё]+)\s*[-–—]\s*(?P<price>\d[\d\s]*)\s*руб\.?\s*(?P<rest>.*)$", re.I
)
BAG_RE = re.compile(r"багаж\w*\s+(\d+)\s*кг", re.I)
LINK_RE = re.compile(r"https?://\S+")


@dataclass
class Deal:
    origin: str
    origin_city: str
    destination: str
    destination_city: str
    transfers: int
    day: date
    price: int
    baggage_kg: int | None
    link: str | None
    post_id: int
    posted_at: datetime


@register
class TicketEgyptSource(Source):
    name = "ticket_egypt"
    title = "Горящие чартеры ticket_egypt"
    method = "json"
    may_be_empty = True
    param_schema = {
        "channel": f"Username канала (по умолчанию {CHANNEL})",
        "pages": "Сколько страниц истории читать, по 20 постов (по умолчанию 3)",
        "max_age_days": "Не учитывать посты старше N дней (по умолчанию 7)",
    }

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        channel = ctx.params.get("channel") or CHANNEL
        posts = await fetch_posts(ctx, channel, int(ctx.params.get("pages", 3)))
        max_age = timedelta(days=int(ctx.params.get("max_age_days", 7)))
        now = datetime.now(timezone.utc)
        deals = latest_deals(p for p in posts if now - p.posted_at <= max_age)
        return [
            to_offer(d, query, channel)
            for d in deals
            if query.origin in (d.origin, d.origin_city)
            and query.destination in (d.destination, d.destination_city)
            and query.date_from <= d.day <= query.date_to
        ]


def parse_post(post: Post) -> list[Deal]:
    deals: list[Deal] = []
    route = None
    for line in post.text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if (m := FARE_RE.match(line)) and route:
            month = MONTHS_GEN.get(m.group("m").lower())
            # «24 сентября - 4 октября - 18854 руб.» — туда-обратно, FARE_RE не совпадёт с ценой; пропускаем
            if not month:
                continue
            day = infer_day(int(m.group("d")), month, post.posted_at.date())
            if day is None:
                continue
            (o, oc), (d, dc), transfers = route
            rest = m.group("rest")
            bag = BAG_RE.search(rest)
            link = LINK_RE.search(rest)
            deals.append(
                Deal(o, oc, d, dc, transfers, day, int(re.sub(r"\s", "", m.group("price"))),
                     int(bag.group(1)) if bag else (0 if "ручн" in rest.lower() else None),
                     link.group(0) if link else None, post.id, post.posted_at)
            )
            continue
        if line.endswith(":") and (h := HEADER_RE.match(line)):
            cities = [c for c in ARROW_RE.split(h.group("route").strip()) if c]
            if len(cities) != 2:  # туда-обратно или мусор
                route = None
                continue
            a, b = resolve_place(cities[0]), resolve_place(cities[1])
            transfers = 1 if h.group("tail") else 0
            route = (a, b, transfers) if a and b else None
    return deals


def latest_deals(posts) -> list[Deal]:
    latest: dict[tuple, Deal] = {}
    for post in sorted(posts, key=lambda p: p.id):
        for d in parse_post(post):
            latest[(d.origin, d.destination, d.day, d.transfers)] = d
    return list(latest.values())


def to_offer(d: Deal, query: SearchQuery, channel: str) -> FlightOffer:
    notes = ["горящее предложение из Telegram, цена держится недолго"]
    if d.baggage_kg:
        notes.append(f"багаж {d.baggage_kg} кг")
    elif d.baggage_kg == 0:
        notes.append("только ручная кладь")
    posted = d.posted_at.astimezone(timezone(timedelta(hours=3)))
    notes.append(f"пост {posted:%d.%m %H:%M} МСК")
    return FlightOffer(
        source="ticket_egypt",
        price_rub=d.price * max(query.passengers, 1),
        price_original=float(d.price),
        origin_airport=d.origin,
        destination_airport=d.destination,
        departure_at=datetime(d.day.year, d.day.month, d.day.day, 12, 0, tzinfo=timezone.utc),
        time_known=False,
        transfers=d.transfers,
        route_airports=[d.origin, d.destination] if not d.transfers else [],
        baggage_included=(d.baggage_kg or 0) > 0 if d.baggage_kg is not None else None,
        link=d.link or f"https://t.me/{channel}/{d.post_id}",
        note="; ".join(notes),
    )
