"""Прогресс поиска в сообщении «⏳ Ищу билеты…»: какие источники уже ответили."""

from __future__ import annotations

import time

from aiogram.types import Message

from bot.fmt import source_title
from bot.utils import safe_edit

MIN_EDIT_INTERVAL_S = 1.5  # Telegram не любит частые правки одного сообщения


class SearchProgress:
    def __init__(self, message: Message) -> None:
        self.message = message
        self.total = 0
        self.done: list[tuple[str, bool, int]] = []
        self._last_edit = 0.0

    async def started(self, total: int) -> None:
        # Поиск по нескольким городам — несколько запусков, суммируем
        self.total += total

    async def finished(self, source: str, ok: bool, offers: int) -> None:
        self.done.append((source, ok, offers))
        now = time.monotonic()
        if now - self._last_edit < MIN_EDIT_INTERVAL_S and len(self.done) < self.total:
            return
        self._last_edit = now
        await safe_edit(self.message, self.text())

    def text(self) -> str:
        found = sum(n for _, ok, n in self.done if ok)
        lines = [f"⏳ Ищу билеты… опрошено {len(self.done)} из {self.total} источников, найдено {found} вариантов"]
        merged: dict[str, tuple[bool, int]] = {}
        for src, ok, n in self.done:
            prev_ok, prev_n = merged.get(src, (False, 0))
            merged[src] = (prev_ok or ok, prev_n + n)
        marks = [f"{'✅' if ok else '⚠️'} {source_title(src)}{f' {n}' if ok else ''}" for src, (ok, n) in merged.items()]
        if marks:
            lines.append(" · ".join(marks))
        return "\n".join(lines)
