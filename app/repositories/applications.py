"""Application and conversation persistence."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application, ApplicationMessage
from app.models.enums import (
    OPEN_APPLICATION_STATUSES,
    ApplicationStatus,
    ApplicationType,
)
from app.models.user import User
from app.repositories.base import Page, normalize_page, offset_for


@dataclass(frozen=True, slots=True)
class ApplicationRow:
    """An application together with its client, for list rendering."""

    application: Application
    client: User


class ApplicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, application_id: int) -> Application | None:
        return await self.session.get(Application, application_id)

    async def get_for_update(self, application_id: int) -> Application | None:
        stmt = (
            select(Application)
            .where(Application.id == application_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_page(
        self,
        *,
        statuses: Sequence[ApplicationStatus] | None = None,
        client_id: int | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Page[ApplicationRow]:
        base: Select[tuple[Application, User]] = select(Application, User).join(
            User, User.id == Application.client_id
        )
        if statuses is not None:
            base = base.where(Application.status.in_(list(statuses)))
        if client_id is not None:
            base = base.where(Application.client_id == client_id)

        total_stmt = select(func.count()).select_from(
            base.with_only_columns(Application.id).subquery()
        )
        total = int((await self.session.execute(total_stmt)).scalar_one())
        page = normalize_page(page, page_size, total)
        stmt = (
            base.order_by(Application.created_at.desc(), Application.id.desc())
            .offset(offset_for(page, page_size))
            .limit(page_size)
        )
        rows = [
            ApplicationRow(application=application, client=client)
            for application, client in await self.session.execute(stmt)
        ]
        return Page(items=rows, total=total, page=page, page_size=page_size)

    async def list_for_export(self, since: dt.datetime | None = None) -> list[ApplicationRow]:
        stmt = select(Application, User).join(User, User.id == Application.client_id)
        if since is not None:
            stmt = stmt.where(Application.created_at >= since)
        stmt = stmt.order_by(Application.created_at.asc(), Application.id.asc())
        return [
            ApplicationRow(application=application, client=client)
            for application, client in await self.session.execute(stmt)
        ]

    async def find_open_course_application(
        self, client_id: int, course_id: int
    ) -> Application | None:
        stmt = select(Application).where(
            Application.client_id == client_id,
            Application.course_id == course_id,
            Application.type == ApplicationType.COURSE,
            Application.status.in_(list(OPEN_APPLICATION_STATUSES)),
        )
        return (await self.session.execute(stmt.limit(1))).scalar_one_or_none()

    async def count_open_of(self, client_id: int) -> int:
        stmt = select(func.count(Application.id)).where(
            Application.client_id == client_id,
            Application.status.in_(list(OPEN_APPLICATION_STATUSES)),
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_by_status(self) -> dict[ApplicationStatus, int]:
        stmt = select(Application.status, func.count(Application.id)).group_by(Application.status)
        return {status: int(count) for status, count in await self.session.execute(stmt)}

    async def count_by_type_since(self, since: dt.datetime) -> dict[ApplicationType, int]:
        stmt = (
            select(Application.type, func.count(Application.id))
            .where(Application.created_at >= since)
            .group_by(Application.type)
        )
        return {kind: int(count) for kind, count in await self.session.execute(stmt)}

    def add(self, application: Application) -> Application:
        self.session.add(application)
        return application

    # -- conversation -------------------------------------------------------
    def add_message(self, message: ApplicationMessage) -> ApplicationMessage:
        self.session.add(message)
        return message

    async def messages(self, application_id: int, limit: int = 50) -> list[ApplicationMessage]:
        """The latest ``limit`` messages, oldest first."""
        stmt = (
            select(ApplicationMessage)
            .where(ApplicationMessage.application_id == application_id)
            .order_by(ApplicationMessage.created_at.desc(), ApplicationMessage.id.desc())
            .limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows
