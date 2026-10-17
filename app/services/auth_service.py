"""Registration and bootstrap.

The bot is public: the first message from an unknown Telegram account
registers it as a ``CLIENT``. The Telegram numeric id is the identity;
usernames are cached for display only and refreshed on every interaction.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.text import sanitize_text
from app.models.audit_log import AuditAction
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.audit import AuditRepository
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 255
MAX_USERNAME_LENGTH = 64
BOOTSTRAP_NAME_PREFIX = "Администратор "


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.users = UserRepository(session)
        self.audit = AuditRepository(session)

    async def resolve_or_register(
        self,
        telegram_id: int,
        telegram_username: str | None = None,
        telegram_full_name: str | None = None,
    ) -> User:
        """Return the stored user for a Telegram id, registering it if new.

        Blocked users are returned as well, so the caller can explain why
        access is denied.
        """
        username = sanitize_text(telegram_username, MAX_USERNAME_LENGTH) or None
        user = await self.users.get_by_telegram_id(telegram_id)
        if user is not None:
            changed = username != user.telegram_username
            user.telegram_username = username
            if telegram_full_name and user.full_name.startswith(BOOTSTRAP_NAME_PREFIX):
                # A bootstrapped admin gets their real name on first contact.
                user.full_name = sanitize_text(telegram_full_name, MAX_NAME_LENGTH)
                changed = True
            if changed:
                await self.session.commit()
            return user

        full_name = sanitize_text(telegram_full_name, MAX_NAME_LENGTH) or f"Клиент {telegram_id}"
        user = self.users.add(
            telegram_id=telegram_id, full_name=full_name, telegram_username=username
        )
        try:
            await self.session.flush()
            self.audit.log(
                action=AuditAction.USER_REGISTERED,
                entity_type="user",
                entity_id=user.id,
                actor_user_id=user.id,
            )
            await self.session.commit()
        except IntegrityError:
            # Two updates from a brand-new user raced each other; the other
            # one won, so just load what it created.
            await self.session.rollback()
            existing = await self.users.get_by_telegram_id(telegram_id)
            if existing is None:  # pragma: no cover - defensive
                raise
            return existing

        logger.info(
            "client registered",
            extra={
                "operation": "register",
                "telegram_user_id": telegram_id,
                "user_id": user.id,
                "result": "ok",
            },
        )
        return user

    async def bootstrap_admins(self) -> list[User]:
        """Promote the configured Telegram ids to administrators (idempotent)."""
        changed: list[User] = []
        for telegram_id in self.settings.bootstrap_admin_ids:
            user = await self.users.get_by_telegram_id(telegram_id)
            if user is None:
                user = self.users.add(
                    telegram_id=telegram_id,
                    full_name=f"{BOOTSTRAP_NAME_PREFIX}{telegram_id}",
                    role=UserRole.ADMIN,
                )
                await self.session.flush()
            elif user.is_admin and user.is_active:
                continue
            else:
                user.role = UserRole.ADMIN
                user.is_active = True
            self.audit.log(
                action=AuditAction.USER_BOOTSTRAPPED,
                entity_type="user",
                entity_id=user.id,
                payload={"telegram_id": telegram_id},
            )
            changed.append(user)
        try:
            await self.session.commit()
        except IntegrityError:  # pragma: no cover - concurrent bootstrap
            await self.session.rollback()
            logger.warning("bootstrap race detected", extra={"operation": "bootstrap"})
        return changed
