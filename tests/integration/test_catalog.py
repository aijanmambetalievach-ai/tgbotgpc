"""Courses, lessons, quizzes, progress, FAQ and editable texts."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import (
    ContentUnavailableError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.models.content import BotTextKey
from app.models.enums import Audience, ClientCategory, ContentStatus
from app.models.user import User
from app.services.catalog_service import CatalogService, CourseInput, LessonInput
from tests.integration.conftest import create_course, create_lesson, create_user

pytestmark = pytest.mark.integration


async def test_clients_see_published_courses_for_their_category(
    session: AsyncSession, admin: User, client: User
) -> None:
    await create_course(session, title="Для всех", audience=Audience.ALL, position=1)
    await create_course(session, title="Поставщикам", audience=Audience.SUPPLIER, position=2)
    await create_course(session, title="Закупщикам", audience=Audience.PURCHASER, position=3)
    await create_course(session, title="Черновик", status=ContentStatus.DRAFT)
    await create_course(session, title="Архив", status=ContentStatus.ARCHIVED)

    catalog = CatalogService(session)
    assert client.category is ClientCategory.SUPPLIER
    mine = await catalog.list_courses(client)
    assert [c.title for c in mine.items] == ["Для всех", "Поставщикам"]
    everything = await catalog.list_courses(client, show_all=True)
    assert [c.title for c in everything.items] == ["Для всех", "Поставщикам", "Закупщикам"]

    admin_view = await catalog.list_courses(admin)
    assert {c.title for c in admin_view.items} == {
        "Для всех",
        "Поставщикам",
        "Закупщикам",
        "Черновик",
    }
    archive = await catalog.list_archived_courses(admin)
    assert [c.title for c in archive.items] == ["Архив"]


async def test_admin_creates_and_publishes_a_course(
    session: AsyncSession, admin: User, client: User
) -> None:
    catalog = CatalogService(session)
    course = await catalog.create_course(
        admin, CourseInput(title="  Жалобы  в госзакупках ", description="<b>2 дня</b>")
    )
    assert course.title == "Жалобы в госзакупках"
    assert course.status is ContentStatus.DRAFT
    with pytest.raises(ContentUnavailableError):
        await catalog.get_course(client, course.id)

    await catalog.update_course_text(admin, course.id, "price", "3 000 сом")
    await catalog.set_course_status(admin, course.id, ContentStatus.PUBLISHED)
    card = await catalog.get_course(client, course.id)
    assert card.course.price == "3 000 сом"

    with pytest.raises(PermissionDeniedError):
        await catalog.create_course(client, CourseInput(title="Взлом"))
    with pytest.raises(ValidationError):
        await catalog.update_course_text(admin, course.id, "status", "x")


async def test_lesson_navigation_follows_position_and_category(
    session: AsyncSession, client: User
) -> None:
    first = await create_lesson(session, title="Первый", position=1)
    await create_lesson(session, title="Закупщикам", position=2, audience=Audience.PURCHASER)
    third = await create_lesson(
        session, title="Поставщикам", position=3, audience=Audience.SUPPLIER
    )
    await create_lesson(session, title="Черновик", position=4, status=ContentStatus.DRAFT)

    catalog = CatalogService(session)
    view = await catalog.view_lesson(client, first.id)
    assert (view.index, view.total) == (1, 2)
    assert view.prev_id is None
    assert view.next_id == third.id

    all_view = await catalog.view_lesson(client, first.id, show_all=True)
    assert all_view.total == 3


async def test_quiz_and_best_score_progress(
    session: AsyncSession, admin: User, client: User
) -> None:
    catalog = CatalogService(session)
    lesson = await catalog.create_lesson(admin, LessonInput(title="Комиссия", body="Текст"))
    await catalog.add_question(admin, lesson.id, "Сколько членов?\n- 2\n+ 3\n- 4")
    await catalog.add_question(admin, lesson.id, "Кто председатель?\n+ Член комиссии\n- Поставщик")
    with pytest.raises(ValidationError):
        await catalog.add_question(admin, lesson.id, "Без вариантов")

    with pytest.raises(ContentUnavailableError):
        await catalog.view_lesson(client, lesson.id)
    await catalog.set_lesson_status(admin, lesson.id, ContentStatus.PUBLISHED)

    view = await catalog.view_lesson(client, lesson.id)
    assert [q.correct_option for q in view.questions] == [1, 0]

    await catalog.complete_lesson(client, lesson.id, quiz_score=2, quiz_total=2)
    progress = await catalog.complete_lesson(client, lesson.id, quiz_score=1, quiz_total=2)
    assert progress.quiz_score == 2, "a worse retake must not overwrite the best score"

    listing = await catalog.list_lessons(client)
    assert listing.completed == {lesson.id}
    assert listing.question_counts == {lesson.id: 2}

    await catalog.clear_quiz(admin, lesson.id)
    assert (await catalog.view_lesson(client, lesson.id)).questions == []


async def test_lesson_needs_text_or_file(session: AsyncSession, admin: User) -> None:
    with pytest.raises(ValidationError):
        await CatalogService(session).create_lesson(admin, LessonInput(title="Пустой"))


async def test_faq_visibility(session: AsyncSession, admin: User, client: User) -> None:
    catalog = CatalogService(session)
    entry = await catalog.save_faq(admin, question="Что такое ЭЦП?", answer="Электронная подпись")
    assert (await catalog.list_faq(client)).total == 1

    await catalog.toggle_faq(admin, entry.id)
    assert (await catalog.list_faq(client)).total == 0
    assert (await catalog.list_faq(admin)).total == 1
    with pytest.raises(NotFoundError):
        await catalog.get_faq(client, entry.id)


async def test_editable_texts_fall_back_to_defaults(session: AsyncSession, admin: User) -> None:
    catalog = CatalogService(session)
    assert "государственными закупками" in await catalog.get_text(BotTextKey.ABOUT)
    await catalog.set_text(admin, BotTextKey.CONTACTS, "📞 <b>0555 000 111</b>")
    assert await catalog.get_text(BotTextKey.CONTACTS) == "📞 <b>0555 000 111</b>"
    with pytest.raises(ValidationError):
        await catalog.set_text(admin, "unknown", "x")


async def test_blocked_client_has_no_access(session: AsyncSession) -> None:
    blocked = await create_user(
        session, telegram_id=4001, full_name="Заблокирован", is_active=False
    )
    with pytest.raises(PermissionDeniedError):
        await CatalogService(session).list_courses(blocked)
