"""User model — the single source of truth for authorization."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IntPKMixin, TimestampMixin
from app.models.enums import ClientCategory, UserRole


class User(IntPKMixin, TimestampMixin, Base):
    """Anyone who has opened the bot.

    The bot is public: every new Telegram account is registered as a
    ``CLIENT`` on first contact. The Telegram numeric user id is the stable
    identity; ``telegram_username`` is cached for display only and must never
    be used for authorization.
    """

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, native_enum=False, length=32, name="user_role"),
        nullable=False,
        default=UserRole.CLIENT,
    )
    category: Mapped[ClientCategory | None] = mapped_column(
        SAEnum(ClientCategory, native_enum=False, length=32, name="client_category"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_users_role_is_active", "role", "is_active"),
        Index("ix_users_category", "category"),
    )

    # --- Convenience -------------------------------------------------------
    @property
    def can_use_bot(self) -> bool:
        return self.is_active

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    @property
    def has_contact_details(self) -> bool:
        return bool(self.full_name.strip()) and bool(self.phone)

    @property
    def display_name(self) -> str:
        if self.telegram_username:
            return f"{self.full_name} (@{self.telegram_username})"
        return self.full_name
