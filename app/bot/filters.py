"""Reusable aiogram filters."""

from __future__ import annotations

from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.models.enums import UserRole
from app.models.user import User


class RoleFilter(BaseFilter):
    """Route updates by the *stored* role.

    This is UI routing only — every service call re-checks permissions, so a
    forged callback cannot bypass authorization by reaching another handler.
    """

    def __init__(self, *roles: UserRole) -> None:
        self.roles = set(roles)

    async def __call__(self, event: TelegramObject, **data: Any) -> bool:
        user: User | None = data.get("user")
        return user is not None and user.can_use_bot and user.role in self.roles


EmployeeFilter = RoleFilter(UserRole.TENDER_EMPLOYEE, UserRole.ADMIN)
PurchaserFilter = RoleFilter(UserRole.PURCHASER)
