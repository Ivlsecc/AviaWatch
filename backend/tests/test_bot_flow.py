"""Сквозной сценарий бота через настоящий Dispatcher с подменённым Telegram API."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import select

import bot.handlers.search as search_handlers
from bot.callbacks import Cal, Flt, Menu, Pax, PlacePick, Res, Sub, Wiz
from bot.handlers import search, start, subs
from bot.middlewares import UserMiddleware
from common import app_settings
from common.db import session_scope
from common.models import SourceConfig, Subscription, User
from common.places import Place
from scheduler.checker import SubscriptionChecker
from search.cache import MemoryCache
from search.orchestrator import SearchService, sync_source_configs
from sources.base import FlightOffer, SearchQuery, Source, SourceContext
from sources.registry import register

CHAT = Chat(id=777, type="private")
TG_USER = TgUser(id=777, is_bot=False, first_name="Тест")
FUTURE = date.today() + timedelta(days=40)


@register
class FakeFlowSource(Source):
    name = "fake_flow"
    title = "Fake flow"
    supports_calendar = True

    async def search(self, query: SearchQuery, ctx: SourceContext) -> list[FlightOffer]:
        dep = datetime.combine(query.date_from, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
        return [
            FlightOffer(source=self.name, price_rub=15000 * query.passengers + i * 1000, origin_airport=query.origin,
                        destination_airport="SVO", departure_at=dep + timedelta(hours=i), arrival_at=dep + timedelta(hours=i + 5),
                        duration_min=300, flight_numbers=[f"SU{100 + i}"], link=f"https://x/{i}")
            for i in range(7)
        ]

    async def calendar(self, origin, destination, date_from, date_to, ctx):
        return {date_from + timedelta(days=i): 16000 for i in range(5)}


class FakeSession(BaseSession):
    """Отвечает на методы Bot API правдоподобными объектами и запоминает вызовы."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._next_id = 100

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            self._next_id += 1
            # Как настоящая сессия: объект ответа привязан к боту (иначе .edit_text() не работает)
            return Message(
                message_id=getattr(method, "message_id", None) or self._next_id,
                date=datetime.now(timezone.utc), chat=CHAT, text=method.text, reply_markup=method.reply_markup,
            ).as_(bot)
        if isinstance(method, EditMessageReplyMarkup):
            return True
        if isinstance(method, AnswerCallbackQuery):
            return True
        return True

    async def close(self) -> None:
        pass

    async def stream_content(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    def texts(self) -> list[str]:
        return [m.text for m in self.calls if isinstance(m, (SendMessage, EditMessageText))]

    def alerts(self) -> list[str]:
        return [m.text for m in self.calls if isinstance(m, AnswerCallbackQuery) and m.text]

    def last_markup(self):
        for m in reversed(self.calls):
            if isinstance(m, (SendMessage, EditMessageText, EditMessageReplyMarkup)) and m.reply_markup:
                return m.reply_markup
        return None


class Harness:
    def __init__(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        self.dp, self.bot, self.session = dp, bot, session
        self.update_id = 0
        self.msg_id = 1

    async def text(self, text: str) -> None:
        self.update_id += 1
        self.msg_id += 1
        msg = Message(message_id=self.msg_id, date=datetime.now(timezone.utc), chat=CHAT, from_user=TG_USER, text=text)
        await self.dp.feed_update(self.bot, Update(update_id=self.update_id, message=msg))

    async def press(self, data) -> None:
        self.update_id += 1
        packed = data.pack() if hasattr(data, "pack") else data
        msg = Message(message_id=self.msg_id, date=datetime.now(timezone.utc), chat=CHAT, from_user=TG_USER, text="…")
        cb = CallbackQuery(id=str(self.update_id), from_user=TG_USER, chat_instance="ci", message=msg, data=packed)
        await self.dp.feed_update(self.bot, Update(update_id=self.update_id, callback_query=cb))

    def buttons(self) -> list[str]:
        markup = self.session.last_markup()
        return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data] if markup else []


@pytest.fixture
async def h(monkeypatch):
    app_settings.invalidate()
    await sync_source_configs()
    async with session_scope() as s:
        for cfg in (await s.scalars(select(SourceConfig))).all():
            cfg.enabled = cfg.name == "fake_flow"
            cfg.retries = 0
            cfg.rate_limit_per_min = 0

    async def fake_places(term: str, http=None, limit: int = 6):
        table = {"хург": Place(code="HRG", name="Хургада", type="city", country="Египет"),
                 "шарм": Place(code="SSH", name="Шарм-эль-Шейх", type="city", country="Египет"),
                 "моск": Place(code="MOW", name="Москва", type="city", country="Россия")}
        return [p for k, p in table.items() if term.lower().startswith(k)]

    monkeypatch.setattr(search_handlers, "find_places", fake_places)

    session = FakeSession()
    bot = Bot("42:TEST", session=session)
    svc = SearchService(cache=MemoryCache())

    class Notifier:
        sent: list = []

        async def notify(self, *a, **kw):
            self.sent.append(a)
            return True

    dp = Dispatcher(storage=MemoryStorage())
    dp["svc"] = svc
    dp["checker"] = SubscriptionChecker(svc, Notifier())
    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())
    # Роутеры — модульные синглтоны, к диспетчеру их можно подключить только один раз
    for r in (start.router, search.router, subs.router):
        r._parent_router = None
    dp.include_routers(start.router, search.router, subs.router)
    yield Harness(dp, bot, session)
    await svc.close()


async def test_full_user_journey(h: Harness):
    await h.text("/start")
    assert "AviaWatch" in h.session.texts()[-1] and "Тест" in h.session.texts()[-1]

    # --- мастер поиска ---
    await h.press(Menu(action="search"))
    assert "Откуда летим" in h.session.texts()[-1]
    await h.text("Хургада")
    assert PlacePick(step="from", idx=0).pack() in h.buttons()
    await h.press(PlacePick(step="from", idx=0))
    await h.text("Шарм")  # второй город вылета
    await h.press(PlacePick(step="from", idx=0))
    assert "Хургада (HRG), Шарм-эль-Шейх (SSH)" in h.session.texts()[-1]
    await h.press(Wiz(action="next", step="from"))
    await h.text("Москва")
    await h.press(PlacePick(step="to", idx=0))
    await h.press(Wiz(action="next", step="to"))
    assert "Когда вылет" in h.session.texts()[-1]

    await h.press(Cal(action="day", y=FUTURE.year, m=FUTURE.month, d=FUTURE.day))
    assert "Начало" in h.session.texts()[-1]
    end = FUTURE + timedelta(days=2)
    await h.press(Cal(action="day", y=end.year, m=end.month, d=end.day))
    assert "Сколько пассажиров" in h.session.texts()[-1]
    await h.press(Pax(kind="adults", delta=1))
    await h.press(Wiz(action="next", step="pax"))
    summary = h.session.texts()[-1]
    assert "Проверьте поиск" in summary and "2 взр." in summary

    # Фильтры внутри мастера
    await h.press(Wiz(action="filters"))
    await h.press(Flt(field="transfers", ctx="wiz"))
    assert "Пересадок не больше: <b>2</b>" in h.session.texts()[-1]
    await h.press(Flt(field="done", ctx="wiz"))

    # --- поиск и выдача ---
    await h.press(Wiz(action="search"))
    results = h.session.texts()[-1]
    assert "Хургада / Шарм-эль-Шейх → Москва" in results
    assert "<b>1. " in results and "за чел." in results  # 2 пассажира
    assert "1–5 из" in results and "ответили" in results
    assert Res(action="page", page=1).pack() in h.buttons()
    await h.press(Res(action="page", page=1))
    assert "<b>6. " in h.session.texts()[-1]

    # --- подписка ---
    await h.press(Res(action="subscribe"))
    assert any("Готово" in a for a in h.session.alerts())
    async with session_scope() as s:
        sub = (await s.scalars(select(Subscription))).one()
        assert sub.origin == "HRG,SSH" and sub.adults == 2 and sub.last_min_price == 30000
        assert sub.filters["max_transfers"] == 2

    await h.press(Menu(action="subs"))
    assert Sub(action="open", id=sub.id).pack() in h.buttons()
    await h.press(Sub(action="open", id=sub.id))
    assert "Когда писать" in h.session.texts()[-1]

    await h.press(Sub(action="threshold", id=sub.id))
    await h.text("28 000 ₽")
    assert "Порог: 28 000 ₽ и ниже" in h.session.texts()[-1]
    await h.press(Sub(action="drop", id=sub.id))
    assert "упала на 3%" in h.session.texts()[-1]
    await h.press(Sub(action="digest", id=sub.id))
    assert "каждые 3 ч" in h.session.texts()[-1]
    await h.press(Sub(action="quiet", id=sub.id))
    assert "23:00–08:00" in h.session.texts()[-1]
    await h.press(Sub(action="toggle", id=sub.id))
    assert "на паузе" in h.session.texts()[-1]

    # Все варианты из подписки — отдельным сообщением
    await h.press(Sub(action="results", id=sub.id))
    assert "Хургада / Шарм-эль-Шейх → Москва" in h.session.texts()[-1]

    await h.press(Sub(action="delete", id=sub.id))
    await h.press(Sub(action="delete_yes", id=sub.id))
    async with session_scope() as s:
        assert (await s.scalars(select(Subscription))).first() is None

    # --- фильтры из меню и справка ---
    await h.press(Menu(action="filters"))
    await h.press(Flt(field="combos", ctx="menu"))
    async with session_scope() as s:
        user = await s.scalar(select(User).where(User.tg_id == 777))
        assert user.default_filters["self_combos"] is True
    await h.press(Menu(action="help"))
    assert "Как пользоваться" in h.session.texts()[-1]


async def test_maintenance_mode_blocks_users(h: Harness):
    await app_settings.update({"maintenance": True, "maintenance_text": "Техработы!"})
    try:
        await h.text("/start")
        assert h.session.texts()[-1] == "Техработы!"
    finally:
        await app_settings.update({"maintenance": False})


async def test_expired_session_does_not_crash(h: Harness):
    await h.text("/start")
    await h.press(Res(action="page", page=1))  # нет данных поиска в FSM
    assert "устарел" in h.session.texts()[-1]
    await h.press(PlacePick(step="from", idx=3))
    assert any("устарел" in a for a in h.session.alerts())
