"""Поиск городов и аэропортов по названию (Travelpayouts autocomplete, без токена)."""

from __future__ import annotations

import httpx
from pydantic import BaseModel

AUTOCOMPLETE_URL = "https://autocomplete.travelpayouts.com/places2"


class Place(BaseModel):
    code: str
    name: str
    type: str  # city | airport
    country: str = ""
    city_name: str | None = None

    @property
    def label(self) -> str:
        if self.type == "airport":
            return f"✈️ {self.name} ({self.code}), {self.city_name or self.country}"
        return f"🏙 {self.name} ({self.code}), {self.country} — все аэропорты"


async def find_places(term: str, http: httpx.AsyncClient | None = None, limit: int = 6) -> list[Place]:
    term = term.strip()
    if len(term) < 2:
        return []
    params = {"term": term, "locale": "ru", "types[]": ["city", "airport"]}
    own = http is None
    http = http or httpx.AsyncClient()
    try:
        resp = await http.get(AUTOCOMPLETE_URL, params=params, timeout=10)
        resp.raise_for_status()
        items = resp.json()
    finally:
        if own:
            await http.aclose()

    places = []
    for it in items:
        if not it.get("code") or it.get("type") not in ("city", "airport"):
            continue
        places.append(
            Place(
                code=it["code"],
                name=it.get("name") or it["code"],
                type=it["type"],
                country=it.get("country_name") or "",
                city_name=it.get("city_name"),
            )
        )
    return places[:limit]
