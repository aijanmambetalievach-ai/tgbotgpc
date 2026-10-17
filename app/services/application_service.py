"""Client applications and the client ↔ consultant conversation.

Text conventions: what a *client* writes is stored as plain text (escaped when
rendered); what a *consultant* writes is stored as Telegram HTML taken from
``Message.html_text`` so their formatting survives. ``ApplicationMessage``'s
``from_staff`` flag tells the renderer which one it is looking at.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.exceptions import (
    ApplicationClosedError,
    ContentUnavailableError,
    DuplicateApplicationError,
    NotFoundError,
    ValidationError,
)
from app.domain.permissions import require_active, require_admin, require_owner_or_admin
from app.domain.text import normalize_unicode, sanitize_text
from app.domain.timeutils import utcnow
from app.domain.transitions import CLOSED_STATUSES, ensure_transition
from app.models.application import Application, ApplicationMessage
from app.models.audit_log import AuditAction
from app.models.content import Course
from app.models.enums import (
    OPEN_APPLICATION_STATUSES,
    ApplicationStatus,
    ApplicationType,
    ConsultationTopic,
    ContactMethod,
    ContentStatus,
    MediaType,
)
from app.models.user import User
from app.repositories.applications import ApplicationRepository, ApplicationRow
from app.repositories.audit import AuditRepository
from app.repositories.base import Page
from app.repositories.content import CourseRepository
from app.repositories.numbering import NumberingRepository
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)

MIN_DESCRIPTION_LENGTH = 5
MAX_PREFERRED_TIME_LENGTH = 300
MAX_REASON_LENGTH = 1000

#: Admin list filters: scope name -> statuses (``None`` = everything).
ADMIN_SCOPES: dict[str, tuple[ApplicationStatus, ...] | None] = {
    "new": (ApplicationStatus.NEW,),
    "active": (ApplicationStatus.IN_PROGRESS,),
    "closed": tuple(CLOSED_STATUSES),
    "all": None,
}


@dataclass(frozen=True, slots=True)
class Attachment:
    media_type: MediaType
    file_id: str


@dataclass(frozen=True, slots=True)
class CreatedApplication:
    application: Application
    client: User
    first_message: ApplicationMessage
    admins: list[User]


@dataclass(frozen=True, slots=True)
class ApplicationThread:
    application: Application
    client: User
    messages: list[ApplicationMessage]
    assignee: User | None


@dataclass(frozen=True, slots=True)
class PostedMessage:
    application: Application
    client: User
    message: ApplicationMessage
    #: Who should be told about it (the client for staff replies; the
    #: assignee or all admins for client messages).
    recipients: list[User]


@dataclass(frozen=True, slots=True)
class StatusChange:
    application: Application
    client: User
    previous: ApplicationStatus


@dataclass(frozen=True, slots=True)
class ApplicationStats:
    by_status: dict[ApplicationStatus, int]
    last_7_days: dict[ApplicationType, int]


class ApplicationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.applications = ApplicationRepository(session)
        self.courses = CourseRepository(session)
        self.users = UserRepository(session)
        self.numbering = NumberingRepository(session)
        self.audit = AuditRepository(session)

    # ======================================================================
    # Creation (clients)
    # ======================================================================
    async def enroll_in_course(
        self, client: User, course_id: int, comment: str = ""
    ) -> CreatedApplication:
        self._check_client(client)
        course = await self.courses.get(course_id)
        if course is None or course.status is not ContentStatus.PUBLISHED:
            raise ContentUnavailableError("Запись на этот курс закрыта.")
        if await self.applications.find_open_course_application(client.id, course.id):
            raise DuplicateApplicationError()
        return await self._create(
            client,
            kind=ApplicationType.COURSE,
            description=sanitize_text(comment, self.settings.max_text_length),
            course=course,
        )

    async def request_individual(
        self,
        client: User,
        description: str,
        preferred_time: str = "",
        contact_method: ContactMethod = ContactMethod.TELEGRAM,
    ) -> CreatedApplication:
        self._check_client(client)
        return await self._create(
            client,
            kind=ApplicationType.INDIVIDUAL,
            description=self._description(description),
            preferred_time=preferred_time,
            contact_method=contact_method,
        )

    async def request_consultation(
        self,
        client: User,
        topic: ConsultationTopic,
        description: str,
        contact_method: ContactMethod = ContactMethod.TELEGRAM,
        attachment: Attachment | None = None,
        preferred_time: str = "",
    ) -> CreatedApplication:
        self._check_client(client)
        return await self._create(
            client,
            kind=ApplicationType.CONSULTATION,
            description=self._description(description, allow_empty=attachment is not None),
            topic=topic,
            contact_method=contact_method,
            attachment=attachment,
            preferred_time=preferred_time,
        )

    async def _create(
        self,
        client: User,
        *,
        kind: ApplicationType,
        description: str,
        course: Course | None = None,
        topic: ConsultationTopic | None = None,
        preferred_time: str = "",
        contact_method: ContactMethod = ContactMethod.TELEGRAM,
        attachment: Attachment | None = None,
    ) -> CreatedApplication:
        if await self.applications.count_open_of(client.id) >= self.settings.max_open_applications:
            raise ValidationError(
                "У вас уже много открытых заявок. Дождитесь ответа по ним "
                "или отмените лишние в разделе «📋 Мои заявки»."
            )
        now = utcnow()
        application = self.applications.add(
            Application(
                number=await self.numbering.next_application_number(now.year),
                type=kind,
                status=ApplicationStatus.NEW,
                client_id=client.id,
                course_id=course.id if course else None,
                course_title=course.title if course else None,
                topic=topic,
                description=description,
                preferred_time=sanitize_text(preferred_time, MAX_PREFERRED_TIME_LENGTH) or None,
                contact_method=contact_method,
            )
        )
        await self.session.flush()
        first_message = self.applications.add_message(
            ApplicationMessage(
                application_id=application.id,
                author_id=client.id,
                from_staff=False,
                text=description,
                media_type=attachment.media_type if attachment else None,
                media_file_id=attachment.file_id if attachment else None,
            )
        )
        self.audit.log(
            action=AuditAction.APPLICATION_CREATED,
            entity_type="application",
            entity_id=application.id,
            actor_user_id=client.id,
            payload={"number": application.number, "type": str(kind)},
        )
        await self.session.commit()
        logger.info(
            "application created",
            extra={
                "operation": "application_create",
                "user_id": client.id,
                "entity_id": application.id,
                "result": str(kind),
            },
        )
        return CreatedApplication(
            application=application,
            client=client,
            first_message=first_message,
            admins=await self.users.list_admins(),
        )

    # ======================================================================
    # Reading
    # ======================================================================
    async def list_own(self, client: User, page: int = 1) -> Page[ApplicationRow]:
        require_active(client)
        return await self.applications.list_page(
            client_id=client.id, page=page, page_size=self.settings.page_size
        )

    async def list_for_admin(
        self, actor: User, scope: str = "new", page: int = 1
    ) -> Page[ApplicationRow]:
        require_admin(actor)
        if scope not in ADMIN_SCOPES:
            scope = "new"
        return await self.applications.list_page(
            statuses=ADMIN_SCOPES[scope], page=page, page_size=self.settings.page_size
        )

    async def list_of_client(
        self, actor: User, client_id: int, page: int = 1
    ) -> Page[ApplicationRow]:
        require_admin(actor)
        return await self.applications.list_page(
            client_id=client_id, page=page, page_size=self.settings.page_size
        )

    async def get_thread(self, user: User, application_id: int) -> ApplicationThread:
        application = await self._get(application_id)
        require_owner_or_admin(user, application.client_id)
        client = await self.users.get_by_id(application.client_id)
        if client is None:  # pragma: no cover - FK guarantees it
            raise NotFoundError()
        assignee = (
            await self.users.get_by_id(application.assignee_id) if application.assignee_id else None
        )
        return ApplicationThread(
            application=application,
            client=client,
            messages=await self.applications.messages(application.id),
            assignee=assignee,
        )

    async def stats(self, actor: User) -> ApplicationStats:
        require_admin(actor)
        return ApplicationStats(
            by_status=await self.applications.count_by_status(),
            last_7_days=await self.applications.count_by_type_since(
                utcnow() - dt.timedelta(days=7)
            ),
        )

    # ======================================================================
    # Conversation
    # ======================================================================
    async def staff_reply(
        self,
        actor: User,
        application_id: int,
        text_html: str,
        attachment: Attachment | None = None,
    ) -> PostedMessage:
        """A consultant answers. Replying to a new application takes it."""
        require_admin(actor)
        application = await self._get_for_update(application_id)
        if application.status not in OPEN_APPLICATION_STATUSES:
            raise ApplicationClosedError()
        text = normalize_unicode(text_html).strip()
        if len(text) > self.settings.max_text_length:
            raise ValidationError("Ответ слишком длинный — разделите его на несколько сообщений.")
        if not text and attachment is None:
            raise ValidationError("Напишите текст ответа или приложите файл.")

        if application.status is ApplicationStatus.NEW:
            application.status = ApplicationStatus.IN_PROGRESS
        if application.assignee_id is None:
            application.assignee_id = actor.id
        message = self._add_message(application, actor, True, text, attachment)
        self.audit.log(
            action=AuditAction.APPLICATION_REPLIED,
            entity_type="application",
            entity_id=application.id,
            actor_user_id=actor.id,
        )
        await self.session.commit()
        client = await self._client(application)
        return PostedMessage(
            application=application, client=client, message=message, recipients=[client]
        )

    async def client_message(
        self,
        client: User,
        application_id: int,
        text: str,
        attachment: Attachment | None = None,
    ) -> PostedMessage:
        require_active(client)
        application = await self._get_for_update(application_id)
        require_owner_or_admin(client, application.client_id)
        if application.status not in OPEN_APPLICATION_STATUSES:
            raise ApplicationClosedError(
                "Эта заявка уже закрыта. Если остались вопросы — создайте новую."
            )
        clean = sanitize_text(text, self.settings.max_text_length)
        if not clean and attachment is None:
            raise ValidationError("Сообщение пустое.")
        message = self._add_message(application, client, False, clean, attachment)
        await self.session.commit()

        recipients: list[User] = []
        if application.assignee_id:
            assignee = await self.users.get_by_id(application.assignee_id)
            if assignee is not None and assignee.is_admin and assignee.can_use_bot:
                recipients = [assignee]
        if not recipients:
            recipients = await self.users.list_admins()
        return PostedMessage(
            application=application, client=client, message=message, recipients=recipients
        )

    def _add_message(
        self,
        application: Application,
        author: User,
        from_staff: bool,
        text: str,
        attachment: Attachment | None,
    ) -> ApplicationMessage:
        application.updated_at = utcnow()
        return self.applications.add_message(
            ApplicationMessage(
                application_id=application.id,
                author_id=author.id,
                from_staff=from_staff,
                text=text,
                media_type=attachment.media_type if attachment else None,
                media_file_id=attachment.file_id if attachment else None,
            )
        )

    # ======================================================================
    # Status changes
    # ======================================================================
    async def take(self, actor: User, application_id: int) -> StatusChange:
        require_admin(actor)
        application = await self._get_for_update(application_id)
        previous = application.status
        ensure_transition(previous, ApplicationStatus.IN_PROGRESS, by_staff=True)
        application.status = ApplicationStatus.IN_PROGRESS
        application.assignee_id = actor.id
        return await self._finish_change(actor, application, previous)

    async def complete(self, actor: User, application_id: int) -> StatusChange:
        require_admin(actor)
        application = await self._get_for_update(application_id)
        previous = application.status
        ensure_transition(previous, ApplicationStatus.DONE, by_staff=True)
        application.status = ApplicationStatus.DONE
        application.closed_at = utcnow()
        application.assignee_id = application.assignee_id or actor.id
        return await self._finish_change(actor, application, previous)

    async def reject(self, actor: User, application_id: int, reason: str) -> StatusChange:
        require_admin(actor)
        clean = sanitize_text(reason, MAX_REASON_LENGTH)
        if len(clean) < MIN_DESCRIPTION_LENGTH:
            raise ValidationError("Укажите причину — клиент увидит ее в уведомлении.")
        application = await self._get_for_update(application_id)
        previous = application.status
        ensure_transition(previous, ApplicationStatus.REJECTED, by_staff=True)
        application.status = ApplicationStatus.REJECTED
        application.rejection_reason = clean
        application.closed_at = utcnow()
        return await self._finish_change(actor, application, previous)

    async def cancel(self, client: User, application_id: int) -> StatusChange:
        require_active(client)
        application = await self._get_for_update(application_id)
        require_owner_or_admin(client, application.client_id)
        previous = application.status
        ensure_transition(previous, ApplicationStatus.CANCELLED, by_staff=False)
        application.status = ApplicationStatus.CANCELLED
        application.closed_at = utcnow()
        return await self._finish_change(client, application, previous)

    async def _finish_change(
        self, actor: User, application: Application, previous: ApplicationStatus
    ) -> StatusChange:
        self.audit.log(
            action=AuditAction.APPLICATION_STATUS_CHANGED,
            entity_type="application",
            entity_id=application.id,
            actor_user_id=actor.id,
            payload={"from": str(previous), "to": str(application.status)},
        )
        await self.session.commit()
        return StatusChange(
            application=application, client=await self._client(application), previous=previous
        )

    # ======================================================================
    # helpers
    # ======================================================================
    def _check_client(self, client: User) -> None:
        require_active(client)
        if not client.has_contact_details:
            raise ValidationError("Сначала укажите имя и номер телефона.")

    def _description(self, raw: str, *, allow_empty: bool = False) -> str:
        clean = sanitize_text(raw, self.settings.max_text_length)
        if not allow_empty and len(clean) < MIN_DESCRIPTION_LENGTH:
            raise ValidationError("Опишите вопрос чуть подробнее — хотя бы несколько слов.")
        return clean

    async def _get(self, application_id: int) -> Application:
        application = await self.applications.get(application_id)
        if application is None:
            raise NotFoundError("Заявка не найдена.")
        return application

    async def _get_for_update(self, application_id: int) -> Application:
        application = await self.applications.get_for_update(application_id)
        if application is None:
            raise NotFoundError("Заявка не найдена.")
        return application

    async def _client(self, application: Application) -> User:
        client = await self.users.get_by_id(application.client_id)
        if client is None:  # pragma: no cover - FK guarantees it
            raise NotFoundError()
        return client
