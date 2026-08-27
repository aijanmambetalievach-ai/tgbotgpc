"""Authentication / onboarding.

The Telegram numeric id is the identity. Usernames are cached for display only
and are refreshed opportunistically on every interaction.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.exceptions import InviteError
from app.domain.text import sanitize_text
from app.domain.timeutils import utcnow
from app.models.audit_log import AuditAction
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.audit import AuditRepository
from app.repositories.invites import InviteRepository
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)

BOOTSTRAP_NAME_PREFIX = "Сотрудник тендерного отдела #"
MAX_NAME_LENGTH = 255


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.users = UserRepository(session)
        self.invites = InviteRepository(session)
        self.audit = AuditRepository(session)

    async def resolve_user(
        self,
        telegram_id: int,
        telegram_username: str | None = None,
        telegram_full_name: str | None = None,
    ) -> User | None:
        """Return the stored user for a Telegram id, refreshing cached profile data.

        Returns ``None`` for unknown Telegram accounts — the caller shows the
        "no access" message. Blocked/revoked users are still returned so the
        caller can explain *why* access is denied.
        """
        user = await self.users.get_by_telegram_id(telegram_id)
        if user is None:
            return None

        changed = False
        username = sanitize_text(telegram_username, 64) or None
        if username != user.telegram_username:
            user.telegram_username = username
            changed = True

        if telegram_full_name and user.full_name.startswith(BOOTSTRAP_NAME_PREFIX):
            user.full_name = sanitize_text(telegram_full_name, MAX_NAME_LENGTH)
            changed = True

        if changed:
            await self.session.commit()
        return user

    async def bootstrap_employees(self) -> list[User]:
        """Seed the configured Telegram ids as tender employees (idempotent)."""
        created: list[User] = []
        for telegram_id in self.settings.bootstrap_admin_ids:
            user = await self.users.get_by_telegram_id(telegram_id)
            if user is None:
                user = self.users.add(
                    telegram_id=telegram_id,
                    full_name=f"{BOOTSTRAP_NAME_PREFIX}{telegram_id}",
                    role=UserRole.TENDER_EMPLOYEE,
                )
                await self.session.flush()
                self.audit.log(
                    action=AuditAction.USER_BOOTSTRAPPED,
                    entity_type="user",
                    entity_id=user.id,
                    payload={"telegram_id": telegram_id},
                )
                created.append(user)
            elif not user.is_employee or not user.can_use_bot:
                user.role = UserRole.TENDER_EMPLOYEE
                user.is_active = True
                user.revoked_at = None
                self.audit.log(
                    action=AuditAction.USER_BOOTSTRAPPED,
                    entity_type="user",
                    entity_id=user.id,
                    payload={"telegram_id": telegram_id, "restored": True},
                )
        try:
            await self.session.commit()
        except IntegrityError:  # pragma: no cover - concurrent bootstrap
            await self.session.rollback()
            logger.warning("bootstrap race detected", extra={"operation": "bootstrap"})
        return created

    async def accept_invite(
        self,
        code: str,
        telegram_id: int,
        telegram_username: str | None = None,
        telegram_full_name: str | None = None,
    ) -> User:
        """Consume a one-time invite code and bind it to a Telegram account.

        The invite row is locked for the whole transaction, so a leaked link
        cannot onboard two accounts even under a race.
        """
        code = sanitize_text(code, 64)
        if not code:
            raise InviteError()

        now = utcnow()
        invite = await self.invites.get_by_code_for_update(code)
        if invite is None or not invite.is_usable(now):
            raise InviteError()

        existing = await self.users.get_by_telegram_id(telegram_id)
        if existing is not None:
            # Already onboarded: burn the invite, restore access if it was
            # blocked, but never silently change an existing user's role.
            invite.used_at = now
            invite.used_by_user_id = existing.id
            await self.session.commit()
            return existing

        full_name = invite.full_name or sanitize_text(telegram_full_name or "", MAX_NAME_LENGTH)
        user = self.users.add(
            telegram_id=telegram_id,
            full_name=full_name or f"Пользователь {telegram_id}",
            role=invite.role,
            telegram_username=sanitize_text(telegram_username or "", 64) or None,
            created_by=invite.created_by,
        )
        await self.session.flush()

        invite.used_at = now
        invite.used_by_user_id = user.id
        self.audit.log(
            action=AuditAction.USER_JOINED,
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
            payload={"invite_id": invite.id, "role": str(invite.role)},
        )
        try:
            await self.session.commit()
        except IntegrityError:  # pragma: no cover - concurrent /start
            await self.session.rollback()
            existing = await self.users.get_by_telegram_id(telegram_id)
            if existing is None:
                raise InviteError() from None
            return existing

        logger.info(
            "invite accepted",
            extra={
                "operation": "accept_invite",
                "telegram_user_id": telegram_id,
                "user_id": user.id,
                "result": "ok",
            },
        )
        return user
