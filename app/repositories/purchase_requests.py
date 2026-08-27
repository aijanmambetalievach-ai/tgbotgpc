"""Purchase request persistence."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import PurchaseRequestStatus
from app.models.procurement import Procurement
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_item import PurchaseRequestItem
from app.models.status_history import StatusHistory
from app.models.user import User
from app.repositories.base import Page, normalize_page, offset_for

ACTIVE_STATUSES: tuple[PurchaseRequestStatus, ...] = (
    PurchaseRequestStatus.SUBMITTED,
    PurchaseRequestStatus.VIEWED,
    PurchaseRequestStatus.IN_PROGRESS,
)

#: Statuses whose items belong in an export / aggregate report.
#: Rejected and cancelled requests are deliberately excluded so a withdrawn
#: request never inflates the totals.
EXPORTABLE_STATUSES: tuple[PurchaseRequestStatus, ...] = (
    *ACTIVE_STATUSES,
    PurchaseRequestStatus.COMPLETED,
)


class PurchaseRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reads -------------------------------------------------------------
    async def get_by_id(self, request_id: int) -> PurchaseRequest | None:
        return await self.session.get(PurchaseRequest, request_id)

    async def get_with_items(self, request_id: int) -> PurchaseRequest | None:
        stmt = (
            select(PurchaseRequest)
            .where(PurchaseRequest.id == request_id)
            .options(selectinload(PurchaseRequest.items))
        )
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()

    async def get_for_update(self, request_id: int) -> PurchaseRequest | None:
        """Row-locked fetch — the anti-double-submit primitive."""
        stmt = (
            select(PurchaseRequest)
            .where(PurchaseRequest.id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()

    async def get_by_pair(self, procurement_id: int, purchaser_id: int) -> PurchaseRequest | None:
        stmt = select(PurchaseRequest).where(
            PurchaseRequest.procurement_id == procurement_id,
            PurchaseRequest.purchaser_id == purchaser_id,
        )
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()

    async def get_by_pair_for_update(
        self, procurement_id: int, purchaser_id: int
    ) -> PurchaseRequest | None:
        stmt = (
            select(PurchaseRequest)
            .where(
                PurchaseRequest.procurement_id == procurement_id,
                PurchaseRequest.purchaser_id == purchaser_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()

    async def get_self_initiated_draft(self, purchaser_id: int) -> PurchaseRequest | None:
        """The purchaser's open self-initiated draft, if they have one."""
        stmt = select(PurchaseRequest).where(
            PurchaseRequest.purchaser_id == purchaser_id,
            PurchaseRequest.procurement_id.is_(None),
            PurchaseRequest.status == PurchaseRequestStatus.DRAFT,
        )
        return (await self.session.execute(stmt)).unique().scalars().first()

    async def list_by_procurement(
        self,
        procurement_id: int,
        page: int = 1,
        page_size: int = 10,
        statuses: Sequence[PurchaseRequestStatus] | None = None,
    ) -> Page[PurchaseRequest]:
        base = select(PurchaseRequest).where(PurchaseRequest.procurement_id == procurement_id)
        if statuses:
            base = base.where(PurchaseRequest.status.in_(list(statuses)))
        else:
            base = base.where(PurchaseRequest.status != PurchaseRequestStatus.DRAFT)
        total = await self._count(base)
        page = normalize_page(page, page_size, total)
        stmt = (
            base.order_by(PurchaseRequest.submitted_at.desc(), PurchaseRequest.id.desc())
            .offset(offset_for(page, page_size))
            .limit(page_size)
        )
        return Page(
            items=list((await self.session.execute(stmt)).unique().scalars().all()),
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_by_purchaser(
        self,
        purchaser_id: int,
        page: int = 1,
        page_size: int = 10,
        statuses: Sequence[PurchaseRequestStatus] | None = None,
    ) -> Page[PurchaseRequest]:
        base = select(PurchaseRequest).where(PurchaseRequest.purchaser_id == purchaser_id)
        if statuses:
            base = base.where(PurchaseRequest.status.in_(list(statuses)))
        total = await self._count(base)
        page = normalize_page(page, page_size, total)
        stmt = (
            base.order_by(PurchaseRequest.created_at.desc(), PurchaseRequest.id.desc())
            .offset(offset_for(page, page_size))
            .limit(page_size)
        )
        return Page(
            items=list((await self.session.execute(stmt)).unique().scalars().all()),
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_new(self, page: int = 1, page_size: int = 10) -> Page[PurchaseRequest]:
        base = select(PurchaseRequest).where(
            PurchaseRequest.status == PurchaseRequestStatus.SUBMITTED
        )
        total = await self._count(base)
        page = normalize_page(page, page_size, total)
        stmt = (
            base.order_by(PurchaseRequest.submitted_at.desc(), PurchaseRequest.id.desc())
            .offset(offset_for(page, page_size))
            .limit(page_size)
        )
        return Page(
            items=list((await self.session.execute(stmt)).unique().scalars().all()),
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_items(self, request_id: int) -> list[PurchaseRequestItem]:
        stmt = (
            select(PurchaseRequestItem)
            .where(PurchaseRequestItem.purchase_request_id == request_id)
            .order_by(PurchaseRequestItem.position.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_items(self, request_id: int) -> int:
        stmt = select(func.count(PurchaseRequestItem.id)).where(
            PurchaseRequestItem.purchase_request_id == request_id
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def iter_procurement_items(
        self, procurement_id: int, statuses: Sequence[PurchaseRequestStatus] | None = None
    ) -> list[tuple[PurchaseRequest, PurchaseRequestItem, User]]:
        """Flat rows for the aggregate Excel export, ordered deterministically."""
        stmt = (
            select(PurchaseRequest, PurchaseRequestItem, User)
            .join(
                PurchaseRequestItem,
                PurchaseRequestItem.purchase_request_id == PurchaseRequest.id,
            )
            .join(User, User.id == PurchaseRequest.purchaser_id)
            .where(PurchaseRequest.procurement_id == procurement_id)
            .order_by(
                User.full_name.asc(),
                PurchaseRequest.id.asc(),
                PurchaseRequestItem.position.asc(),
            )
        )
        statuses = statuses or EXPORTABLE_STATUSES
        stmt = stmt.where(PurchaseRequest.status.in_(list(statuses)))
        rows = (await self.session.execute(stmt)).unique().all()
        return [(row[0], row[1], row[2]) for row in rows]

    async def aggregate_items(
        self, procurement_id: int, statuses: Sequence[PurchaseRequestStatus] | None = None
    ) -> list[tuple[str, str, Decimal, int]]:
        """``(display_name, unit, total_quantity, source_rows)`` grouped safely.

        Grouping happens on ``(normalized_name, unit)`` only: identical spelling
        and identical unit. Anything less certain stays a separate row — better
        two rows than one wrong total.
        """
        statuses = statuses or EXPORTABLE_STATUSES
        stmt = (
            select(
                PurchaseRequestItem.normalized_name,
                PurchaseRequestItem.unit,
                func.sum(PurchaseRequestItem.quantity),
                func.count(PurchaseRequestItem.id),
                func.min(PurchaseRequestItem.name),
            )
            .join(
                PurchaseRequest,
                PurchaseRequest.id == PurchaseRequestItem.purchase_request_id,
            )
            .where(
                PurchaseRequest.procurement_id == procurement_id,
                PurchaseRequest.status.in_(list(statuses)),
            )
            .group_by(PurchaseRequestItem.normalized_name, PurchaseRequestItem.unit)
            .order_by(PurchaseRequestItem.normalized_name.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            (str(display_name), str(unit), Decimal(str(total)), int(count))
            for _normalized, unit, total, count, display_name in rows
        ]

    async def count_by_status(self, status: PurchaseRequestStatus) -> int:
        stmt = select(func.count(PurchaseRequest.id)).where(PurchaseRequest.status == status)
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_submitted_since(self, since: dt.datetime) -> int:
        stmt = select(func.count(PurchaseRequest.id)).where(
            PurchaseRequest.submitted_at.is_not(None), PurchaseRequest.submitted_at >= since
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_history(self, request_id: int) -> list[StatusHistory]:
        stmt = (
            select(StatusHistory)
            .where(StatusHistory.purchase_request_id == request_id)
            .order_by(StatusHistory.created_at.asc(), StatusHistory.id.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_procurement_of(self, request_id: int) -> Procurement | None:
        stmt = (
            select(Procurement)
            .join(PurchaseRequest, PurchaseRequest.procurement_id == Procurement.id)
            .where(PurchaseRequest.id == request_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # -- writes ------------------------------------------------------------
    def add(
        self,
        *,
        procurement_id: int | None,
        purchaser_id: int,
        comment: str | None = None,
        subject: str | None = None,
    ) -> PurchaseRequest:
        request = PurchaseRequest(
            procurement_id=procurement_id,
            purchaser_id=purchaser_id,
            status=PurchaseRequestStatus.DRAFT,
            comment=comment,
            subject=subject,
        )
        self.session.add(request)
        return request

    def add_item(
        self,
        *,
        request_id: int,
        position: int,
        name: str,
        normalized_name: str,
        quantity: Decimal,
        unit: str,
        comment: str | None = None,
        source_text: str | None = None,
    ) -> PurchaseRequestItem:
        item = PurchaseRequestItem(
            purchase_request_id=request_id,
            position=position,
            name=name,
            normalized_name=normalized_name,
            quantity=quantity,
            unit=unit,
            comment=comment,
            source_text=source_text,
        )
        self.session.add(item)
        return item

    async def delete_items(self, request_id: int) -> None:
        for item in await self.list_items(request_id):
            await self.session.delete(item)
        await self.session.flush()

    def add_history(
        self,
        *,
        request_id: int,
        old_status: PurchaseRequestStatus | None,
        new_status: PurchaseRequestStatus,
        changed_by: int | None,
        comment: str | None = None,
    ) -> StatusHistory:
        history = StatusHistory(
            purchase_request_id=request_id,
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by,
            comment=comment,
        )
        self.session.add(history)
        return history

    async def _count(self, stmt: Select[Any]) -> int:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        return int((await self.session.execute(count_stmt)).scalar_one())
