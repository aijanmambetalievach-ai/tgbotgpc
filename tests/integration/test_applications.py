"""Applications: creation, conversation, status changes and access control."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import (
    ApplicationClosedError,
    ContentUnavailableError,
    DuplicateApplicationError,
    InvalidStatusTransitionError,
    PermissionDeniedError,
    ValidationError,
)
from app.models.enums import (
    ApplicationStatus,
    ApplicationType,
    ClientCategory,
    ConsultationTopic,
    ContactMethod,
    ContentStatus,
    MediaType,
)
from app.models.user import User
from app.services.application_service import ApplicationService, Attachment
from tests.integration.conftest import create_course, create_user

pytestmark = pytest.mark.integration


async def test_course_enrollment_is_numbered_and_announced_to_admins(
    session: AsyncSession, admin: User, client: User
) -> None:
    course = await create_course(session)
    created = await ApplicationService(session).enroll_in_course(client, course.id, "Есть вопрос")

    application = created.application
    assert application.number.startswith("ZV-")
    assert application.number.endswith("000001")
    assert application.type is ApplicationType.COURSE
    assert application.status is ApplicationStatus.NEW
    assert application.course_title == course.title
    assert [user.id for user in created.admins] == [admin.id]
    assert created.first_message.text == "Есть вопрос"


async def test_second_open_enrollment_in_the_same_course_is_refused(
    session: AsyncSession, admin: User, client: User
) -> None:
    course = await create_course(session)
    service = ApplicationService(session)
    first = await service.enroll_in_course(client, course.id)
    with pytest.raises(DuplicateApplicationError):
        await service.enroll_in_course(client, course.id)

    # Once the first one is closed the client may sign up again.
    await service.complete(admin, first.application.id)
    again = await service.enroll_in_course(client, course.id)
    assert again.application.number.endswith("000002")


async def test_unpublished_course_cannot_be_joined(session: AsyncSession, client: User) -> None:
    course = await create_course(session, status=ContentStatus.DRAFT)
    with pytest.raises(ContentUnavailableError):
        await ApplicationService(session).enroll_in_course(client, course.id)


async def test_contact_details_are_required(session: AsyncSession) -> None:
    anonymous = await create_user(session, telegram_id=3001, full_name="Без Телефона", phone=None)
    with pytest.raises(ValidationError, match="телефон"):
        await ApplicationService(session).request_individual(anonymous, "Хочу научиться")


async def test_consultation_conversation_flow(
    session: AsyncSession, admin: User, client: User
) -> None:
    service = ApplicationService(session)
    created = await service.request_consultation(
        client,
        ConsultationTopic.PORTAL,
        "Не могу опубликовать объявление",
        ContactMethod.TELEGRAM,
        attachment=Attachment(MediaType.PHOTO, "photo-file-id"),
    )
    app_id = created.application.id
    assert created.first_message.media_file_id == "photo-file-id"

    reply = await service.staff_reply(admin, app_id, "<b>Проверьте</b> статус плана")
    assert reply.application.status is ApplicationStatus.IN_PROGRESS
    assert reply.application.assignee_id == admin.id
    assert [user.id for user in reply.recipients] == [client.id]

    answer = await service.client_message(client, app_id, "Спасибо, получилось!")
    # The client's follow-up goes to the consultant who took the application.
    assert [user.id for user in answer.recipients] == [admin.id]

    thread = await service.get_thread(client, app_id)
    assert [m.from_staff for m in thread.messages] == [False, True, False]

    await service.complete(admin, app_id)
    with pytest.raises(ApplicationClosedError):
        await service.client_message(client, app_id, "И еще вопрос")
    with pytest.raises(ApplicationClosedError):
        await service.staff_reply(admin, app_id, "Дополнение")


async def test_clients_cannot_see_or_touch_other_clients_applications(
    session: AsyncSession, admin: User, client: User, other_client: User
) -> None:
    service = ApplicationService(session)
    created = await service.request_individual(client, "Хочу научиться работать с порталом")
    app_id = created.application.id

    with pytest.raises(PermissionDeniedError):
        await service.get_thread(other_client, app_id)
    with pytest.raises(PermissionDeniedError):
        await service.client_message(other_client, app_id, "Чужое сообщение")
    with pytest.raises(PermissionDeniedError):
        await service.cancel(other_client, app_id)
    with pytest.raises(PermissionDeniedError):
        await service.staff_reply(client, app_id, "Я не консультант")
    with pytest.raises(PermissionDeniedError):
        await service.list_for_admin(client)

    own = await service.list_own(other_client)
    assert own.total == 0


async def test_tender_support_only_for_suppliers(
    session: AsyncSession, admin: User, client: User, other_client: User
) -> None:
    service = ApplicationService(session)
    assert client.category is ClientCategory.SUPPLIER
    created = await service.request_support(
        client,
        "Объявление №12345, поставка мебели, подача до 25 октября",
        ContactMethod.PHONE,
        attachment=Attachment(MediaType.DOCUMENT, "tender-docs"),
        preferred_time="завтра после 14:00",
    )
    assert created.application.type is ApplicationType.SUPPORT
    assert created.application.preferred_time == "завтра после 14:00"

    assert other_client.category is ClientCategory.PURCHASER
    with pytest.raises(ContentUnavailableError, match="для поставщиков"):
        await service.request_support(other_client, "Хочу сопровождение")


async def test_status_changes(session: AsyncSession, admin: User, client: User) -> None:
    service = ApplicationService(session)
    first = (await service.request_individual(client, "Программа обучения для отдела")).application
    taken = await service.take(admin, first.id)
    assert taken.previous is ApplicationStatus.NEW
    assert taken.application.status is ApplicationStatus.IN_PROGRESS

    with pytest.raises(ValidationError):
        await service.reject(admin, first.id, "нет")
    rejected = await service.reject(admin, first.id, "Группа уже набрана, предложим другую дату")
    assert rejected.application.status is ApplicationStatus.REJECTED
    assert rejected.application.closed_at is not None
    with pytest.raises(InvalidStatusTransitionError):
        await service.cancel(client, first.id)

    second = (await service.request_individual(client, "Еще одна заявка на обучение")).application
    cancelled = await service.cancel(client, second.id)
    assert cancelled.application.status is ApplicationStatus.CANCELLED

    new = await service.list_for_admin(admin, "new")
    closed = await service.list_for_admin(admin, "closed")
    assert new.total == 0
    assert closed.total == 2


async def test_open_application_limit(
    session: AsyncSession, admin: User, client: User, settings: object
) -> None:
    service = ApplicationService(session)
    service.settings = service.settings.model_copy(update={"max_open_applications": 2})
    await service.request_individual(client, "Первая заявка")
    await service.request_individual(client, "Вторая заявка")
    with pytest.raises(ValidationError, match="много открытых"):
        await service.request_individual(client, "Третья заявка")
