from datetime import date, datetime, timezone

from sqlalchemy import func, select

from common.db import session_scope
from common.models import PriceSnapshot, SearchLog, SourceConfig
from search.cache import MemoryCache
from search.orchestrator import SearchService, sync_source_configs
from sources.base import FlightOffer, SearchQuery, Source, SourceContext
from sources.registry import register

CALLS = {"ok": 0, "broken": 0}


@register
class FakeOkSource(Source):
    name = "fake_ok"
    title = "Fake OK"

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        CALLS["ok"] += 1
        dep = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)
        return [
            FlightOffer(source=self.name, price_rub=40000, origin_airport="HRG", destination_airport="SVO",
                        departure_at=dep, duration_min=300, flight_numbers=["SU1840"], link="https://x/1"),
            FlightOffer(source=self.name, price_rub=30000, origin_airport="HRG", destination_airport="VKO",
                        departure_at=dep, duration_min=290, flight_numbers=["ZF702"], link="https://x/2"),
            FlightOffer(source=self.name, price_rub=20000, origin_airport="HRG", destination_airport="SVO",
                        departure_at=dep, duration_min=1500, transfers=3, link="https://x/3"),
        ]


@register
class FakeBrokenSource(Source):
    name = "fake_broken"
    title = "Fake broken"

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        CALLS["broken"] += 1
        raise RuntimeError("сайт поменял вёрстку")


QUERY = SearchQuery(origin="HRG", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 20), adults=2)


async def _setup():
    CALLS.update(ok=0, broken=0)
    await sync_source_configs()
    async with session_scope() as s:
        for cfg in (await s.scalars(select(SourceConfig))).all():
            cfg.enabled = cfg.name.startswith("fake_")
            cfg.retries = 0
            cfg.rate_limit_per_min = 0


async def test_search_filters_merges_caches_and_saves_history():
    await _setup()
    svc = SearchService(cache=MemoryCache())
    try:
        res = await svc.search(QUERY)
        assert [o.price_rub for o in res.offers] == [30000, 40000]  # 3 пересадки отсеяны
        assert res.raw_count == 3 and not res.from_cache
        statuses = {st.source: st for st in res.statuses}
        assert statuses["fake_ok"].ok and not statuses["fake_broken"].ok
        assert "вёрстку" in statuses["fake_broken"].error

        again = await svc.search(QUERY)
        assert again.from_cache and [o.price_rub for o in again.offers] == [30000, 40000]
        assert CALLS["ok"] == 1
    finally:
        await svc.close()

    async with session_scope() as s:
        prices = sorted((await s.scalars(select(PriceSnapshot.price_rub))).all())
        assert prices == [10000, 15000, 20000]  # за одного пассажира
        assert await s.scalar(select(func.count(SearchLog.id))) == 2


async def test_circuit_breaker_disables_failing_source(monkeypatch):
    await _setup()
    down = []

    async def on_down(name, error):
        down.append(name)

    svc = SearchService(cache=MemoryCache(), on_source_down=on_down)
    monkeypatch.setattr(svc.settings, "source_failure_threshold", 2)
    try:
        await svc.search(QUERY, use_cache=False)
        await svc.search(QUERY, use_cache=False)
        assert down == ["fake_broken"]
        res = await svc.search(QUERY, use_cache=False)
        broken = next(st for st in res.statuses if st.source == "fake_broken")
        assert broken.skipped
        assert CALLS["broken"] == 2
    finally:
        await svc.close()

    async with session_scope() as s:
        cfg = await s.get(SourceConfig, "fake_broken")
        assert cfg.disabled_until is not None and cfg.last_error
