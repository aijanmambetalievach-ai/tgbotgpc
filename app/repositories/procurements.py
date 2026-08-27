"""Procurement and participant persistence."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ParticipantSelectionMode, ProcurementStatus, PurchaseRequestStatus
from app.models.procurement import Procurement
from app.models.procurement_participant import ProcurementParticipant
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_item import PurchaseRequestItem
from app.models.user import User
from app.repositories.base import Page, normalize_page, offset_for

SUBMITTED_STATUSES: tuple[PurchaseRequestStatus, ...] = (
    PurchaseRequestStatus.SUBMITTED,
    PurchaseRequestStatus.VIEWED,
    PurchaseRequestStatus.IN_PROGRESS,
    PurchaseRequestStatus.COMPLETED,
    PurchaseRequestStatus.REJECTED,
)


@dataclass(frozen=True, slots=True)
class ProcurementStats:
    participants: int
    responded: int
    total_items: int

    @property
    def pending(self) -> int:
        return max(0, self.participants - self.responded)

    @property
    def response_rate(self) -> int:
        if self.participants <= 0:
            return 0
        return round(self.responded * 100 / self.participants)


class ProcurementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reads -------------------------------------------------------------
    async def get_by_id(self, procurement_id: int) -> Procurement | None:
        return await self.session.get(Procurement, procurement_id)

    async def get_for_update(self, procurement_id: int) -> Procurement | None:
        stmt = select(Procurement).where(Procurement.id == procurement_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_number(self, number: str) -> Procurement | None:
        stmt = select(Procurement).where(Procurement.procurement_number == number)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_statuses(
        self,
        statuses: Sequence[ProcurementStatus],
        page: int = 1,
        page_size: int = 10,
        created_by: int | None = None,
    ) -> Page[Procurement]:
        base = select(Procurement)
        if statuses:
            base = base.where(Procurement.status.in_(list(statuses)))
        if created_by is not None:
            base = base.where(Procurement.created_by == created_by)
        total = await self._count(base)
        page = normalize_page(page, page_size, total)
        stmt = (
            base.order_by(Procurement.created_at.desc(), Procurement.id.desc())
            .offset(offset_for(page, page_size))
            .limit(page_size)
        )
        return Page(
            items=list((await self.session.execute(stmt)).scalars().all()),
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_available_for_user(
        self, user_id: int, page: int = 1, page_size: int = 10, only_open: bool = True
    ) -> Page[Procurement]:
        """Procurements the given purchaser participates in."""
        base = (
            select(Procurement)
            .join(
                ProcurementParticipant,
                ProcurementParticipant.procurement_id == Procurement.id,
            )
            .where(ProcurementParticipant.user_id == user_id)
        )
        if only_open:
            base = base.where(Procurement.status == ProcurementStatus.OPEN)
        else:
            base = base.where(
                Procurement.status.in_(
                    [
                        ProcurementStatus.CLOSED,
                        ProcurementStatus.COMPLETED,
                        ProcurementStatus.CANCELLED,
                    ]
                )
            )
        total = await self._count(base)
        page = normalize_page(page, page_size, total)
        stmt = (
            base.order_by(Procurement.deadline.asc(), Procurement.id.desc())
            .offset(offset_for(page, page_size))
            .limit(page_size)
        )
        return Page(
            items=list((await self.session.execute(stmt)).scalars().all()),
            total=total,
            page=page,
            page_size=page_size,
        )

    async def is_participant(self, procurement_id: int, user_id: int) -> bool:
        stmt = select(func.count(ProcurementParticipant.id)).where(
            ProcurementParticipant.procurement_id == procurement_id,
            ProcurementParticipant.user_id == user_id,
        )
        return bool((await self.session.execute(stmt)).scalar_one())

    async def list_participants(
        self, procurement_id: int, page: int = 1, page_size: int = 10
    ) -> Page[User]:
        base = (
            select(User)
            .join(ProcurementParticipant, ProcurementParticipant.user_id == User.id)
            .where(ProcurementParticipant.procurement_id == procurement_id)
        )
        total = await self._count(base)
        page = normalize_page(page, page_size, total)
        stmt = (
            base.order_by(User.full_name.asc(), User.id.asc())
            .offset(offset_for(page, page_size))
            .limit(page_size)
        )
        return Page(
            items=list((await self.session.execute(stmt)).scalars().all()),
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_participant_user_ids(self, procurement_id: int) -> list[int]:
        stmt = select(ProcurementParticipant.user_id).where(
            ProcurementParticipant.procurement_id == procurement_id
        )
        return [int(row) for row in (await self.session.execute(stmt)).scalars().all()]

    async def list_non_responders(self, procurement_id: int) -> list[User]:
        """Participants without a submitted request."""
        responded = select(PurchaseRequest.purchaser_id).where(
            PurchaseRequest.procurement_id == procurement_id,
            PurchaseRequest.status.in_(list(SUBMITTED_STATUSES)),
        )
        stmt = (
            select(User)
            .join(ProcurementParticipant, ProcurementParticipant.user_id == User.id)
            .where(
                ProcurementParticipant.procurement_id == procurement_id,
                User.id.notin_(responded),
                User.is_active.is_(True),
                User.revoked_at.is_(None),
            )
            .order_by(User.full_name.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_participants(self, procurement_id: int) -> int:
        stmt = select(func.count(ProcurementParticipant.id)).where(
            ProcurementParticipant.procurement_id == procurement_id
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def stats(self, procurement_id: int) -> ProcurementStats:
        participants = await self.count_participants(procurement_id)

        responded_stmt = select(func.count(func.distinct(PurchaseRequest.purchaser_id))).where(
            PurchaseRequest.procurement_id == procurement_id,
            PurchaseRequest.status.in_(list(SUBMITTED_STATUSES)),
        )
        responded = int((await self.session.execute(responded_stmt)).scalar_one())

        items_stmt = (
            select(func.count(PurchaseRequestItem.id))
            .join(
                PurchaseRequest,
                PurchaseRequest.id == PurchaseRequestItem.purchase_request_id,
            )
            .where(
                PurchaseRequest.procurement_id == procurement_id,
                PurchaseRequest.status.in_(list(SUBMITTED_STATUSES)),
            )
        )
        total_items = int((await self.session.execute(items_stmt)).scalar_one())
        return ProcurementStats(
            participants=participants, responded=responded, total_items=total_items
        )

    async def stats_for_many(self, procurement_ids: Sequence[int]) -> dict[int, ProcurementStats]:
        """Batched statistics so list views never issue N+1 queries."""
        if not procurement_ids:
            return {}
        ids = list(procurement_ids)

        participants_stmt = (
            select(
                ProcurementParticipant.procurement_id,
                func.count(ProcurementParticipant.id),
            )
            .where(ProcurementParticipant.procurement_id.in_(ids))
            .group_by(ProcurementParticipant.procurement_id)
        )
        participants = {
            int(pid): int(count)
            for pid, count in (await self.session.execute(participants_stmt)).all()
        }

        responded_stmt = (
            select(
                PurchaseRequest.procurement_id,
                func.count(func.distinct(PurchaseRequest.purchaser_id)),
            )
            .where(
                PurchaseRequest.procurement_id.in_(ids),
                PurchaseRequest.status.in_(list(SUBMITTED_STATUSES)),
            )
            .group_by(PurchaseRequest.procurement_id)
        )
        responded = {
            int(pid): int(count)
            for pid, count in (await self.session.execute(responded_stmt)).all()
        }

        items_stmt = (
            select(PurchaseRequest.procurement_id, func.count(PurchaseRequestItem.id))
            .join(
                PurchaseRequestItem,
                PurchaseRequestItem.purchase_request_id == PurchaseRequest.id,
            )
            .where(
                PurchaseRequest.procurement_id.in_(ids),
                PurchaseRequest.status.in_(list(SUBMITTED_STATUSES)),
            )
            .group_by(PurchaseRequest.procurement_id)
        )
        items = {
            int(pid): int(count) for pid, count in (await self.session.execute(items_stmt)).all()
        }

        return {
            pid: ProcurementStats(
                participants=participants.get(pid, 0),
                responded=responded.get(pid, 0),
                total_items=items.get(pid, 0),
            )
            for pid in ids
        }

    async def count_by_status(self, status: ProcurementStatus) -> int:
        stmt = select(func.count(Procurement.id)).where(Procurement.status == status)
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_created_since(self, since: dt.datetime) -> int:
        stmt = select(func.count(Procurement.id)).where(Procurement.created_at >= since)
        return int((await self.session.execute(stmt)).scalar_one())

    # -- writes ------------------------------------------------------------
    def add(
        self,
        *,
        procurement_number: str,
        title: str,
        description: str | None,
        deadline: dt.datetime,
        created_by: int,
        participant_mode: ParticipantSelectionMode,
        status: ProcurementStatus = ProcurementStatus.DRAFT,
    ) -> Procurement:
        procurement = Procurement(
            procurement_number=procurement_number,
            title=title,
            description=description,
            deadline=deadline,
            created_by=created_by,
            participant_mode=participant_mode,
            status=status,
        )
        self.session.add(procurement)
        return procurement

    async def set_participants(self, procurement_id: int, user_ids: Sequence[int]) -> int:
        """Idempotently attach participants; returns the number of new rows.

        ``ON CONFLICT DO NOTHING`` makes a repeated publish (double tap) a
        no-op instead of a unique-constraint crash.
        """
        unique_ids = list(dict.fromkeys(int(uid) for uid in user_ids))
        if not unique_ids:
            return 0
        dialect = self.session.get_bind().dialect.name
        insert = sqlite_insert if dialect == "sqlite" else pg_insert
        stmt = (
            insert(ProcurementParticipant)
            .values(
                [
                    {"procurement_id": procurement_id, "user_id": user_id}
                    for user_id in unique_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["procurement_id", "user_id"])
        )
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def clear_participants(self, procurement_id: int) -> None:
        stmt = select(ProcurementParticipant).where(
            ProcurementParticipant.procurement_id == procurement_id
        )
        for participant in (await self.session.execute(stmt)).scalars().all():
            await self.session.delete(participant)

    async def _count(self, stmt: Select[Any]) -> int:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        return int((await self.session.execute(count_stmt)).scalar_one())

    async def list_expired_open(self, now: dt.datetime) -> list[Procurement]:
        """Open procurements whose deadline has passed (future scheduler hook)."""
        stmt = select(Procurement).where(
            and_(Procurement.status == ProcurementStatus.OPEN, Procurement.deadline <= now)
        )
        return list((await self.session.execute(stmt)).scalars().all())
