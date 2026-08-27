"""A single line item of a purchase request."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IntPKMixin

if TYPE_CHECKING:
    from app.models.purchase_request import PurchaseRequest

# 15 integer digits + 3 decimals: enough for any realistic quantity while
# keeping exact decimal semantics (never float).
QUANTITY_PRECISION = 18
QUANTITY_SCALE = 3


class PurchaseRequestItem(IntPKMixin, Base):
    """Item name + exact decimal quantity + normalised unit."""

    __tablename__ = "purchase_request_items"

    purchase_request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE, asdecimal=True), nullable=False
    )
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    purchase_request: Mapped[PurchaseRequest] = relationship(
        back_populates="items", lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint(
            "purchase_request_id", "position", name="uq_purchase_request_items_position"
        ),
        Index("ix_purchase_request_items_purchase_request_id", "purchase_request_id"),
        Index("ix_purchase_request_items_normalized_name_unit", "normalized_name", "unit"),
    )
