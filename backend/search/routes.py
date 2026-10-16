"""Маршрут пользователя: несколько городов вылета/прилёта и диапазон дат.

«Хургада или Шарм → Москва» разворачивается в набор SearchQuery, результаты
склеиваются в одну выдачу.
"""

from __future__ import annotations

import asyncio
from datetime import date

from pydantic import BaseModel, Field

from search.dedup import merge_duplicates
from search.filters import FilterSettings, apply_filters
from search.orchestrator import ProgressHook, SearchResult, SearchService, SourceStatus
from search.split import mark_split_prices
from search.verify import verify_cached_prices
from sources.base import SearchQuery


class RouteRequest(BaseModel):
    origins: list[str]
    destinations: list[str]
    origin_names: list[str] = Field(default_factory=list)
    destination_names: list[str] = Field(default_factory=list)
    date_from: date
    date_to: date
    adults: int = 1
    children: int = 0
    infants: int = 0
    direct_only: bool = False

    @property
    def passengers(self) -> int:
        return self.adults + self.children

    def queries(self) -> list[SearchQuery]:
        return [
            SearchQuery(
                origin=o,
                destination=d,
                date_from=self.date_from,
                date_to=self.date_to,
                adults=self.adults,
                children=self.children,
                infants=self.infants,
                direct_only=self.direct_only,
            )
            for o in self.origins
            for d in self.destinations
            if o != d
        ]


async def search_route(
    svc: SearchService,
    req: RouteRequest,
    filters: FilterSettings,
    user_id: int | None = None,
    use_cache: bool = True,
    progress: ProgressHook | None = None,
    split_check: bool = False,
    verify: bool = True,
) -> SearchResult:
    """split_check — дополнительно искать на одного взрослого: вдруг билеты по одному дешевле (search/split.py).
    verify — сверить верхние цены из кэша Aviasales с живыми сайтами (search/verify.py)."""
    queries = req.queries()
    singles: list[SearchQuery] = []
    if split_check and req.adults >= 2 and not req.children and not req.infants:
        singles = [q.model_copy(update={"adults": 1}) for q in queries]
    found = await asyncio.gather(
        *(svc.search(q, filters, user_id, use_cache, progress=progress) for q in queries),
        *(svc.search(q, filters, user_id, use_cache, log_search=False) for q in singles),
    )
    results, single_results = found[: len(queries)], found[len(queries):]

    statuses: dict[str, SourceStatus] = {}
    for r in results:
        for st in r.statuses:
            agg = statuses.setdefault(st.source, SourceStatus(st.source, st.ok, 0, st.error, st.skipped))
            agg.offers += st.offers
            agg.ok = agg.ok or st.ok
    offers = merge_duplicates([o for r in results for o in r.offers])
    if verify:
        offers = await verify_cached_prices(svc, queries, offers, filters, list(statuses.values()))
    if single_results:
        mark_split_prices(offers, merge_duplicates([o for r in single_results for o in r.offers]), req.adults)

    if filters.self_combos:
        combos = await _combos(svc, queries, filters)
        if combos:
            statuses["combo"] = SourceStatus("combo", True, len(combos))
            offers = sorted(offers + combos, key=lambda o: (o.price_rub, o.departure_at))

    return SearchResult(
        query=results[0].query,
        offers=offers,
        raw_count=sum(r.raw_count for r in results),
        statuses=list(statuses.values()),
        from_cache=all(r.from_cache for r in results),
    )


async def _combos(svc: SearchService, queries: list[SearchQuery], filters: FilterSettings) -> list:
    from search.combos import find_combos, worth_showing

    found = []
    for part in await asyncio.gather(*(find_combos(svc, q) for q in queries)):
        found += part
    # Составной маршрут по определению с самостоятельной пересадкой — этот фильтр к нему не применяем
    combo_filters = filters.model_copy(update={"exclude_self_transfer": False, "max_transfers": max(filters.max_transfers, 1)})
    found = apply_filters(found, combo_filters)
    regular = []
    for q in queries:
        res = await svc.search(q, filters, log_search=False)  # из кэша — уже посчитано выше
        regular += res.offers
    return worth_showing(found, regular)
