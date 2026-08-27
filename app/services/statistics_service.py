"""Aggregated numbers for the employee dashboard."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.permissions import Permission, require_permission
from app.domain.timeutils import to_local, utcnow
from app.models.enums import ProcurementStatus, PurchaseRequestStatus
from app.models.user import User
from app.repositories.procurements import ProcurementRepository, ProcurementStats
from app.repositories.purchase_requests import PurchaseRequestRepository
from app.repositories.users import UserRepository


@dataclass(frozen=True, slots=True)
class DashboardStats:
    open_procurements: int
    procurements_this_month: int
    active_purchasers: int
    requests_today: int
    requests_this_week: int
    new_requests: int
    in_progress_requests: int
    completed_requests: int


class StatisticsService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.users = UserRepository(session)
        self.procurements = ProcurementRepository(session)
        self.requests = PurchaseRequestRepository(session)

    async def dashboard(self, actor: User) -> DashboardStats:
        require_permission(actor, Permission.STATISTICS_VIEW)

        now = utcnow()
        tz = self.settings.timezone
        local_now = to_local(now, tz)
        start_of_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_week = start_of_day - dt.timedelta(days=start_of_day.weekday())
        start_of_month = start_of_day.replace(day=1)

        return DashboardStats(
            open_procurements=await self.procurements.count_by_status(ProcurementStatus.OPEN),
            procurements_this_month=await self.procurements.count_created_since(
                start_of_month.astimezone(dt.UTC)
            ),
            active_purchasers=await self.users.count_active_purchasers(),
            requests_today=await self.requests.count_submitted_since(
                start_of_day.astimezone(dt.UTC)
            ),
            requests_this_week=await self.requests.count_submitted_since(
                start_of_week.astimezone(dt.UTC)
            ),
            new_requests=await self.requests.count_by_status(PurchaseRequestStatus.SUBMITTED),
            in_progress_requests=await self.requests.count_by_status(
                PurchaseRequestStatus.IN_PROGRESS
            ),
            completed_requests=await self.requests.count_by_status(
                PurchaseRequestStatus.COMPLETED
            ),
        )

    async def procurement_stats(self, actor: User, procurement_id: int) -> ProcurementStats:
        require_permission(actor, Permission.PROCUREMENT_VIEW_ALL)
        return await self.procurements.stats(procurement_id)
