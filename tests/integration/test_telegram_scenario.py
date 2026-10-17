"""End-to-end scenario through the real dispatcher.

Telegram updates are fed into the aiogram dispatcher with all middlewares and
routers; the Bot API is replaced by a recording fake session, so the test sees
exactly what the bot would have sent — and to whom.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import itertools
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    AnswerCallbackQuery,
    CopyMessage,
    EditMessageText,
    GetMe,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    Contact,
    InlineKeyboardMarkup,
    Message,
    MessageId,
    PhotoSize,
    ReplyKeyboardMarkup,
    Update,
)
from aiogram.types import User as TgUser
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.bot import texts
from app.bot.middlewares.throttling import ThrottlingMiddleware
from app.config.settings import WEBHOOK_PATH, Settings
from app.database.session import dispose_engine, init_engine
from app.main import create_app
from app.models.application import Application
from app.models.enums import ApplicationStatus, ApplicationType, ClientCategory, UserRole
from app.models.user import User
from tests.integration.conftest import create_user

pytestmark = pytest.mark.integration

ADMIN_ID = 1001
CLIENT_ID = 777
NOW = dt.datetime(2026, 10, 17, 9, 0, tzinfo=dt.UTC)
THROTTLE_LIMIT_FOR_TESTS = 10_000


class RecordingSession(BaseSession):
    """Fake Bot API: records every call and returns plausible results."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self._ids = itertools.count(1000)
        self._watermark = 0

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.calls.append(method)
        if isinstance(method, GetMe):
            return TgUser(id=42, is_bot=True, first_name="Bot", username="tender_test_bot")
        if isinstance(method, CopyMessage):
            return MessageId(message_id=next(self._ids))
        if isinstance(method, AnswerCallbackQuery):
            return True
        chat_id = getattr(method, "chat_id", None) or 0
        return Message(
            message_id=next(self._ids),
            date=NOW,
            chat=Chat(id=int(chat_id), type="private"),
            text=getattr(method, "text", None) or "ok",
        )

    async def close(self) -> None:  # pragma: no cover - nothing to release
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        raise NotImplementedError
        yield b""  # pragma: no cover

    # -- assertions helpers -------------------------------------------------
    def texts_to(self, chat_id: int) -> list[str]:
        sent: list[str] = []
        for call in self.calls[self._watermark :]:
            if isinstance(call, SendMessage | EditMessageText) and call.chat_id == chat_id:
                sent.append(call.text)
        return sent

    def last_markup(self, chat_id: int) -> InlineKeyboardMarkup:
        for call in reversed(self.calls):
            if (
                isinstance(call, SendMessage | EditMessageText)
                and call.chat_id == chat_id
                and isinstance(call.reply_markup, InlineKeyboardMarkup)
            ):
                return call.reply_markup
        raise AssertionError(f"no inline keyboard sent to {chat_id}")

    def clear(self) -> None:
        """Forget what was sent so far (keyboards stay pressable)."""
        self._watermark = len(self.calls)


class Scenario:
    def __init__(self, dispatcher: Dispatcher, bot: Bot, session: RecordingSession) -> None:
        self.dispatcher = dispatcher
        self.bot = bot
        self.api = session
        self._update_ids = itertools.count(1)
        self._message_ids = itertools.count(1)

    def _user(self, user_id: int) -> TgUser:
        names = {ADMIN_ID: "Админ", CLIENT_ID: "Айгуль"}
        return TgUser(id=user_id, is_bot=False, first_name=names.get(user_id, "Гость"))

    async def message(self, user_id: int, text: str | None = None, **extra: Any) -> None:
        message = Message(
            message_id=next(self._message_ids),
            date=NOW,
            chat=Chat(id=user_id, type="private"),
            from_user=self._user(user_id),
            text=text,
            **extra,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=next(self._update_ids), message=message)
        )

    async def press(self, user_id: int, data: str) -> None:
        callback = CallbackQuery(
            id=str(next(self._update_ids)),
            from_user=self._user(user_id),
            chat_instance="test",
            data=data,
            message=Message(
                message_id=next(self._message_ids),
                date=NOW,
                chat=Chat(id=user_id, type="private"),
                text="previous screen",
            ),
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=next(self._update_ids), callback_query=callback)
        )

    async def press_button(self, user_id: int, label_part: str) -> None:
        """Press the inline button (from the last keyboard) whose label contains the text."""
        markup = self.api.last_markup(user_id)
        for row in markup.inline_keyboard:
            for button in row:
                if label_part in button.text and button.callback_data:
                    await self.press(user_id, button.callback_data)
                    return
        labels = [button.text for row in markup.inline_keyboard for button in row]
        raise AssertionError(f"button {label_part!r} not found in {labels}")


@pytest.fixture
async def scenario(engine: AsyncEngine, dispatcher: Dispatcher) -> AsyncGenerator[Scenario, None]:
    # ``engine`` has migrated and emptied the test database; point the
    # process-wide session factory (used by the middleware) at it.
    await dispose_engine()
    init_engine()
    # The anti-spam window is per process; scripted tests click much faster
    # than a person, so start each scenario with a clean slate.
    for middleware in dispatcher.update.outer_middleware:
        if isinstance(middleware, ThrottlingMiddleware):
            middleware.limit = THROTTLE_LIMIT_FOR_TESTS
    api = RecordingSession()
    bot = Bot(token="42:TEST", session=api)
    yield Scenario(dispatcher, bot, api)
    await bot.session.close()
    storage = dispatcher.storage
    assert isinstance(storage, MemoryStorage)
    storage.storage.clear()  # no FSM state may leak into the next test
    await dispose_engine()


async def test_consultation_from_first_contact_to_answer(
    scenario: Scenario, session: AsyncSession
) -> None:
    await create_user(
        session, telegram_id=ADMIN_ID, full_name="Админ", role=UserRole.ADMIN, category=None
    )
    api = scenario.api

    # 1. A new client opens the bot: registered automatically, asked who they are.
    await scenario.message(CLIENT_ID, "/start")
    assert any("Кто вы?" in text for text in api.texts_to(CLIENT_ID))
    await scenario.press_button(CLIENT_ID, "Поставщик")
    client = (await session.execute(select(User).where(User.telegram_id == CLIENT_ID))).scalar_one()
    assert client.category is ClientCategory.SUPPLIER

    # 2. Consultation: topic → question with a screenshot → contact way.
    await scenario.message(CLIENT_ID, texts.BTN_CONSULTATION)
    await scenario.press_button(CLIENT_ID, "Подача заявки поставщиком")
    await scenario.message(
        CLIENT_ID,
        caption="Портал не принимает мое предложение, ошибка на скриншоте",
        photo=[PhotoSize(file_id="screenshot-id", file_unique_id="u1", width=10, height=10)],
    )
    await scenario.press_button(CLIENT_ID, "Ответить в Telegram")

    # 3. First application: name and phone are asked once.
    await scenario.press_button(CLIENT_ID, "Айгуль")
    await scenario.message(
        CLIENT_ID,
        contact=Contact(phone_number="996555123456", first_name="Айгуль", user_id=CLIENT_ID),
    )
    assert any("Проверьте заявку" in text for text in api.texts_to(CLIENT_ID))

    # 4. Submit: the admin is notified with the screenshot and reply buttons.
    api.clear()
    await scenario.press_button(CLIENT_ID, "Отправить заявку")
    assert any("принята" in text for text in api.texts_to(CLIENT_ID))
    assert any("Новая заявка" in text for text in api.texts_to(ADMIN_ID))
    photos = [c for c in api.calls if isinstance(c, SendPhoto) and c.chat_id == ADMIN_ID]
    assert [p.photo for p in photos] == ["screenshot-id"]

    application = (await session.execute(select(Application))).scalar_one()
    assert application.status is ApplicationStatus.NEW

    # 5. The admin answers from the notification; the client gets the reply.
    api.clear()
    await scenario.press_button(ADMIN_ID, "Ответить")
    await scenario.message(ADMIN_ID, "Проверьте срок действия ЭЦП и повторите отправку.")
    assert any("Проверьте срок действия ЭЦП" in text for text in api.texts_to(CLIENT_ID))
    assert any("Ответ отправлен" in text for text in api.texts_to(ADMIN_ID))
    await session.refresh(application)
    assert application.status is ApplicationStatus.IN_PROGRESS

    # 6. The client writes back; the consultant who answered is notified.
    api.clear()
    await scenario.press_button(CLIENT_ID, "Ответить")
    await scenario.message(CLIENT_ID, "Спасибо, все получилось!")
    assert any("Спасибо, все получилось!" in text for text in api.texts_to(ADMIN_ID))

    # 7. The admin closes the application; the client is told.
    api.clear()
    await scenario.press_button(ADMIN_ID, "Открыть")
    await scenario.press_button(ADMIN_ID, "Завершить")
    await scenario.press_button(ADMIN_ID, "Завершить")
    assert any("завершена" in text for text in api.texts_to(CLIENT_ID))
    await session.refresh(application)
    assert application.status is ApplicationStatus.DONE


async def test_client_cannot_reach_admin_screens(scenario: Scenario, session: AsyncSession) -> None:
    await create_user(session, telegram_id=CLIENT_ID, full_name="Айгуль")
    await scenario.message(CLIENT_ID, texts.BTN_ADMIN_CLIENTS)
    await scenario.press(CLIENT_ID, "acl:block:1:1:all")
    sent = scenario.api.texts_to(CLIENT_ID)
    assert not any("Клиенты" in text for text in sent)


async def test_blocked_user_is_refused(scenario: Scenario, session: AsyncSession) -> None:
    await create_user(session, telegram_id=CLIENT_ID, full_name="Айгуль", is_active=False)
    await scenario.message(CLIENT_ID, "/start")
    assert scenario.api.texts_to(CLIENT_ID) == [texts.ACCESS_BLOCKED]


async def test_admin_publishes_a_course_and_client_enrolls(
    scenario: Scenario, session: AsyncSession
) -> None:
    await create_user(
        session, telegram_id=ADMIN_ID, full_name="Админ", role=UserRole.ADMIN, category=None
    )
    await create_user(session, telegram_id=CLIENT_ID, full_name="Айгуль")
    api = scenario.api

    # Admin: 7-step wizard, skipping the optional fields.
    await scenario.message(ADMIN_ID, texts.BTN_ADMIN_COURSES)
    await scenario.press_button(ADMIN_ID, "Новый курс")
    await scenario.message(ADMIN_ID, "Портал госзакупок с нуля")
    await scenario.press_button(ADMIN_ID, "Пропустить")
    await scenario.press_button(ADMIN_ID, "Для всех")
    await scenario.press_button(ADMIN_ID, "Онлайн (Zoom)")
    await scenario.message(ADMIN_ID, "15–17 ноября, 10:00")
    await scenario.message(ADMIN_ID, "4 500 сом")
    await scenario.press_button(ADMIN_ID, "Пропустить")
    assert any("черновик" in text for text in api.texts_to(ADMIN_ID))
    await scenario.press_button(ADMIN_ID, "Опубликовать")
    assert any("start=course_1" in text for text in api.texts_to(ADMIN_ID))

    # Client: training → courses → card → sign up.
    api.clear()
    await scenario.message(CLIENT_ID, texts.BTN_TRAINING)
    await scenario.press_button(CLIENT_ID, "Живые курсы")
    await scenario.press_button(CLIENT_ID, "Портал госзакупок с нуля")
    assert any("4 500 сом" in text for text in api.texts_to(CLIENT_ID))
    await scenario.press_button(CLIENT_ID, "Записаться")
    await scenario.press_button(CLIENT_ID, "Пропустить")
    api.clear()
    await scenario.press_button(CLIENT_ID, "Отправить заявку")
    assert any("Новая заявка" in text for text in api.texts_to(ADMIN_ID))

    # The same course twice is refused politely.
    await scenario.press(CLIENT_ID, "c:enroll:1:1:0")
    await scenario.press_button(CLIENT_ID, "Пропустить")
    await scenario.press_button(CLIENT_ID, "Отправить заявку")
    assert any("уже записаны" in text for text in api.texts_to(CLIENT_ID))


async def test_lesson_quiz_through_the_bot(scenario: Scenario, session: AsyncSession) -> None:
    from app.models.enums import ContentStatus
    from app.services.catalog_service import CatalogService, LessonInput

    admin = await create_user(
        session, telegram_id=ADMIN_ID, full_name="Админ", role=UserRole.ADMIN, category=None
    )
    await create_user(session, telegram_id=CLIENT_ID, full_name="Айгуль")
    catalog = CatalogService(session)
    lesson = await catalog.create_lesson(admin, LessonInput(title="Комиссия", body="Текст урока"))
    await catalog.add_question(admin, lesson.id, "Сколько членов?\n- 2\n+ 3")
    await catalog.add_question(admin, lesson.id, "Кто подписывает?\n+ Руководитель\n- Поставщик")
    await catalog.set_lesson_status(admin, lesson.id, ContentStatus.PUBLISHED)
    api = scenario.api

    await scenario.message(CLIENT_ID, texts.BTN_TRAINING)
    await scenario.press_button(CLIENT_ID, "Уроки в боте")
    await scenario.press_button(CLIENT_ID, "Комиссия")
    await scenario.press_button(CLIENT_ID, "Пройти тест")
    await scenario.press_button(CLIENT_ID, "2")  # correct
    # A double tap on the already answered question is ignored.
    await scenario.press(CLIENT_ID, f"q:{lesson.id}:1:0")
    await scenario.press_button(CLIENT_ID, "2")  # wrong
    assert any("1 из 2" in text for text in api.texts_to(CLIENT_ID))

    listing = await CatalogService(session).list_lessons(
        (await session.execute(select(User).where(User.telegram_id == CLIENT_ID))).scalar_one()
    )
    assert listing.completed == {lesson.id}


async def test_supplier_from_instagram_orders_tender_support(
    scenario: Scenario, session: AsyncSession
) -> None:
    await create_user(
        session, telegram_id=ADMIN_ID, full_name="Админ", role=UserRole.ADMIN, category=None
    )
    api = scenario.api

    # The Instagram story link: source is recorded, the category is asked first.
    await scenario.message(CLIENT_ID, "/start insta_support")
    await scenario.press_button(CLIENT_ID, "Поставщик")
    client = (await session.execute(select(User).where(User.telegram_id == CLIENT_ID))).scalar_one()
    assert client.source == "instagram"

    # Suppliers get the tender support button in their menu.
    menus = [
        call.reply_markup
        for call in api.calls
        if isinstance(call, SendMessage)
        and call.chat_id == CLIENT_ID
        and isinstance(call.reply_markup, ReplyKeyboardMarkup)
    ]
    assert texts.BTN_SUPPORT in {b.text for row in menus[-1].keyboard for b in row}

    # The deep link continues straight to the support offer.
    await scenario.press_button(CLIENT_ID, "Оставить заявку")
    await scenario.message(CLIENT_ID, "Объявление №12345, поставка мебели, подача до 25.10")
    await scenario.press_button(CLIENT_ID, "Позвонить мне")
    await scenario.message(CLIENT_ID, "завтра после 14:00")
    await scenario.press_button(CLIENT_ID, "Айгуль")
    await scenario.message(CLIENT_ID, "0555 123 456")
    api.clear()
    await scenario.press_button(CLIENT_ID, "Отправить заявку")

    application = (await session.execute(select(Application))).scalar_one()
    assert application.type is ApplicationType.SUPPORT
    assert application.preferred_time == "завтра после 14:00"
    assert any("Тендерное сопровождение" in text for text in api.texts_to(ADMIN_ID))


async def test_purchaser_is_offered_no_tender_support(
    scenario: Scenario, session: AsyncSession
) -> None:
    await create_user(
        session, telegram_id=CLIENT_ID, full_name="Данияр", category=ClientCategory.PURCHASER
    )
    await scenario.message(CLIENT_ID, texts.BTN_SUPPORT)
    assert any("для <b>поставщиков</b>" in text for text in scenario.api.texts_to(CLIENT_ID))
    assert (await session.execute(select(Application))).first() is None


async def test_webhook_endpoint_checks_the_secret_and_processes_updates(
    scenario: Scenario, session: AsyncSession, settings: Settings
) -> None:
    configured = settings.model_copy(
        update={"webhook_base_url": "https://bot.example.com", "bot_token": SecretStr("42:TEST")}
    )
    app = create_app(configured, scenario.bot, scenario.dispatcher)
    update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": int(NOW.timestamp()),
            "chat": {"id": CLIENT_ID, "type": "private"},
            "from": {"id": CLIENT_ID, "is_bot": False, "first_name": "Айгуль"},
            "text": "/start insta",
        },
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        forged = await http.post(WEBHOOK_PATH, json=update)
        assert forged.status_code == 403
        wrong = await http.post(
            WEBHOOK_PATH, json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "nope"}
        )
        assert wrong.status_code == 403
        ok = await http.post(
            WEBHOOK_PATH,
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": configured.webhook_token},
        )
        assert ok.status_code == 200

    # The update is processed in the background — wait for it.
    for _ in range(100):
        if scenario.api.texts_to(CLIENT_ID):
            break
        await asyncio.sleep(0.02)
    assert any("Здравствуйте" in text for text in scenario.api.texts_to(CLIENT_ID))
    client = (await session.execute(select(User).where(User.telegram_id == CLIENT_ID))).scalar_one()
    assert client.source == "instagram"
