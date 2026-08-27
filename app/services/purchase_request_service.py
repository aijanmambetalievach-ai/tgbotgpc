"""Purchase request lifecycle: draft → submit → status changes."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.exceptions import (
    DeadlineExpiredError,
    LimitExceededError,
    NotAParticipantError,
    NotFoundError,
    PermissionDeniedError,
    ProcurementNotAcceptingError,
    ValidationError,
)
from app.domain.permissions import Permission, has_permission, require_permission
from app.domain.text import humanize_name, normalize_item_name, sanitize_text
from app.domain.timeutils import to_local, utcnow
from app.domain.transitions import ensure_request_transition
from app.models.audit_log import AuditAction
from app.models.enums import ProcurementStatus, PurchaseRequestStatus
from app.models.procurement import Procurement
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_item import PurchaseRequestItem
from app.models.user import User
from app.parsers.base import ParsedItem
from app.repositories.audit import AuditRepository
from app.repositories.base import Page
from app.repositories.numbering import NumberingRepository
from app.repositories.procurements import ProcurementRepository
from app.repositories.purchase_requests import PurchaseRequestRepository

logger = logging.getLogger(__name__)

MIN_SUBJECT_LENGTH = 3


@dataclass(frozen=True, slots=True)
class DraftResult:
    request: PurchaseRequest
    #: ``None`` for a self-initiated request that belongs to no procurement.
    procurement: Procurement | None
    is_new: bool
    already_submitted: bool


@dataclass(frozen=True, slots=True)
class SubmitResult:
    request: PurchaseRequest
    procurement: Procurement | None
    purchaser: User
    items: list[PurchaseRequestItem]
    already_submitted: bool = False


@dataclass(frozen=True, slots=True)
class StatusChangeResult:
    request: PurchaseRequest
    purchaser: User
    procurement: Procurement | None
    old_status: PurchaseRequestStatus
    new_status: PurchaseRequestStatus
    changed: bool


class PurchaseRequestService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.requests = PurchaseRequestRepository(session)
        self.procurements = ProcurementRepository(session)
        self.numbering = NumberingRepository(session)
        self.audit = AuditRepository(session)

    # -- drafting ----------------------------------------------------------
    async def get_or_create_draft(self, actor: User, procurement_id: int) -> DraftResult:
        """Open the purchaser's request for a procurement, creating it if needed.

        Per the MVP rule one purchaser has at most one request per procurement:
        an existing draft is reused, an already submitted request is returned
        untouched.
        """
        require_permission(actor, Permission.REQUEST_SUBMIT)
        procurement = await self._require_participation(actor, procurement_id)

        existing = await self.requests.get_by_pair(procurement_id, actor.id)
        if existing is not None:
            return DraftResult(
                request=existing,
                procurement=procurement,
                is_new=False,
                already_submitted=existing.is_submitted,
            )

        self._ensure_accepting(procurement)
        request = self.requests.add(procurement_id=procurement_id, purchaser_id=actor.id)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.requests.get_by_pair(procurement_id, actor.id)
            if existing is None:  # pragma: no cover - defensive
                raise
            return DraftResult(existing, procurement, False, existing.is_submitted)

        self.audit.log(
            action=AuditAction.REQUEST_DRAFT_CREATED,
            entity_type="purchase_request",
            entity_id=request.id,
            actor_user_id=actor.id,
            payload={"procurement_id": procurement_id},
        )
        await self.session.commit()
        return DraftResult(request, procurement, True, False)

    async def create_self_initiated_draft(self, actor: User, subject: str) -> DraftResult:
        """Start a request the purchaser raises on their own initiative.

        Such a request belongs to no procurement; it goes straight to the
        tender employees for approval. At most one self-initiated draft exists
        per purchaser at a time — a second attempt reuses (and renames) the
        open draft instead of littering the table with abandoned rows.
        """
        require_permission(actor, Permission.REQUEST_SUBMIT)
        clean_subject = sanitize_text(subject, self.settings.max_procurement_title_length)
        if len(clean_subject) < MIN_SUBJECT_LENGTH:
            raise ValidationError(
                f"Опишите тему заявки — минимум {MIN_SUBJECT_LENGTH} символа."
            )

        existing = await self.requests.get_self_initiated_draft(actor.id)
        if existing is not None:
            existing.subject = clean_subject
            await self.session.commit()
            return DraftResult(existing, None, is_new=False, already_submitted=False)

        request = self.requests.add(
            procurement_id=None, purchaser_id=actor.id, subject=clean_subject
        )
        await self.session.flush()
        self.audit.log(
            action=AuditAction.REQUEST_DRAFT_CREATED,
            entity_type="purchase_request",
            entity_id=request.id,
            actor_user_id=actor.id,
            payload={"self_initiated": True, "subject": clean_subject},
        )
        await self.session.commit()
        logger.info(
            "self-initiated draft created",
            extra={
                "operation": "create_self_initiated_draft",
                "user_id": actor.id,
                "purchase_request_id": request.id,
                "result": "ok",
            },
        )
        return DraftResult(request, None, is_new=True, already_submitted=False)

    async def replace_items(
        self, actor: User, request_id: int, items: Sequence[ParsedItem]
    ) -> list[PurchaseRequestItem]:
        """Persist the parsed item list, replacing whatever the draft held."""
        require_permission(actor, Permission.REQUEST_SUBMIT)
        request = await self._require_own_draft(actor, request_id)

        if not items:
            raise ValidationError("Список товаров пуст.")
        if len(items) > self.settings.max_items_per_request:
            raise LimitExceededError(
                f"Слишком много позиций: максимум {self.settings.max_items_per_request}."
            )

        await self.requests.delete_items(request.id)
        stored: list[PurchaseRequestItem] = []
        for position, parsed in enumerate(items, start=1):
            name = humanize_name(sanitize_text(parsed.name, self.settings.max_item_name_length))
            if not name:
                raise ValidationError(f"Позиция {position}: не указано наименование.")
            if parsed.quantity <= 0:
                raise ValidationError(f"Позиция {position}: количество должно быть больше нуля.")
            stored.append(
                self.requests.add_item(
                    request_id=request.id,
                    position=position,
                    name=name,
                    normalized_name=normalize_item_name(name),
                    quantity=parsed.quantity,
                    unit=parsed.unit,
                    comment=sanitize_text(parsed.comment, self.settings.max_comment_length)
                    or None,
                    source_text=sanitize_text(parsed.source_text, 1000) or None,
                )
            )
        await self.session.flush()
        self.audit.log(
            action=AuditAction.REQUEST_ITEMS_REPLACED,
            entity_type="purchase_request",
            entity_id=request.id,
            actor_user_id=actor.id,
            payload={"items": len(stored)},
        )
        await self.session.commit()
        return stored

    async def set_comment(
        self, actor: User, request_id: int, comment: str | None
    ) -> PurchaseRequest:
        require_permission(actor, Permission.REQUEST_SUBMIT)
        request = await self._require_own_draft(actor, request_id)
        request.comment = sanitize_text(comment, self.settings.max_comment_length) or None
        await self.session.commit()
        return request

    # -- submission --------------------------------------------------------
    async def submit(self, actor: User, request_id: int) -> SubmitResult:
        """Atomically validate and submit a draft.

        Everything below happens inside one transaction with the request row
        locked, so a double tap can never produce two submissions or two
        request numbers. Telegram notifications are sent by the caller *after*
        this method commits.
        """
        require_permission(actor, Permission.REQUEST_SUBMIT)

        request = await self.requests.get_for_update(request_id)
        if request is None:
            raise NotFoundError("Заявка не найдена.")
        if request.purchaser_id != actor.id:
            raise PermissionDeniedError("Это чужая заявка.")

        procurement: Procurement | None = None
        if request.procurement_id is not None:
            procurement = await self.procurements.get_by_id(request.procurement_id)
            if procurement is None:  # pragma: no cover - FK guarantees existence
                raise NotFoundError("Закупка не найдена.")

        items = await self.requests.list_items(request.id)

        if request.status is not PurchaseRequestStatus.DRAFT:
            # Idempotent: already submitted (double tap / repeated update).
            await self.session.commit()
            return SubmitResult(request, procurement, actor, items, already_submitted=True)

        # Participation and deadline only constrain procurement-bound requests;
        # a self-initiated one has neither.
        if procurement is not None:
            if not await self.procurements.is_participant(procurement.id, actor.id):
                raise NotAParticipantError()
            self._ensure_accepting(procurement)

        if not items:
            raise ValidationError("Нельзя отправить пустую заявку.")
        if len(items) > self.settings.max_items_per_request:
            raise LimitExceededError(
                f"Слишком много позиций: максимум {self.settings.max_items_per_request}."
            )

        now = utcnow()
        if request.request_number is None:
            year = to_local(now, self.settings.timezone).year
            request.request_number = await self.numbering.next_request_number(year)

        old_status = request.status
        request.status = PurchaseRequestStatus.SUBMITTED
        request.submitted_at = now
        self.requests.add_history(
            request_id=request.id,
            old_status=old_status,
            new_status=PurchaseRequestStatus.SUBMITTED,
            changed_by=actor.id,
        )
        self.audit.log(
            action=AuditAction.REQUEST_SUBMITTED,
            entity_type="purchase_request",
            entity_id=request.id,
            actor_user_id=actor.id,
            payload={
                "procurement_id": procurement.id if procurement else None,
                "self_initiated": procurement is None,
                "number": request.request_number,
                "items": len(items),
            },
        )
        await self.session.commit()

        logger.info(
            "purchase request submitted",
            extra={
                "operation": "submit_request",
                "user_id": actor.id,
                "procurement_id": procurement.id if procurement else None,
                "purchase_request_id": request.id,
                "result": "ok",
            },
        )
        return SubmitResult(request, procurement, actor, items)

    # -- employee side -----------------------------------------------------
    async def change_status(
        self,
        actor: User,
        request_id: int,
        new_status: PurchaseRequestStatus,
        comment: str | None = None,
    ) -> StatusChangeResult:
        require_permission(actor, Permission.REQUEST_CHANGE_STATUS)

        if new_status is PurchaseRequestStatus.REJECTED:
            reason = sanitize_text(comment, self.settings.max_comment_length)
            if len(reason) < 3:
                raise ValidationError("Для отклонения заявки нужно указать причину.")
            comment = reason
        else:
            comment = sanitize_text(comment, self.settings.max_comment_length) or None

        request = await self.requests.get_for_update(request_id)
        if request is None:
            raise NotFoundError("Заявка не найдена.")

        purchaser = await self.session.get(User, request.purchaser_id)
        if purchaser is None:  # pragma: no cover - FK guarantees
            raise NotFoundError("Заявка не найдена.")
        procurement = (
            await self.procurements.get_by_id(request.procurement_id)
            if request.procurement_id is not None
            else None
        )

        old_status = request.status
        if old_status is new_status:
            await self.session.commit()
            return StatusChangeResult(
                request, purchaser, procurement, old_status, new_status, changed=False
            )

        ensure_request_transition(old_status, new_status)
        request.status = new_status
        if new_status is PurchaseRequestStatus.REJECTED:
            request.rejection_reason = comment

        self.requests.add_history(
            request_id=request.id,
            old_status=old_status,
            new_status=new_status,
            changed_by=actor.id,
            comment=comment,
        )
        self.audit.log(
            action=AuditAction.REQUEST_STATUS_CHANGED,
            entity_type="purchase_request",
            entity_id=request.id,
            actor_user_id=actor.id,
            payload={"old": str(old_status), "new": str(new_status)},
        )
        await self.session.commit()
        logger.info(
            "request status changed",
            extra={
                "operation": "change_request_status",
                "user_id": actor.id,
                "purchase_request_id": request.id,
                "result": str(new_status),
            },
        )
        return StatusChangeResult(
            request, purchaser, procurement, old_status, new_status, changed=True
        )

    # -- queries -----------------------------------------------------------
    async def get_for_actor(self, actor: User, request_id: int) -> PurchaseRequest:
        """Load a request, enforcing ownership for purchasers."""
        request = await self.requests.get_by_id(request_id)
        if request is None:
            raise NotFoundError("Заявка не найдена.")
        if has_permission(actor, Permission.REQUEST_VIEW_ALL):
            return request
        require_permission(actor, Permission.REQUEST_VIEW_OWN)
        if request.purchaser_id != actor.id:
            raise PermissionDeniedError("Это чужая заявка.")
        return request

    async def list_items(self, actor: User, request_id: int) -> list[PurchaseRequestItem]:
        await self.get_for_actor(actor, request_id)
        return await self.requests.list_items(request_id)

    async def get_own_request(
        self, actor: User, procurement_id: int
    ) -> PurchaseRequest | None:
        """The actor's own request for a procurement, if any."""
        require_permission(actor, Permission.REQUEST_VIEW_OWN)
        return await self.requests.get_by_pair(procurement_id, actor.id)

    async def get_procurement(self, request_id: int) -> Procurement | None:
        """The procurement a request belongs to, or ``None`` if self-initiated."""
        return await self.requests.get_procurement_of(request_id)

    async def list_own(
        self,
        actor: User,
        page: int = 1,
        page_size: int | None = None,
        statuses: Sequence[PurchaseRequestStatus] | None = None,
    ) -> Page[PurchaseRequest]:
        require_permission(actor, Permission.REQUEST_VIEW_OWN)
        return await self.requests.list_by_purchaser(
            actor.id,
            page=page,
            page_size=page_size or self.settings.page_size,
            statuses=statuses,
        )

    async def list_of_purchaser(
        self, actor: User, purchaser_id: int, page: int = 1, page_size: int | None = None
    ) -> Page[PurchaseRequest]:
        """All requests of a given purchaser — employees only."""
        require_permission(actor, Permission.REQUEST_VIEW_ALL)
        return await self.requests.list_by_purchaser(
            purchaser_id, page=page, page_size=page_size or self.settings.page_size
        )

    async def list_new(
        self, actor: User, page: int = 1, page_size: int | None = None
    ) -> Page[PurchaseRequest]:
        require_permission(actor, Permission.REQUEST_VIEW_ALL)
        return await self.requests.list_new(
            page=page, page_size=page_size or self.settings.page_size
        )

    async def list_by_procurement(
        self, actor: User, procurement_id: int, page: int = 1, page_size: int | None = None
    ) -> Page[PurchaseRequest]:
        require_permission(actor, Permission.REQUEST_VIEW_ALL)
        return await self.requests.list_by_procurement(
            procurement_id, page=page, page_size=page_size or self.settings.page_size
        )

    async def count_items(self, request_id: int) -> int:
        return await self.requests.count_items(request_id)

    # -- internals ---------------------------------------------------------
    async def _require_participation(self, actor: User, procurement_id: int) -> Procurement:
        procurement = await self.procurements.get_by_id(procurement_id)
        if procurement is None:
            raise NotFoundError("Закупка не найдена.")
        if procurement.status is ProcurementStatus.DRAFT:
            raise NotAParticipantError()
        if not await self.procurements.is_participant(procurement_id, actor.id):
            raise NotAParticipantError()
        return procurement

    async def _require_own_draft(self, actor: User, request_id: int) -> PurchaseRequest:
        request = await self.requests.get_by_id(request_id)
        if request is None:
            raise NotFoundError("Заявка не найдена.")
        if request.purchaser_id != actor.id:
            raise PermissionDeniedError("Это чужая заявка.")
        if request.status is not PurchaseRequestStatus.DRAFT:
            raise ValidationError("Отправленную заявку изменить нельзя.")
        return request

    @staticmethod
    def _ensure_accepting(procurement: Procurement) -> None:
        now = utcnow()
        if procurement.status is not ProcurementStatus.OPEN:
            raise ProcurementNotAcceptingError()
        if procurement.is_expired(now):
            raise DeadlineExpiredError()
