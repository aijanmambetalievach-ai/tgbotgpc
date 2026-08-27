"""User model — the single source of truth for authorization."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IntPKMixin, TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.purchase_request import PurchaseRequest


class User(IntPKMixin, TimestampMixin, Base):
    """A person allowed to use the bot.

    The Telegram numeric user id is the stable identity. ``telegram_username``
    is stored for display only — usernames can be changed or released at any
    time and must never be used for authorization.
    """

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, native_enum=False, length=32, name="user_role"),
        nullable=False,
        default=UserRole.PURCHASER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    purchase_requests: Mapped[list[PurchaseRequest]] = relationship(
        back_populates="purchaser",
        foreign_keys="PurchaseRequest.purchaser_id",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_users_role_is_active", "role", "is_active"),
        Index("ix_users_created_by", "created_by"),
    )

    # --- Convenience -------------------------------------------------------
    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def can_use_bot(self) -> bool:
        return self.is_active and self.revoked_at is None

    @property
    def is_employee(self) -> bool:
        return self.role in (UserRole.TENDER_EMPLOYEE, UserRole.ADMIN)

    @property
    def display_name(self) -> str:
        if self.telegram_username:
            return f"{self.full_name} (@{self.telegram_username})"
        return self.full_name
