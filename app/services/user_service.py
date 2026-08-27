"""User administration performed by tender employees."""

from __future__ import annotations

import datetime as dt
import logging
import secrets
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.exceptions import NotFoundError, ValidationError
from app.domain.permissions import Permission, require_permission
from app.domain.text import sanitize_text
from app.domain.timeutils import utcnow
from app.models.audit_log import AuditAction
from app.models.enums import UserRole
from app.models.invite import Invite
from app.models.user import User
from app.repositories.audit import AuditRepository
from app.repositories.base import Page
from app.repositories.invites import InviteRepository
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)

INVITE_CODE_BYTES = 12
MAX_FULL_NAME_LENGTH = 255
MIN_FULL_NAME_LENGTH = 2


@dataclass(frozen=True, slots=True)
class PurchaserCard:
    user: User
    requests_count: int


class UserService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.users = UserRepository(session)
        self.invites = InviteRepository(session)
        self.audit = AuditRepository(session)

    # -- queries -----------------------------------------------------------
    async def list_purchasers(
        self,
        actor: User,
        page: int = 1,
        page_size: int | None = None,
        include_revoked: bool = False,
    ) -> Page[User]:
        require_permission(actor, Permission.USER_VIEW)
        return await self.users.list_purchasers(
            page=page,
            page_size=page_size or self.settings.page_size,
            include_revoked=include_revoked,
        )

    async def list_active_purchasers(self, actor: User) -> list[User]:
        require_permission(actor, Permission.USER_VIEW)
        return await self.users.list_active_purchasers()

    async def get_card(self, actor: User, user_id: int) -> PurchaserCard:
        require_permission(actor, Permission.USER_VIEW)
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("Пользователь не найден.")
        return PurchaserCard(user=user, requests_count=await self.users.count_requests_of(user_id))

    # -- onboarding --------------------------------------------------------
    async def create_invite(
        self, actor: User, full_name: str, role: UserRole = UserRole.PURCHASER
    ) -> Invite:
        require_permission(actor, Permission.USER_MANAGE)
        clean_name = self._validate_name(full_name)
        code = secrets.token_urlsafe(INVITE_CODE_BYTES)
        expires_at = utcnow() + dt.timedelta(hours=self.settings.invite_ttl_hours)

        invite = self.invites.add(
            code=code,
            full_name=clean_name,
            role=role,
            created_by=actor.id,
            expires_at=expires_at,
        )
        await self.session.flush()
        self.audit.log(
            action=AuditAction.USER_INVITED,
            entity_type="invite",
            entity_id=invite.id,
            actor_user_id=actor.id,
            payload={"full_name": clean_name, "role": str(role)},
        )
        await self.session.commit()
        logger.info(
            "invite created",
            extra={"operation": "create_invite", "user_id": actor.id, "result": "ok"},
        )
        return invite

    async def add_purchaser_by_telegram_id(
        self, actor: User, telegram_id: int, full_name: str
    ) -> User:
        require_permission(actor, Permission.USER_MANAGE)
        clean_name = self._validate_name(full_name)
        if telegram_id <= 0:
            raise ValidationError("Telegram ID должен быть положительным числом.")

        existing = await self.users.get_by_telegram_id(telegram_id)
        if existing is not None:
            raise ValidationError(
                f"Пользователь с Telegram ID {telegram_id} уже есть в системе "
                f"({existing.full_name})."
            )

        user = self.users.add(
            telegram_id=telegram_id,
            full_name=clean_name,
            role=UserRole.PURCHASER,
            created_by=actor.id,
        )
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            raise ValidationError("Такой Telegram ID уже зарегистрирован.") from None

        self.audit.log(
            action=AuditAction.USER_CREATED,
            entity_type="user",
            entity_id=user.id,
            actor_user_id=actor.id,
            payload={"telegram_id": telegram_id, "role": str(UserRole.PURCHASER)},
        )
        await self.session.commit()
        return user

    # -- access control ----------------------------------------------------
    async def block(self, actor: User, user_id: int) -> User:
        return await self._set_access(actor, user_id, active=True, blocked=True)

    async def unblock(self, actor: User, user_id: int) -> User:
        return await self._set_access(actor, user_id, active=True, blocked=False)

    async def revoke(self, actor: User, user_id: int) -> User:
        """Soft revoke: the row and its history stay, access is withdrawn."""
        require_permission(actor, Permission.USER_MANAGE)
        target = await self._load_target(actor, user_id)
        if target.revoked_at is not None:
            return target  # idempotent

        self.users.revoke(target, utcnow())
        self.audit.log(
            action=AuditAction.USER_REVOKED,
            entity_type="user",
            entity_id=target.id,
            actor_user_id=actor.id,
            payload={"telegram_id": target.telegram_id},
        )
        await self.session.commit()
        logger.info(
            "user access revoked",
            extra={"operation": "revoke_user", "user_id": actor.id, "entity_id": target.id},
        )
        return target

    async def _set_access(
        self, actor: User, user_id: int, *, active: bool, blocked: bool
    ) -> User:
        require_permission(actor, Permission.USER_MANAGE)
        target = await self._load_target(actor, user_id)

        if target.revoked_at is not None and not blocked:
            # Unblocking a revoked user restores access explicitly.
            target.revoked_at = None

        desired_active = active and not blocked
        if target.is_active == desired_active and target.revoked_at is None:
            return target  # idempotent double tap

        target.is_active = desired_active
        self.audit.log(
            action=AuditAction.USER_BLOCKED if blocked else AuditAction.USER_UNBLOCKED,
            entity_type="user",
            entity_id=target.id,
            actor_user_id=actor.id,
            payload={"telegram_id": target.telegram_id},
        )
        await self.session.commit()
        return target

    async def _load_target(self, actor: User, user_id: int) -> User:
        target = await self.users.get_for_update(user_id)
        if target is None:
            raise NotFoundError("Пользователь не найден.")
        if target.id == actor.id:
            raise ValidationError("Нельзя изменить собственный доступ.")
        if target.is_employee and actor.role is not UserRole.ADMIN:
            raise ValidationError("Управлять доступом сотрудников может только администратор.")
        return target

    @staticmethod
    def _validate_name(full_name: str) -> str:
        clean = sanitize_text(full_name, MAX_FULL_NAME_LENGTH)
        if len(clean) < MIN_FULL_NAME_LENGTH:
            raise ValidationError("Укажите имя и фамилию (минимум 2 символа).")
        return clean
