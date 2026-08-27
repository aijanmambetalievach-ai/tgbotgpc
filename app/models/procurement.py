"""Procurement ("Закупка") aggregate root."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IntPKMixin, TimestampMixin
from app.models.enums import ParticipantSelectionMode, ProcurementStatus

if TYPE_CHECKING:
    from app.models.procurement_participant import ProcurementParticipant
    from app.models.purchase_request import PurchaseRequest


class Procurement(IntPKMixin, TimestampMixin, Base):
    """A procurement announcement that purchasers submit requests against."""

    __tablename__ = "procurements"

    procurement_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProcurementStatus] = mapped_column(
        SAEnum(ProcurementStatus, native_enum=False, length=32, name="procurement_status"),
        nullable=False,
        default=ProcurementStatus.DRAFT,
        index=True,
    )
    deadline: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    participant_mode: Mapped[ParticipantSelectionMode] = mapped_column(
        SAEnum(
            ParticipantSelectionMode,
            native_enum=False,
            length=32,
            name="participant_selection_mode",
        ),
        nullable=False,
        default=ParticipantSelectionMode.MANUAL,
    )
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    participants: Mapped[list[ProcurementParticipant]] = relationship(
        back_populates="procurement",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    purchase_requests: Mapped[list[PurchaseRequest]] = relationship(
        back_populates="procurement",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_procurements_deadline", "deadline"),
        Index("ix_procurements_created_by", "created_by"),
        Index("ix_procurements_status_deadline", "status", "deadline"),
    )

    @property
    def is_open(self) -> bool:
        return self.status is ProcurementStatus.OPEN

    def is_expired(self, now: dt.datetime) -> bool:
        return now >= self.deadline

    def accepts_submissions(self, now: dt.datetime) -> bool:
        return self.is_open and not self.is_expired(now)
