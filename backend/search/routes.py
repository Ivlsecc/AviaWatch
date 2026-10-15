"""Маршрут пользователя: несколько городов вылета/прилёта и диапазон дат.

«Хургада или Шарм → Москва» разворачивается в набор SearchQuery, результаты
склеиваются в одну выдачу.
"""

from __future__ import annotations

import asyncio
from datetime import date

from pydantic import BaseModel, Field

from search.dedup import merge_duplicates
from search.filters import FilterSettings
from search.orchestrator import SearchResult, SearchService, SourceStatus
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
    svc: SearchService, req: RouteRequest, filters: FilterSettings, user_id: int | None = None, use_cache: bool = True
) -> SearchResult:
    results = await asyncio.gather(*(svc.search(q, filters, user_id, use_cache) for q in req.queries()))
    if len(results) == 1:
        return results[0]

    statuses: dict[str, SourceStatus] = {}
    for r in results:
        for st in r.statuses:
            agg = statuses.setdefault(st.source, SourceStatus(st.source, st.ok, 0, st.error, st.skipped))
            agg.offers += st.offers
            agg.ok = agg.ok or st.ok
    offers = merge_duplicates([o for r in results for o in r.offers])
    return SearchResult(
        query=results[0].query,
        offers=offers,
        raw_count=sum(r.raw_count for r in results),
        statuses=list(statuses.values()),
        from_cache=all(r.from_cache for r in results),
    )
