"""One-time invite codes used to onboard purchasers."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IntPKMixin, TimestampMixin
from app.models.enums import UserRole


class Invite(IntPKMixin, TimestampMixin, Base):
    """A single-use, time-limited invitation.

    The code is a high-entropy random token; it is consumed atomically on first
    use (``used_at`` set under a row lock), so a leaked link cannot onboard two
    different Telegram accounts.
    """

    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, native_enum=False, length=32, name="user_role"),
        nullable=False,
        default=UserRole.PURCHASER,
    )
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_invites_created_by", "created_by"),
        Index("ix_invites_expires_at", "expires_at"),
    )

    def is_usable(self, now: dt.datetime) -> bool:
        return self.used_at is None and self.revoked_at is None and now < self.expires_at
