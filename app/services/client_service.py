"""Client profile (self-service) and client administration (admins)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.domain.permissions import require_active, require_admin
from app.domain.text import normalize_phone, sanitize_text
from app.models.audit_log import AuditAction
from app.models.enums import ClientCategory
from app.models.user import User
from app.repositories.audit import AuditRepository
from app.repositories.base import Page
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)

MIN_NAME_LENGTH = 2
MAX_NAME_LENGTH = 255
MAX_ORGANIZATION_LENGTH = 255
MAX_SOURCE_LENGTH = 32


@dataclass(frozen=True, slots=True)
class ClientCard:
    user: User
    applications_count: int


class ClientService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.users = UserRepository(session)
        self.audit = AuditRepository(session)

    # -- self-service --------------------------------------------------------
    async def set_category(self, user: User, category: ClientCategory) -> User:
        require_active(user)
        user.category = category
        await self.session.commit()
        return user

    async def update_contacts(
        self,
        user: User,
        *,
        full_name: str | None = None,
        phone: str | None = None,
        organization: str | None = None,
    ) -> User:
        """Update only the fields that were passed (``None`` = keep)."""
        require_active(user)
        if full_name is not None:
            user.full_name = self.validate_name(full_name)
        if phone is not None:
            user.phone = self.validate_phone(phone)
        if organization is not None:
            user.organization = sanitize_text(organization, MAX_ORGANIZATION_LENGTH) or None
        self.audit.log(
            action=AuditAction.USER_PROFILE_UPDATED,
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
        )
        await self.session.commit()
        return user

    async def record_source(self, user: User, source: str) -> User:
        """Remember where a client first came from — later links don't overwrite it."""
        if user.source is None and not user.is_admin:
            user.source = sanitize_text(source, MAX_SOURCE_LENGTH) or None
            await self.session.commit()
        return user

    @staticmethod
    def validate_name(raw: str) -> str:
        name = sanitize_text(raw, MAX_NAME_LENGTH)
        if len(name) < MIN_NAME_LENGTH:
            raise ValidationError("Укажите имя — хотя бы два символа.")
        return name

    @staticmethod
    def validate_phone(raw: str) -> str:
        phone = normalize_phone(raw)
        if phone is None:
            raise ValidationError(
                "Не получилось распознать номер. Пример: <code>0555 123 456</code> "
                "или <code>+996 555 123 456</code>."
            )
        return phone

    # -- administration ------------------------------------------------------
    async def list_clients(
        self, actor: User, page: int = 1, category: ClientCategory | None = None
    ) -> Page[User]:
        require_admin(actor)
        return await self.users.list_clients(
            page=page, page_size=self.settings.page_size, category=category
        )

    async def get_card(self, actor: User, user_id: int) -> ClientCard:
        require_admin(actor)
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("Клиент не найден.")
        return ClientCard(
            user=user, applications_count=await self.users.count_applications_of(user_id)
        )

    async def set_blocked(self, actor: User, user_id: int, blocked: bool) -> User:
        require_admin(actor)
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("Клиент не найден.")
        if user.is_admin:
            raise PermissionDeniedError("Администратора нельзя заблокировать из бота.")
        user.is_active = not blocked
        self.audit.log(
            action=AuditAction.USER_BLOCKED if blocked else AuditAction.USER_UNBLOCKED,
            entity_type="user",
            entity_id=user.id,
            actor_user_id=actor.id,
        )
        await self.session.commit()
        logger.info(
            "client access changed",
            extra={
                "operation": "block" if blocked else "unblock",
                "user_id": user.id,
                "result": "ok",
            },
        )
        return user

    async def broadcast_recipients(
        self, actor: User, category: ClientCategory | None
    ) -> list[User]:
        require_admin(actor)
        return await self.users.list_broadcast_recipients(category)

    async def log_broadcast(
        self, actor: User, category: ClientCategory | None, delivered: int, total: int
    ) -> None:
        require_admin(actor)
        self.audit.log(
            action=AuditAction.BROADCAST_SENT,
            entity_type="broadcast",
            actor_user_id=actor.id,
            payload={
                "category": str(category) if category else "ALL",
                "delivered": delivered,
                "total": total,
            },
        )
        await self.session.commit()
