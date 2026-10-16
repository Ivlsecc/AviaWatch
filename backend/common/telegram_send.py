"""Отправка сообщений через Bot API без aiogram — для рассылок из админки."""

from __future__ import annotations

import urllib.request

import httpx

from common.config import get_settings


def telegram_proxy(explicit: str | None = None) -> str | None:
    """Прокси до api.telegram.org: явный из .env или системный (VPN-клиент)."""
    explicit = explicit if explicit is not None else get_settings().telegram_proxy
    if explicit:
        return explicit
    return urllib.request.getproxies().get("https") or None


class TelegramSender:
    def __init__(self) -> None:
        s = get_settings()
        self.url = f"https://api.telegram.org/bot{s.bot_token}"
        proxy = telegram_proxy()
        self.http = httpx.AsyncClient(proxy=proxy, timeout=20)
        # Запасной маршрут, если прокси (VPN) недоступен — как у бота (bot/session.py)
        self.direct = httpx.AsyncClient(timeout=20) if proxy else None

    async def send(self, chat_id: int, text: str) -> tuple[bool, str | None]:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        try:
            resp = await self.http.post(f"{self.url}/sendMessage", json=payload)
        except (httpx.ConnectError, httpx.ProxyError):
            # Соединение не установилось — сообщение точно не ушло, повтор безопасен
            if self.direct is None:
                raise
            self.http, self.direct = self.direct, self.http
            resp = await self.http.post(f"{self.url}/sendMessage", json=payload)
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if body.get("ok"):
            return True, None
        return False, body.get("description") or f"HTTP {resp.status_code}"

    async def close(self) -> None:
        await self.http.aclose()
        if self.direct is not None:
            await self.direct.aclose()
