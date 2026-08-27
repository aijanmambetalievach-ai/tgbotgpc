"""Procurement lifecycle: create → publish → close/complete."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.exceptions import (
    LimitExceededError,
    NotAParticipantError,
    NotFoundError,
    ValidationError,
)
from app.domain.permissions import Permission, require_permission
from app.domain.text import sanitize_text
from app.domain.timeutils import to_local, utcnow
from app.domain.transitions import ensure_procurement_transition
from app.models.audit_log import AuditAction
from app.models.enums import ParticipantSelectionMode, ProcurementStatus
from app.models.procurement import Procurement
from app.models.user import User
from app.repositories.audit import AuditRepository
from app.repositories.base import Page
from app.repositories.numbering import NumberingRepository
from app.repositories.procurements import ProcurementRepository, ProcurementStats
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProcurementDraftInput:
    """Validated input for creating or updating a procurement."""

    title: str
    deadline: dt.datetime
    description: str | None = None
    participant_mode: ParticipantSelectionMode = ParticipantSelectionMode.ALL_ACTIVE
    participant_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PublishResult:
    procurement: Procurement
    participants: list[User]
    already_published: bool = False


@dataclass(frozen=True, slots=True)
class ProcurementCard:
    procurement: Procurement
    stats: ProcurementStats


class ProcurementService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.procurements = ProcurementRepository(session)
        self.users = UserRepository(session)
        self.numbering = NumberingRepository(session)
        self.audit = AuditRepository(session)

    # -- creation ----------------------------------------------------------
    async def create_draft(self, actor: User, data: ProcurementDraftInput) -> Procurement:
        require_permission(actor, Permission.PROCUREMENT_CREATE)
        title, description, deadline = self._validate(data)

        year = to_local(utcnow(), self.settings.timezone).year
        number = await self.numbering.next_procurement_number(year)
        procurement = self.procurements.add(
            procurement_number=number,
            title=title,
            description=description,
            deadline=deadline,
            created_by=actor.id,
            participant_mode=data.participant_mode,
            status=ProcurementStatus.DRAFT,
        )
        await self.session.flush()

        if data.participant_mode is ParticipantSelectionMode.MANUAL and data.participant_ids:
            await self._assign_participants(procurement.id, data.participant_ids)

        self.audit.log(
            action=AuditAction.PROCUREMENT_CREATED,
            entity_type="procurement",
            entity_id=procurement.id,
            actor_user_id=actor.id,
            payload={"number": number, "title": title, "mode": str(data.participant_mode)},
        )
        await self.session.commit()
        logger.info(
            "procurement draft created",
            extra={
                "operation": "create_procurement",
                "user_id": actor.id,
                "procurement_id": procurement.id,
                "result": "ok",
            },
        )
        return procurement

    async def publish(
        self,
        actor: User,
        procurement_id: int,
        participant_mode: ParticipantSelectionMode | None = None,
        participant_ids: list[int] | None = None,
    ) -> PublishResult:
        """Publish a draft and freeze its participant list.

        Idempotent: publishing an already-open procurement returns the current
        state instead of duplicating participants or notifications.
        """
        require_permission(actor, Permission.PROCUREMENT_PUBLISH)

        procurement = await self.procurements.get_for_update(procurement_id)
        if procurement is None:
            raise NotFoundError("Закупка не найдена.")

        if procurement.status is ProcurementStatus.OPEN:
            participants = await self._load_participants(procurement.id)
            await self.session.commit()
            return PublishResult(procurement, participants, already_published=True)

        ensure_procurement_transition(procurement.status, ProcurementStatus.OPEN)

        now = utcnow()
        if procurement.deadline <= now:
            raise ValidationError("Срок подачи заявок должен быть в будущем.")

        mode = participant_mode or procurement.participant_mode
        if mode is ParticipantSelectionMode.ALL_ACTIVE:
            ids = [user.id for user in await self.users.list_active_purchasers()]
        else:
            ids = list(participant_ids or await self.procurements.list_participant_user_ids(
                procurement.id
            ))

        if not ids:
            raise ValidationError(
                "Не выбран ни один закупщик. Добавьте закупщиков или выберите участников."
            )

        procurement.participant_mode = mode
        await self._assign_participants(procurement.id, ids)

        procurement.status = ProcurementStatus.OPEN
        procurement.published_at = now

        self.audit.log(
            action=AuditAction.PROCUREMENT_PUBLISHED,
            entity_type="procurement",
            entity_id=procurement.id,
            actor_user_id=actor.id,
            payload={
                "number": procurement.procurement_number,
                "participants": len(ids),
                "mode": str(mode),
            },
        )
        await self.session.commit()

        participants = await self._load_participants(procurement.id)
        logger.info(
            "procurement published",
            extra={
                "operation": "publish_procurement",
                "user_id": actor.id,
                "procurement_id": procurement.id,
                "result": "ok",
            },
        )
        return PublishResult(procurement, participants)

    async def create_and_publish(
        self, actor: User, data: ProcurementDraftInput
    ) -> PublishResult:
        procurement = await self.create_draft(actor, data)
        return await self.publish(
            actor, procurement.id, data.participant_mode, data.participant_ids
        )

    # -- updates -----------------------------------------------------------
    async def update_fields(
        self,
        actor: User,
        procurement_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        deadline: dt.datetime | None = None,
    ) -> Procurement:
        require_permission(actor, Permission.PROCUREMENT_UPDATE)
        procurement = await self.procurements.get_for_update(procurement_id)
        if procurement is None:
            raise NotFoundError("Закупка не найдена.")
        if procurement.status in (ProcurementStatus.CANCELLED, ProcurementStatus.COMPLETED):
            raise ValidationError("Завершенную или отмененную закупку изменить нельзя.")

        changes: dict[str, object] = {}
        if title is not None:
            clean = sanitize_text(title, self.settings.max_procurement_title_length)
            if len(clean) < 3:
                raise ValidationError("Название должно содержать минимум 3 символа.")
            procurement.title = clean
            changes["title"] = clean
        if description is not None:
            procurement.description = (
                sanitize_text(description, self.settings.max_procurement_description_length)
                or None
            )
            changes["description"] = True
        if deadline is not None:
            procurement.deadline = deadline
            changes["deadline"] = deadline.isoformat()

        if changes:
            self.audit.log(
                action=AuditAction.PROCUREMENT_UPDATED,
                entity_type="procurement",
                entity_id=procurement.id,
                actor_user_id=actor.id,
                payload=changes,
            )
        await self.session.commit()
        return procurement

    async def extend_deadline(
        self, actor: User, procurement_id: int, new_deadline: dt.datetime
    ) -> Procurement:
        """Move the deadline forward. Always audited (requirement 33)."""
        require_permission(actor, Permission.PROCUREMENT_EXTEND_DEADLINE)
        procurement = await self.procurements.get_for_update(procurement_id)
        if procurement is None:
            raise NotFoundError("Закупка не найдена.")
        if procurement.status in (ProcurementStatus.CANCELLED, ProcurementStatus.COMPLETED):
            raise ValidationError("Нельзя продлить срок завершенной или отмененной закупки.")

        now = utcnow()
        if new_deadline <= now:
            raise ValidationError("Новый срок должен быть в будущем.")

        old_deadline = procurement.deadline
        procurement.deadline = new_deadline
        if procurement.status is ProcurementStatus.CLOSED:
            # Reopen so purchasers can submit again.
            ensure_procurement_transition(procurement.status, ProcurementStatus.OPEN)
            procurement.status = ProcurementStatus.OPEN
            procurement.closed_at = None

        self.audit.log(
            action=AuditAction.PROCUREMENT_DEADLINE_EXTENDED,
            entity_type="procurement",
            entity_id=procurement.id,
            actor_user_id=actor.id,
            payload={
                "old_deadline": old_deadline.isoformat(),
                "new_deadline": new_deadline.isoformat(),
            },
        )
        await self.session.commit()
        logger.info(
            "procurement deadline extended",
            extra={
                "operation": "extend_deadline",
                "user_id": actor.id,
                "procurement_id": procurement.id,
            },
        )
        return procurement

    async def change_status(
        self, actor: User, procurement_id: int, new_status: ProcurementStatus
    ) -> Procurement:
        permission = {
            ProcurementStatus.CLOSED: Permission.PROCUREMENT_CLOSE,
            ProcurementStatus.CANCELLED: Permission.PROCUREMENT_CANCEL,
            ProcurementStatus.COMPLETED: Permission.PROCUREMENT_COMPLETE,
            ProcurementStatus.OPEN: Permission.PROCUREMENT_PUBLISH,
        }.get(new_status, Permission.PROCUREMENT_UPDATE)
        require_permission(actor, permission)

        procurement = await self.procurements.get_for_update(procurement_id)
        if procurement is None:
            raise NotFoundError("Закупка не найдена.")
        if procurement.status is new_status:
            await self.session.commit()
            return procurement  # idempotent

        ensure_procurement_transition(procurement.status, new_status)
        procurement.status = new_status
        now = utcnow()
        if new_status in (ProcurementStatus.CLOSED, ProcurementStatus.CANCELLED):
            procurement.closed_at = now
        if new_status is ProcurementStatus.COMPLETED and procurement.closed_at is None:
            procurement.closed_at = now

        action = {
            ProcurementStatus.CLOSED: AuditAction.PROCUREMENT_CLOSED,
            ProcurementStatus.CANCELLED: AuditAction.PROCUREMENT_CANCELLED,
            ProcurementStatus.COMPLETED: AuditAction.PROCUREMENT_COMPLETED,
        }.get(new_status, AuditAction.PROCUREMENT_UPDATED)
        self.audit.log(
            action=action,
            entity_type="procurement",
            entity_id=procurement.id,
            actor_user_id=actor.id,
            payload={"status": str(new_status)},
        )
        await self.session.commit()
        return procurement

    async def set_participants(
        self, actor: User, procurement_id: int, participant_ids: list[int]
    ) -> int:
        require_permission(actor, Permission.PROCUREMENT_UPDATE)
        procurement = await self.procurements.get_for_update(procurement_id)
        if procurement is None:
            raise NotFoundError("Закупка не найдена.")
        added = await self._assign_participants(procurement_id, participant_ids)
        procurement.participant_mode = ParticipantSelectionMode.MANUAL
        self.audit.log(
            action=AuditAction.PROCUREMENT_PARTICIPANTS_SET,
            entity_type="procurement",
            entity_id=procurement_id,
            actor_user_id=actor.id,
            payload={"requested": len(participant_ids), "added": added},
        )
        await self.session.commit()
        return added

    # -- queries -----------------------------------------------------------
    async def list_for_employee(
        self,
        actor: User,
        statuses: list[ProcurementStatus],
        page: int = 1,
        page_size: int | None = None,
    ) -> Page[Procurement]:
        require_permission(actor, Permission.PROCUREMENT_VIEW_ALL)
        return await self.procurements.list_by_statuses(
            statuses, page=page, page_size=page_size or self.settings.page_size
        )

    async def get_card(self, actor: User, procurement_id: int) -> ProcurementCard:
        require_permission(actor, Permission.PROCUREMENT_VIEW_ALL)
        procurement = await self.procurements.get_by_id(procurement_id)
        if procurement is None:
            raise NotFoundError("Закупка не найдена.")
        return ProcurementCard(procurement, await self.procurements.stats(procurement_id))

    async def stats_for(self, procurement_ids: list[int]) -> dict[int, ProcurementStats]:
        return await self.procurements.stats_for_many(procurement_ids)

    async def list_participants(
        self, actor: User, procurement_id: int, page: int = 1, page_size: int | None = None
    ) -> Page[User]:
        require_permission(actor, Permission.PROCUREMENT_VIEW_ALL)
        return await self.procurements.list_participants(
            procurement_id, page=page, page_size=page_size or self.settings.page_size
        )

    async def list_non_responders(self, actor: User, procurement_id: int) -> list[User]:
        require_permission(actor, Permission.PROCUREMENT_REMIND)
        return await self.procurements.list_non_responders(procurement_id)

    async def list_for_purchaser(
        self,
        actor: User,
        page: int = 1,
        page_size: int | None = None,
        only_open: bool = True,
    ) -> Page[Procurement]:
        require_permission(actor, Permission.REQUEST_VIEW_OWN)
        return await self.procurements.list_available_for_user(
            actor.id, page=page, page_size=page_size or self.settings.page_size,
            only_open=only_open,
        )

    async def get_for_purchaser(self, actor: User, procurement_id: int) -> Procurement:
        """Fetch a procurement, enforcing participation server-side."""
        require_permission(actor, Permission.REQUEST_VIEW_OWN)
        procurement = await self.procurements.get_by_id(procurement_id)
        if procurement is None:
            raise NotFoundError("Закупка не найдена.")
        if not await self.procurements.is_participant(procurement_id, actor.id):
            raise NotAParticipantError()
        if procurement.status is ProcurementStatus.DRAFT:
            raise NotAParticipantError()
        return procurement

    async def mark_reminder_sent(
        self, actor: User, procurement_id: int, recipients: int
    ) -> None:
        self.audit.log(
            action=AuditAction.PROCUREMENT_REMINDER_SENT,
            entity_type="procurement",
            entity_id=procurement_id,
            actor_user_id=actor.id,
            payload={"recipients": recipients},
        )
        await self.session.commit()

    # -- internals ---------------------------------------------------------
    async def _assign_participants(self, procurement_id: int, user_ids: list[int]) -> int:
        unique_ids = list(dict.fromkeys(user_ids))
        if len(unique_ids) > self.settings.max_participants_per_procurement:
            raise LimitExceededError(
                "Слишком много участников: максимум "
                f"{self.settings.max_participants_per_procurement}."
            )
        if not unique_ids:
            return 0
        known = {user.id for user in await self.users.list_by_ids(unique_ids)}
        unknown = set(unique_ids) - known
        if unknown:
            raise ValidationError("Часть выбранных пользователей не найдена.")
        return await self.procurements.set_participants(procurement_id, unique_ids)

    async def _load_participants(self, procurement_id: int) -> list[User]:
        ids = await self.procurements.list_participant_user_ids(procurement_id)
        return await self.users.list_by_ids(ids)

    def _validate(self, data: ProcurementDraftInput) -> tuple[str, str | None, dt.datetime]:
        title = sanitize_text(data.title, self.settings.max_procurement_title_length)
        if len(title) < 3:
            raise ValidationError("Название должно содержать минимум 3 символа.")
        description = (
            sanitize_text(data.description, self.settings.max_procurement_description_length)
            or None
        )
        deadline = data.deadline
        if deadline.tzinfo is None:
            raise ValidationError("Внутренняя ошибка: срок без часового пояса.")
        return title, description, deadline
