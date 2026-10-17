"""Bot wiring: dispatcher, callback data, keyboards and text rendering."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from aiogram import Dispatcher
from aiogram.filters.callback_data import CallbackData
from pydantic import SecretStr

from app.bot import texts
from app.bot.bot import create_bot
from app.bot.callbacks import (
    AdminClientCB,
    AdminCourseCB,
    AdminLessonCB,
    AppCB,
    CourseCB,
    LessonCB,
    QuizCB,
)
from app.bot.handlers.helpers import truncate_for_telegram
from app.bot.keyboards import common as common_kb
from app.config.settings import get_settings
from app.models.application import Application, ApplicationMessage
from app.models.content import Course, Lesson, LessonQuestion
from app.models.enums import (
    ApplicationStatus,
    ApplicationType,
    Audience,
    ConsultationTopic,
    ContactMethod,
    ContentStatus,
    CourseDelivery,
)
from tests.conftest import make_user

TZ = ZoneInfo("Asia/Bishkek")
NOW = dt.datetime(2026, 10, 17, 9, 0, tzinfo=dt.UTC)
TELEGRAM_CALLBACK_DATA_LIMIT = 64


def test_dispatcher_wires_middlewares_and_routers(dispatcher: Dispatcher) -> None:
    assert len(dispatcher.update.outer_middleware) >= 4
    names = [router.name for router in dispatcher.sub_routers[0].sub_routers]
    assert names[0] == "common"
    assert names[-1] == "errors"
    assert {"client", "client_flow", "admin_applications", "admin_content", "admin_misc"} <= set(
        names
    )


def test_create_bot_requires_a_token() -> None:
    settings = get_settings().model_copy(update={"bot_token": SecretStr("")})
    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        create_bot(settings)


@pytest.mark.parametrize(
    "payload",
    [
        AppCB(action="cancel_yes", id=987_654_321, page=999, scope="closed"),
        CourseCB(action="enroll", id=987_654_321, page=999, all=1),
        LessonCB(action="open", id=987_654_321, page=999, all=1),
        QuizCB(lesson=987_654_321, number=20, option=5),
        AdminCourseCB(action="set_delivery", id=987_654_321, page=99, value="ONLINE"),
        AdminLessonCB(action="set_audience", id=987_654_321, page=99, value="PURCHASER"),
        AdminClientCB(action="unblock", id=987_654_321, page=999, cat="PURCHASER"),
    ],
)
def test_callback_data_fits_telegram_limit(payload: CallbackData) -> None:
    packed = payload.pack()
    assert len(packed.encode()) <= TELEGRAM_CALLBACK_DATA_LIMIT
    assert type(payload).unpack(packed) == payload


def test_menus_differ_per_role() -> None:
    client_labels = {b.text for row in common_kb.client_menu().keyboard for b in row}
    admin_labels = {b.text for row in common_kb.admin_menu().keyboard for b in row}
    assert texts.BTN_CONSULTATION in client_labels
    assert texts.BTN_ADMIN_APPLICATIONS in admin_labels
    assert not client_labels & admin_labels


def test_course_card_renders_admin_html_and_escapes_plain_fields() -> None:
    course = Course(
        title="Портал <ЭГЗ> с нуля",
        description="<b>Программа</b>: 3 дня",
        audience=Audience.PURCHASER,
        delivery=CourseDelivery.ONLINE,
        schedule="15–17 ноября",
        price="4 500 сом",
        location="",
        status=ContentStatus.PUBLISHED,
    )
    rendered = texts.course_card(course)
    assert "Портал &lt;ЭГЗ&gt; с нуля" in rendered
    assert "<b>Программа</b>" in rendered
    assert "4 500 сом" in rendered
    assert "Место" not in rendered


def test_application_card_shows_thread_as_plain_text() -> None:
    application = Application(
        number="ZV-2026-000007",
        type=ApplicationType.CONSULTATION,
        status=ApplicationStatus.IN_PROGRESS,
        client_id=2,
        topic=ConsultationTopic.COMPLAINT,
        description="Отклонили заявку",
        contact_method=ContactMethod.TELEGRAM,
        created_at=NOW,
    )
    messages = [
        ApplicationMessage(from_staff=False, text="Как обжаловать <решение>?", created_at=NOW),
        ApplicationMessage(
            from_staff=True, text="<b>Подайте жалобу</b> в течение 5 дней", created_at=NOW
        ),
    ]
    client = make_user(2, full_name="Айгуль")
    rendered = texts.application_card(application, messages, TZ, client=client)
    assert "ZV-2026-000007" in rendered
    assert "Жалобы и споры" in rendered
    assert "Как обжаловать &lt;решение&gt;?" in rendered
    # Staff HTML is flattened in the thread preview (it may be truncated there).
    assert "Подайте жалобу в течение 5 дней" in rendered
    assert "+996555123456" in rendered


def test_lesson_text_mentions_quiz_and_progress() -> None:
    lesson = Lesson(title="Как подать заявку", body="Текст урока", audience=Audience.ALL)
    assert "тест из 3" in texts.lesson_text(lesson, 1, 5, 3, None)


def test_quiz_feedback_reveals_the_correct_answer() -> None:
    question = LessonQuestion(question="Сколько?", options=["Два", "Три"], correct_option=1)
    wrong = texts.quiz_answer_feedback(question, ["Два", "Три"], 0, 1, 1)
    assert "Неверно" in wrong
    assert "Три" in wrong
    assert "Верно" in texts.quiz_answer_feedback(question, ["Два", "Три"], 1, 1, 1)


def test_long_html_is_flattened_instead_of_cut_mid_tag() -> None:
    text = "<b>" + "а" * 5000 + "</b> &amp; конец"
    result = truncate_for_telegram(text)
    assert len(result) <= get_settings().max_message_length
    assert "<b>" not in result
    assert result.endswith("сокращено</i>")
