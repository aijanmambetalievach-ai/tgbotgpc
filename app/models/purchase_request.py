"""Purchase request submitted by a purchaser against a procurement."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IntPKMixin, TimestampMixin
from app.models.enums import PurchaseRequestStatus

if TYPE_CHECKING:
    from app.models.procurement import Procurement
    from app.models.purchase_request_item import PurchaseRequestItem
    from app.models.user import User


class PurchaseRequest(IntPKMixin, TimestampMixin, Base):
    """A purchaser's item list.

    Two kinds of request share this table:

    * **against a procurement** — ``procurement_id`` is set. A purchaser has at
      most one such request per procurement; the unique constraint on
      ``(procurement_id, purchaser_id)`` enforces that in the database, which
      also makes double-tap submissions harmless.
    * **self-initiated** — ``procurement_id`` is ``NULL`` and ``subject``
      describes what the purchaser needs. The purchaser starts these on their
      own and sends them to a tender employee for approval. PostgreSQL treats
      ``NULL``s as distinct in a unique constraint, so the same constraint
      allows any number of self-initiated requests per purchaser.
    """

    __tablename__ = "purchase_requests"

    request_number: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    procurement_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("procurements.id", ondelete="CASCADE"), nullable=True
    )
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    purchaser_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[PurchaseRequestStatus] = mapped_column(
        SAEnum(PurchaseRequestStatus, native_enum=False, length=32, name="purchase_request_status"),
        nullable=False,
        default=PurchaseRequestStatus.DRAFT,
        index=True,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ``selectin`` (not ``joined``) on purpose: joined eager loading emits an
    # OUTER JOIN, which PostgreSQL refuses to combine with ``SELECT ... FOR
    # UPDATE`` — and row locking is how duplicate submissions are prevented.
    procurement: Mapped[Procurement | None] = relationship(
        back_populates="purchase_requests", lazy="selectin"
    )
    purchaser: Mapped[User] = relationship(
        back_populates="purchase_requests", foreign_keys=[purchaser_id], lazy="selectin"
    )
    items: Mapped[list[PurchaseRequestItem]] = relationship(
        back_populates="purchase_request",
        cascade="all, delete-orphan",
        order_by="PurchaseRequestItem.position",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("procurement_id", "purchaser_id", name="uq_purchase_requests_pair"),
        CheckConstraint(
            "procurement_id IS NOT NULL OR subject IS NOT NULL",
            name="procurement_or_subject",
        ),
        Index("ix_purchase_requests_procurement_id", "procurement_id"),
        Index("ix_purchase_requests_purchaser_id", "purchaser_id"),
        Index("ix_purchase_requests_submitted_at", "submitted_at"),
        Index("ix_purchase_requests_procurement_status", "procurement_id", "status"),
    )

    @property
    def is_self_initiated(self) -> bool:
        """Started by the purchaser, not tied to any procurement."""
        return self.procurement_id is None

    @property
    def title(self) -> str:
        """What the request is about, whichever kind it is."""
        if self.subject:
            return self.subject
        return self.procurement.title if self.procurement is not None else "Заявка"

    @property
    def is_draft(self) -> bool:
        return self.status is PurchaseRequestStatus.DRAFT

    @property
    def is_submitted(self) -> bool:
        return self.status is not PurchaseRequestStatus.DRAFT

    @property
    def public_number(self) -> str:
        return self.request_number or f"DRAFT-{self.id}"
