"""User persistence."""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.enums import ClientCategory, UserRole
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

    def _clients_stmt(self, category: ClientCategory | None) -> Select[tuple[User]]:
        stmt = select(User).where(User.role == UserRole.CLIENT)
        if category is not None:
            stmt = stmt.where(User.category == category)
        return stmt

    async def list_clients(
        self, page: int = 1, page_size: int = 10, category: ClientCategory | None = None
    ) -> Page[User]:
        base = self._clients_stmt(category)
        total = await self._count(base)
        page = normalize_page(page, page_size, total)
        stmt = (
            base.order_by(User.created_at.desc(), User.id.desc())
            .offset(offset_for(page, page_size))
            .limit(page_size)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return Page(items=rows, total=total, page=page, page_size=page_size)

    async def list_all_clients(self, category: ClientCategory | None = None) -> list[User]:
        stmt = self._clients_stmt(category).order_by(User.created_at.asc(), User.id.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_broadcast_recipients(self, category: ClientCategory | None) -> list[User]:
        stmt = self._clients_stmt(category).where(User.is_active.is_(True)).order_by(User.id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_admins(self) -> list[User]:
        stmt = select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_clients_by_category(self) -> dict[ClientCategory | None, int]:
        stmt = (
            select(User.category, func.count(User.id))
            .where(User.role == UserRole.CLIENT)
            .group_by(User.category)
        )
        return {category: int(count) for category, count in await self.session.execute(stmt)}

    async def count_clients_by_source(self) -> dict[str | None, int]:
        stmt = (
            select(User.source, func.count(User.id))
            .where(User.role == UserRole.CLIENT)
            .group_by(User.source)
        )
        return {source: int(count) for source, count in await self.session.execute(stmt)}

    async def count_applications_of(self, user_id: int) -> int:
        stmt = select(func.count(Application.id)).where(Application.client_id == user_id)
        return int((await self.session.execute(stmt)).scalar_one())

    # -- writes ------------------------------------------------------------
    def add(
        self,
        *,
        telegram_id: int,
        full_name: str,
        role: UserRole = UserRole.CLIENT,
        telegram_username: str | None = None,
    ) -> User:
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            role=role,
            telegram_username=telegram_username,
            is_active=True,
        )
        self.session.add(user)
        return user

    async def _count(self, stmt: Select[tuple[User]]) -> int:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        return int((await self.session.execute(count_stmt)).scalar_one())
