"""Many-to-many link between a procurement and the purchasers invited to it."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IntPKMixin

if TYPE_CHECKING:
    from app.models.procurement import Procurement
    from app.models.user import User


class ProcurementParticipant(IntPKMixin, Base):
    """Frozen participation record.

    Participants are materialised at publication time even when the employee
    chose "all active purchasers", so that adding a purchaser later never
    rewrites the historical composition of an existing procurement.
    """

    __tablename__ = "procurement_participants"

    procurement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("procurements.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    procurement: Mapped[Procurement] = relationship(back_populates="participants", lazy="raise")
    user: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("procurement_id", "user_id", name="uq_procurement_participants_pair"),
        Index("ix_procurement_participants_procurement_id", "procurement_id"),
        Index("ix_procurement_participants_user_id", "user_id"),
    )
