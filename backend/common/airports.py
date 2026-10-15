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
CACHE_FILE = Path(__file__).resolve().parent.parent / ".cache" / "airports.json"

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
        self._loaded = False
        self._lock = asyncio.Lock()

    def set_data(self, data: dict[str, tuple[str, str, str]]) -> None:
        self._data = {**BUILTIN, **data}
        self._loaded = True

    async def ensure_loaded(self, http: httpx.AsyncClient | None = None) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            raw = None
            if CACHE_FILE.exists():
                try:
                    raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                except ValueError:
                    raw = None
            if raw is None:
                try:
                    own = http is None
                    http = http or httpx.AsyncClient()
                    try:
                        resp = await http.get(AIRPORTS_URL, timeout=60)
                        resp.raise_for_status()
                        raw = resp.json()
                    finally:
                        if own:
                            await http.aclose()
                    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    CACHE_FILE.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
                except Exception:  # noqa: BLE001 — без справочника работаем на встроенном минимуме
                    log.warning("Справочник аэропортов недоступен, используется встроенный минимум")
                    self._loaded = True
                    return
            for a in raw:
                if a.get("code") and a.get("time_zone"):
                    self._data[a["code"]] = (a.get("city_code") or a["code"], a["time_zone"], a.get("name") or a["code"])
            self._loaded = True

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
