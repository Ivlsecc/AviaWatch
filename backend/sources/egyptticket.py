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

import html
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sources.base import FlightOffer, SearchQuery, Source, SourceContext, SourceError
from sources.registry import register

CHANNEL = "egyptticket"
PAGE_URL = "https://t.me/s/{channel}"

# Название в посте → (код аэропорта или города, код города)
PLACES: dict[str, tuple[str, str]] = {
    "ХУРГАДА": ("HRG", "HRG"),
    "ШАРМ": ("SSH", "SSH"),
    "ШАРМ-ЭЛЬ-ШЕЙХ": ("SSH", "SSH"),
    "ШАРМ ЭЛЬ ШЕЙХ": ("SSH", "SSH"),
    "КАИР": ("CAI", "CAI"),
    "МОСКВА": ("MOW", "MOW"),
    "ВНУКОВО": ("VKO", "MOW"),
    "ДОМОДЕДОВО": ("DME", "MOW"),
    "ШЕРЕМЕТЬЕВО": ("SVO", "MOW"),
    "ЖУКОВСКИЙ": ("ZIA", "MOW"),
    "С.ПЕТЕРБУРГ": ("LED", "LED"),
    "САНКТ-ПЕТЕРБУРГ": ("LED", "LED"),
    "ПЕТЕРБУРГ": ("LED", "LED"),
    "СПБ": ("LED", "LED"),
    "ЕКАТЕРИНБУРГ": ("SVX", "SVX"),
    "Н.НОВГОРОД": ("GOJ", "GOJ"),
    "НИЖНИЙ НОВГОРОД": ("GOJ", "GOJ"),
    "САМАРА": ("KUF", "KUF"),
    "ПЕРМЬ": ("PEE", "PEE"),
    "ЧЕЛЯБИНСК": ("CEK", "CEK"),
    "СОЧИ": ("AER", "AER"),
    "КРАСНОДАР": ("KRR", "KRR"),
    "КАЗАНЬ": ("KZN", "KZN"),
    "ВЛАДИКАВКАЗ": ("OGZ", "OGZ"),
    "УФА": ("UFA", "UFA"),
    "МИН ВОДЫ": ("MRV", "MRV"),
    "МИН.ВОДЫ": ("MRV", "MRV"),
    "МИНЕРАЛЬНЫЕ ВОДЫ": ("MRV", "MRV"),
    "САРАТОВ": ("GSV", "GSV"),
    "НОВОСИБИРСК": ("OVB", "OVB"),
    "РОСТОВ": ("ROV", "ROV"),
    "РОСТОВ-НА-ДОНУ": ("ROV", "ROV"),
    "ВОЛГОГРАД": ("VOG", "VOG"),
    "ТЮМЕНЬ": ("TJM", "TJM"),
    "ОМСК": ("OMS", "OMS"),
    "КРАСНОЯРСК": ("KJA", "KJA"),
    "ИРКУТСК": ("IKT", "IKT"),
    "ВОРОНЕЖ": ("VOZ", "VOZ"),
    "МАХАЧКАЛА": ("MCX", "MCX"),
    "ГРОЗНЫЙ": ("GRV", "GRV"),
    "КАЛИНИНГРАД": ("KGD", "KGD"),
    "ОРЕНБУРГ": ("REN", "REN"),
    "ИЖЕВСК": ("IJK", "IJK"),
}

# Города разделены дефисом С ПРОБЕЛАМИ: «ШАРМ-ЭЛЬ-ШЕЙХ - ВНУКОВО» не режется по дефису в названии
HEADER_RE = re.compile(r"^\s*([А-ЯЁ][А-ЯЁ.\s\-]*?)\s+[-–—]\s+([А-ЯЁ][А-ЯЁ.\s\-]*?)\s*(?:/.*)?$")
FARE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\s*=\s*(\d[\d\s]*?)\s*руб(.*)$", re.I)
BAG_RE = re.compile(r"(\d+)\s*\+\s*(\d+)")
SEATS_RE = re.compile(r"(\d+)\s*мест")

# Кэш страниц канала: несколько запросов одного поиска не дёргают t.me повторно
_CACHE: dict[str, tuple[float, list["Post"]]] = {}
CACHE_TTL_S = 10 * 60


@dataclass
class Post:
    id: int
    posted_at: datetime
    text: str


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


async def fetch_posts(ctx: SourceContext, channel: str, pages: int) -> list[Post]:
    key = f"{channel}:{pages}"
    if (cached := _CACHE.get(key)) and time.monotonic() - cached[0] < CACHE_TTL_S:
        return cached[1]
    posts: dict[int, Post] = {}
    before = None
    for _ in range(max(pages, 1)):
        url = PAGE_URL.format(channel=channel) + (f"?before={before}" if before else "")
        resp = await ctx.http.get(url, timeout=ctx.timeout_s, follow_redirects=False)
        if resp.status_code != 200:
            raise SourceError(f"Telegram: канал {channel} недоступен (HTTP {resp.status_code})")
        page = parse_channel_html(resp.text, channel)
        if not page:
            break
        for p in page:
            posts[p.id] = p
        before = min(p.id for p in page)
    result = sorted(posts.values(), key=lambda p: p.id)
    _CACHE[key] = (time.monotonic(), result)
    return result


def parse_channel_html(page: str, channel: str = CHANNEL) -> list[Post]:
    posts = []
    for block in re.split(r'(?=<div class="tgme_widget_message_wrap)', page)[1:]:
        pid = re.search(rf'data-post="{re.escape(channel)}/(\d+)"', block)
        when = re.search(r'<time datetime="([^"]+)"', block)
        body = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        if not (pid and when and body):
            continue
        text = re.sub(r"<br\s*/?>", "\n", body.group(1))
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
        posts.append(Post(int(pid.group(1)), datetime.fromisoformat(when.group(1)), text))
    return posts


def _place(name: str) -> tuple[str, str] | None:
    key = re.sub(r"\s+", " ", name.strip().upper().replace("Ё", "Е"))
    return PLACES.get(key) or PLACES.get(key.replace(" ", ""))


def _infer_day(day: int, month: int, posted: date) -> date | None:
    try:
        d = date(posted.year, month, day)
    except ValueError:
        return None
    # Даты в постах без года: декабрьский пост про «05.01» — это уже следующий год
    if d < posted - timedelta(days=31):
        d = date(posted.year + 1, month, day)
    return d


def parse_post(post: Post) -> list[CharterFare]:
    fares: list[CharterFare] = []
    route = None
    for line in post.text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if (m := HEADER_RE.match(line)) and "=" not in line:
            a, b = _place(m.group(1)), _place(m.group(2))
            route = (a, b, m.group(1).strip().title(), m.group(2).strip().title()) if a and b else None
            continue
        if route and (m := FARE_RE.match(line)):
            (o, oc), (d, dc), oname, dname = route
            day = _infer_day(int(m.group(1)), int(m.group(2)), post.posted_at.date())
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
