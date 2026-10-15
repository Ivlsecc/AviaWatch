"""Общее для источников из публичных Telegram-каналов.

Читаем открытую веб-версию канала t.me/s/<канал> (без входа и без капчи),
листаем историю параметром ?before=<id>, кэшируем страницы на 10 минут.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from common.airports import airports
from sources.base import SourceContext, SourceError

PAGE_URL = "https://t.me/s/{channel}"
CACHE_TTL_S = 10 * 60

MONTHS_GEN = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

# Название в посте → (код аэропорта или города, код города). Неизвестные ищем в справочнике.
PLACES: dict[str, tuple[str, str]] = {
    "ХУРГАДА": ("HRG", "HRG"),
    "ШАРМ": ("SSH", "SSH"),
    "ШАРМ-ЭЛЬ-ШЕЙХ": ("SSH", "SSH"),
    "ШАРМ ЭЛЬ ШЕЙХ": ("SSH", "SSH"),
    "ШАРМ-ЭШ-ШЕЙХ": ("SSH", "SSH"),
    "ШАРМ ЭШ ШЕЙХ": ("SSH", "SSH"),
    "КАИР": ("CAI", "CAI"),
    "АЛЕКСАНДРИЯ": ("HBE", "ALY"),
    "АСУАН": ("ASW", "ASW"),
    "АСТРАХАНЬ": ("ASF", "ASF"),
    "ЛУКСОР": ("LXR", "LXR"),
    "МАРСА-АЛАМ": ("RMF", "RMF"),
    "ЭЛЬ-ДАБАА": ("DBB", "DBB"),
    "ЭЛЬ-АЛАМЕЙН": ("DBB", "DBB"),
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

# Кэш страниц канала: несколько запросов одного поиска не дёргают t.me повторно
_CACHE: dict[str, tuple[float, list["Post"]]] = {}


@dataclass
class Post:
    id: int
    posted_at: datetime
    text: str


def resolve_place(name: str) -> tuple[str, str] | None:
    """(код аэропорта/города, код города) по названию из поста."""
    key = re.sub(r"\s+", " ", name.strip().upper().replace("Ё", "Е")).strip("#:")
    if found := PLACES.get(key) or PLACES.get(key.replace(" ", "")):
        return found
    if code := airports.code_by_name(key):
        return code, airports.city(code)
    return None


def infer_day(day: int, month: int, posted: date) -> date | None:
    try:
        d = date(posted.year, month, day)
    except ValueError:
        return None
    # Даты в постах без года: декабрьский пост про «05.01» — это уже следующий год
    if d < posted - timedelta(days=31):
        d = date(posted.year + 1, month, day)
    return d


def parse_channel_html(page: str, channel: str) -> list[Post]:
    posts = []
    for block in re.split(r'(?=<div class="tgme_widget_message_wrap)', page)[1:]:
        pid = re.search(rf'data-post="{re.escape(channel)}/(\d+)"', block, re.I)
        when = re.search(r'<time datetime="([^"]+)"', block)
        body = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        if not (pid and when and body):
            continue
        text = re.sub(r"<br\s*/?>", "\n", body.group(1))
        # Внешние ссылки заменяем адресом (он важнее подписи), а хэштеги (#Москва → href="?q=…") — их текстом
        text = re.sub(
            r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            lambda m: m.group(1) if m.group(1).startswith("http") else m.group(2),
            text,
            flags=re.S,
        )
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
        posts.append(Post(int(pid.group(1)), datetime.fromisoformat(when.group(1)), text))
    return posts


async def fetch_posts(ctx: SourceContext, channel: str, pages: int) -> list[Post]:
    key = f"{channel}:{pages}"
    if (cached := _CACHE.get(key)) and time.monotonic() - cached[0] < CACHE_TTL_S:
        return cached[1]
    await airports.ensure_loaded(ctx.http)
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
