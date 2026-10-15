"""Справочник аэропортов Travelpayouts: часовой пояс, код города, название.

Нужен источникам, которые отдают местное время без смещения (OneTwoTrip), и для
сопоставления «аэропорт ↔ город» (VKO входит в MOW). Скачивается один раз и
кэшируется на диске; при недоступности сети работает встроенный минимум.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

AIRPORTS_URL = "https://api.travelpayouts.com/data/ru/airports.json"
CITIES_URL = "https://api.travelpayouts.com/data/ru/cities.json"
CACHE_FILE = Path(__file__).resolve().parent.parent / ".cache" / "airports.json"
CITIES_CACHE_FILE = CACHE_FILE.with_name("cities.json")


# При одинаковых названиях городов предпочитаем «наши» страны: Александрия — египетская, а не канадская
COUNTRY_PRIORITY = ["RU", "EG", "TR", "AE", "AM", "GE", "KZ", "UZ", "BY", "AZ", "TH", "VN", "CN", "IN", "LK", "MV", "TN", "CY", "GR"]


def normalize_name(name: str) -> str:
    return " ".join(name.upper().replace("Ё", "Е").replace("-", " ").split())

# code → (city_code, time_zone, name). Минимум для оффлайна и тестов.
BUILTIN: dict[str, tuple[str, str, str]] = {
    "HRG": ("HRG", "Africa/Cairo", "Хургада"),
    "SSH": ("SSH", "Africa/Cairo", "Шарм-эль-Шейх"),
    "CAI": ("CAI", "Africa/Cairo", "Каир"),
    "SVO": ("MOW", "Europe/Moscow", "Шереметьево"),
    "VKO": ("MOW", "Europe/Moscow", "Внуково"),
    "DME": ("MOW", "Europe/Moscow", "Домодедово"),
    "ZIA": ("MOW", "Europe/Moscow", "Жуковский"),
    "MOW": ("MOW", "Europe/Moscow", "Москва"),
    "LED": ("LED", "Europe/Moscow", "Пулково"),
    "IST": ("IST", "Europe/Istanbul", "Стамбул"),
    "SAW": ("IST", "Europe/Istanbul", "Сабиха Гёкчен"),
    "AYT": ("AYT", "Europe/Istanbul", "Анталья"),
}


class Airports:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, str, str]] = dict(BUILTIN)
        self._by_name: dict[str, str] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    def set_data(self, data: dict[str, tuple[str, str, str]], names: dict[str, str] | None = None) -> None:
        self._data = {**BUILTIN, **data}
        self._by_name = {normalize_name(k): v for k, v in (names or {}).items()}
        self._loaded = True

    async def _fetch(self, url: str, cache: Path, http: httpx.AsyncClient | None) -> list | None:
        if cache.exists():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except ValueError:
                pass
        own = http is None
        http = http or httpx.AsyncClient()
        try:
            resp = await http.get(url, timeout=60)
            resp.raise_for_status()
            raw = resp.json()
        finally:
            if own:
                await http.aclose()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return raw

    async def ensure_loaded(self, http: httpx.AsyncClient | None = None) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            try:
                raw = await self._fetch(AIRPORTS_URL, CACHE_FILE, http)
                cities = await self._fetch(CITIES_URL, CITIES_CACHE_FILE, http)
            except Exception:  # noqa: BLE001 — без справочника работаем на встроенном минимуме
                log.warning("Справочник аэропортов недоступен, используется встроенный минимум")
                self._loaded = True
                return
            for a in raw or []:
                if a.get("code") and a.get("time_zone"):
                    self._data[a["code"]] = (a.get("city_code") or a["code"], a["time_zone"], a.get("name") or a["code"])
            ranked: dict[str, tuple[int, str]] = {}
            for c in cities or []:
                if not (c.get("code") and c.get("name")):
                    continue
                cc = c.get("country_code") or ""
                rank = COUNTRY_PRIORITY.index(cc) if cc in COUNTRY_PRIORITY else len(COUNTRY_PRIORITY)
                key = normalize_name(c["name"])
                if key not in ranked or rank < ranked[key][0]:
                    ranked[key] = (rank, c["code"])
            for key, (_, code) in ranked.items():
                self._by_name.setdefault(key, code)
            self._loaded = True

    def code_by_name(self, name: str) -> str | None:
        """Код города по русскому названию («Эль-Дабаа» → DBB)."""
        return self._by_name.get(normalize_name(name))

    def tz(self, code: str) -> str | None:
        item = self._data.get(code)
        return item[1] if item else None

    def city(self, code: str) -> str:
        item = self._data.get(code)
        return item[0] if item else code

    def name(self, code: str) -> str:
        item = self._data.get(code)
        return item[2] if item else code

    def matches(self, code: str, wanted: str) -> bool:
        """Аэропорт code подходит под запрос wanted (код аэропорта или города)."""
        return code == wanted or self.city(code) == wanted


airports = Airports()
