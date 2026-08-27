"""Append-only status transition history for purchase requests."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IntPKMixin
from app.models.enums import PurchaseRequestStatus


class StatusHistory(IntPKMixin, Base):
    """One row per status change; never updated, never deleted."""

    __tablename__ = "status_history"

    purchase_request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False
    )
    old_status: Mapped[PurchaseRequestStatus | None] = mapped_column(
        SAEnum(PurchaseRequestStatus, native_enum=False, length=32, name="purchase_request_status"),
        nullable=True,
    )
    new_status: Mapped[PurchaseRequestStatus] = mapped_column(
        SAEnum(PurchaseRequestStatus, native_enum=False, length=32, name="purchase_request_status"),
        nullable=False,
    )
    changed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_status_history_purchase_request_id", "purchase_request_id"),
        Index("ix_status_history_created_at", "created_at"),
    )
