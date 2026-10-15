from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from api.main import app
from common import app_settings
from common.config import get_settings
from common.db import session_scope
from common.models import SearchLog, SourceConfig, SourceRunLog, Subscription, User
from search.cache import MemoryCache
from search.orchestrator import SearchService, sync_source_configs
from sources.base import FlightOffer, SearchQuery, Source, SourceContext
from sources.registry import register


@register
class FakeApiSource(Source):
    name = "fake_api"
    title = "Fake API"

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        dep = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)
        return [FlightOffer(source=self.name, price_rub=12345, origin_airport=query.origin,
                            destination_airport=query.destination, departure_at=dep, link="https://x")]


@pytest.fixture
async def client(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "admin_password", "secret")
    monkeypatch.setattr(s, "jwt_secret", "test-jwt-secret-that-is-long-enough-32b")
    app_settings.invalidate()
    await sync_source_configs()
    app.state.svc = SearchService(cache=MemoryCache())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "secret"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c
    await app.state.svc.close()


async def test_auth_required_and_bad_password(client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as anon:
        assert (await anon.get("/api/dashboard/summary")).status_code == 401
        assert (await anon.post("/api/auth/login", json={"username": "admin", "password": "nope"})).status_code == 401
    assert (await client.get("/api/auth/me")).json() == {"username": "admin"}


async def test_summary_and_activity(client):
    now = datetime.now(timezone.utc)
    async with session_scope() as s:
        s.add(User(tg_id=1, default_filters={}, last_seen_at=now))
        s.add(SearchLog(origin="HRG", destination="MOW", date_from=date(2026, 11, 20), date_to=date(2026, 11, 20)))
        s.add_all([SourceRunLog(source="tutu", ok=True, elapsed_ms=900, offers=10),
                   SourceRunLog(source="tutu", ok=False, elapsed_ms=30000, error="таймаут")])
    summary = (await client.get("/api/dashboard/summary")).json()
    assert summary["users"] == 1 and summary["dau"] == 1 and summary["searches_24h"] == 1
    assert summary["source_requests_24h"] == 2 and summary["source_errors_24h"] == 1
    activity = (await client.get("/api/dashboard/activity?hours=24")).json()
    assert sum(b["requests"] for b in activity) == 2 and sum(b["errors"] for b in activity) == 1
    health = (await client.get("/api/dashboard/sources")).json()
    assert health["tutu"]["requests"] == 2 and health["tutu"]["error_rate"] == 0.5
    system = (await client.get("/api/system?minutes=5")).json()
    assert system["info"]["cpu_count"] >= 1


async def test_sources_patch_reset_and_test_run(client):
    sources = (await client.get("/api/sources")).json()
    names = {x["name"] for x in sources}
    assert {"tutu", "kupibilet", "aviakassa", "fake_api"} <= names

    r = await client.patch("/api/sources/tutu", json={"enabled": False, "timeout_s": 33, "proxy": "", "board_x": 10, "board_y": 20})
    assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["status"] == "disabled"
    async with session_scope() as s:
        cfg = await s.get(SourceConfig, "tutu")
        assert cfg.timeout_s == 33 and cfg.proxy is None and cfg.board_x == 10
        cfg.disabled_until = datetime.now(timezone.utc) + timedelta(hours=1)
        cfg.consecutive_failures = 3
    assert (await client.post("/api/sources/tutu/reset")).json()["consecutive_failures"] == 0

    res = (await client.post("/api/sources/fake_api/test", json={"origin": "hrg", "destination": "mow", "date": "2026-11-20"})).json()
    assert res["ok"] and res["offers"] == 1 and res["sample"][0]["price_rub"] == 12345
    assert (await client.patch("/api/sources/nope", json={"enabled": True})).status_code == 404


async def test_users_subscriptions_settings_board_broadcast(client):
    async with session_scope() as s:
        u = User(tg_id=42, username="danil", default_filters={})
        s.add(u)
        await s.flush()
        s.add(Subscription(user_id=u.id, origin="HRG", destination="MOW", date_from=date(2026, 11, 20),
                           date_to=date(2026, 11, 25), filters={}))
        uid = u.id
    users = (await client.get("/api/users?q=dan")).json()
    assert users["total"] == 1 and users["items"][0]["subscriptions"] == 1
    detail = (await client.get(f"/api/users/{uid}")).json()
    sub_id = detail["subscriptions"][0]["id"]
    assert (await client.patch(f"/api/users/{uid}", json={"is_blocked": True})).json()["is_blocked"] is True
    assert (await client.patch(f"/api/subscriptions/{sub_id}", json={"is_active": False})).json()["is_active"] is False
    assert (await client.delete(f"/api/subscriptions/{sub_id}")).json() == {"ok": True}

    conf = (await client.put("/api/settings", json={"maintenance": True, "welcome_text": "Привет{name}!"})).json()
    assert conf["maintenance"] is True and conf["welcome_text"] == "Привет{name}!"
    assert (await client.put("/api/settings", json={"unknown": 1})).status_code == 422
    assert await app_settings.get("maintenance") is True

    board = (await client.put("/api/board", json={"layout": {"filters": {"x": 1, "y": 2}},
                                                   "proxy_pools": [{"name": "ru", "url": "socks5://h:1"}]})).json()
    assert board["proxy_pools"][0]["name"] == "ru"
    assert (await client.put("/api/board", json={"proxy_pools": [{"name": ""}]})).status_code == 422

    job = (await client.post("/api/broadcast", json={"text": "тест", "dry_run": True})).json()
    assert job["total"] == 0 and job["done"]  # единственный пользователь заблокирован
