"""User persistence."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.purchase_request import PurchaseRequest
from app.models.user import User
from app.repositories.base import Page, normalize_page, offset_for


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reads -------------------------------------------------------------
    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_for_update(self, user_id: int) -> User | None:
        stmt = select(User).where(User.id == user_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def _purchaser_stmt(self, include_revoked: bool) -> Select[tuple[User]]:
        stmt = select(User).where(User.role == UserRole.PURCHASER)
        if not include_revoked:
            stmt = stmt.where(User.revoked_at.is_(None))
        return stmt

    async def list_purchasers(
        self, page: int = 1, page_size: int = 10, include_revoked: bool = False
    ) -> Page[User]:
        base = self._purchaser_stmt(include_revoked)
        total = await self._count(base)
        page = normalize_page(page, page_size, total)
        stmt = (
            base.order_by(User.full_name.asc(), User.id.asc())
            .offset(offset_for(page, page_size))
            .limit(page_size)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return Page(items=rows, total=total, page=page, page_size=page_size)

    async def list_active_purchasers(self) -> list[User]:
        stmt = (
            select(User)
            .where(
                User.role == UserRole.PURCHASER,
                User.is_active.is_(True),
                User.revoked_at.is_(None),
            )
            .order_by(User.full_name.asc(), User.id.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_by_ids(self, user_ids: Sequence[int]) -> list[User]:
        if not user_ids:
            return []
        stmt = select(User).where(User.id.in_(list(user_ids)))
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_employees(self) -> list[User]:
        stmt = select(User).where(
            User.role.in_([UserRole.TENDER_EMPLOYEE, UserRole.ADMIN]),
            User.is_active.is_(True),
            User.revoked_at.is_(None),
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_active_purchasers(self) -> int:
        stmt = select(func.count(User.id)).where(
            User.role == UserRole.PURCHASER,
            User.is_active.is_(True),
            User.revoked_at.is_(None),
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_requests_of(self, user_id: int) -> int:
        stmt = select(func.count(PurchaseRequest.id)).where(
            PurchaseRequest.purchaser_id == user_id
        )
        return int((await self.session.execute(stmt)).scalar_one())

    # -- writes ------------------------------------------------------------
    def add(
        self,
        *,
        telegram_id: int,
        full_name: str,
        role: UserRole,
        telegram_username: str | None = None,
        created_by: int | None = None,
    ) -> User:
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            role=role,
            telegram_username=telegram_username,
            created_by=created_by,
            is_active=True,
        )
        self.session.add(user)
        return user

    async def touch_profile(
        self, user: User, telegram_username: str | None, full_name: str | None
    ) -> bool:
        """Refresh cached Telegram profile fields. Returns ``True`` when changed."""
        changed = False
        if telegram_username != user.telegram_username:
            user.telegram_username = telegram_username
            changed = True
        if full_name and full_name != user.full_name and not user.full_name.strip():
            user.full_name = full_name
            changed = True
        return changed

    async def _count(self, stmt: Select[tuple[User]]) -> int:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        return int((await self.session.execute(count_stmt)).scalar_one())

    @staticmethod
    def block(user: User) -> None:
        user.is_active = False

    @staticmethod
    def unblock(user: User) -> None:
        user.is_active = True

    @staticmethod
    def revoke(user: User, now: dt.datetime) -> None:
        user.is_active = False
        user.revoked_at = now
