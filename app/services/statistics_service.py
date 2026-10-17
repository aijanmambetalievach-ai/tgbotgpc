"""Dashboard numbers for administrators."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.permissions import require_admin
from app.models.enums import ClientCategory
from app.models.user import User
from app.repositories.content import LessonRepository
from app.repositories.users import UserRepository
from app.services.application_service import ApplicationService, ApplicationStats


@dataclass(frozen=True, slots=True)
class Dashboard:
    clients_by_category: dict[ClientCategory | None, int]
    clients_by_source: dict[str | None, int]
    applications: ApplicationStats
    lessons_completed: int

    @property
    def clients_total(self) -> int:
        return sum(self.clients_by_category.values())


class StatisticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def dashboard(self, actor: User) -> Dashboard:
        require_admin(actor)
        users = UserRepository(self.session)
        return Dashboard(
            clients_by_category=await users.count_clients_by_category(),
            clients_by_source=await users.count_clients_by_source(),
            applications=await ApplicationService(self.session).stats(actor),
            lessons_completed=await LessonRepository(self.session).count_completions(),
        )
