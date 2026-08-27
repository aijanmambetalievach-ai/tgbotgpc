"""Invite persistence."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.invite import Invite


class InviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(
        self,
        *,
        code: str,
        full_name: str,
        role: UserRole,
        created_by: int,
        expires_at: dt.datetime,
    ) -> Invite:
        invite = Invite(
            code=code,
            full_name=full_name,
            role=role,
            created_by=created_by,
            expires_at=expires_at,
        )
        self.session.add(invite)
        return invite

    async def get_by_code(self, code: str) -> Invite | None:
        stmt = select(Invite).where(Invite.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_code_for_update(self, code: str) -> Invite | None:
        """Row-locked fetch so a code can only ever be consumed once."""
        stmt = select(Invite).where(Invite.code == code).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_pending(self, limit: int = 20) -> list[Invite]:
        stmt = (
            select(Invite)
            .where(Invite.used_at.is_(None), Invite.revoked_at.is_(None))
            .order_by(Invite.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
