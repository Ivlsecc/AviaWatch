"""Автопроверка источников на контрольном маршруте.

Сайты иногда меняют формат ответа — парсер тогда не падает, а тихо отдаёт ноль
вариантов, и источник просто пропадает из выдачи. Раз в несколько часов ищем
контрольный маршрут через все включённые источники и пишем админу, если какой-то
сломался или замолчал (и когда починился).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from html import escape

from common.config import get_settings
from search.orchestrator import SearchService, SourceStatus
from sources.base import SearchQuery
from sources.registry import all_sources

log = logging.getLogger(__name__)

# Отправка сообщения админу
AdminHook = Callable[[str], Awaitable[None]]

# Через сколько дней после «сегодня» ищем контрольный маршрут и на сколько дней
ROUTE_OFFSET_DAYS = 7
ROUTE_SPAN_DAYS = 2
FIRST_RUN_DELAY_S = 5 * 60


def find_problems(statuses: list[SourceStatus]) -> dict[str, str]:
    """Источник → что с ним не так."""
    sources = all_sources()
    problems: dict[str, str] = {}
    for st in statuses:
        cls = sources.get(st.source)
        if cls is None:
            continue
        title = cls.title
        if st.skipped:
            problems[st.source] = f"{title}: отключён после серии ошибок"
        elif not st.ok:
            problems[st.source] = f"{title}: ошибка — {(st.error or 'без текста')[:200]}"
        elif st.offers == 0 and not cls.may_be_empty:
            problems[st.source] = f"{title}: 0 вариантов — возможно, сайт поменял формат"
    return problems


def report(problems: dict[str, str], previous: dict[str, str] | None, route: str) -> str | None:
    """Текст для админа или None, если писать не о чем. Пишем только об изменениях."""
    previous = previous or {}
    new = {k: v for k, v in problems.items() if k not in previous}
    fixed = [k for k in previous if k not in problems]
    if not new and not fixed:
        return None
    sources = all_sources()
    lines = [f"🩺 <b>Проверка источников</b> · {escape(route)}"]
    if new:
        lines += ["", "Сломались:"] + [f"🔴 {escape(v)}" for v in new.values()]
    if fixed:
        lines += ["", "Снова работают:"] + [f"🟢 {escape(sources[k].title if k in sources else k)}" for k in fixed]
    if still := [v for k, v in problems.items() if k in previous]:
        lines += ["", "Всё ещё не работают:"] + [f"• {escape(v)}" for v in still]
    return "\n".join(lines)


class SourceHealthMonitor:
    def __init__(self, svc: SearchService, notify_admin: AdminHook) -> None:
        self.svc = svc
        self.notify_admin = notify_admin
        self.settings = get_settings()
        self._previous: dict[str, str] | None = None

    def query(self, today: date | None = None) -> SearchQuery:
        origin, _, destination = self.settings.health_route.partition("-")
        start = (today or date.today()) + timedelta(days=ROUTE_OFFSET_DAYS)
        return SearchQuery(origin=origin, destination=destination, date_from=start,
                           date_to=start + timedelta(days=ROUTE_SPAN_DAYS))

    async def run_forever(self) -> None:
        hours = self.settings.health_check_hours
        if hours <= 0:
            return
        await asyncio.sleep(FIRST_RUN_DELAY_S)
        while True:
            try:
                await self.check()
            except Exception:  # noqa: BLE001
                log.exception("source health check failed")
            await asyncio.sleep(hours * 3600)

    async def check(self, today: date | None = None) -> dict[str, str]:
        result = await self.svc.search(self.query(today), use_cache=False, log_search=False)
        problems = find_problems(result.statuses)
        log.info("source health: %d problem(s) %s", len(problems), sorted(problems))
        text = report(problems, self._previous, self.settings.health_route)
        self._previous = problems
        if text:
            await self.notify_admin(text)
        return problems
