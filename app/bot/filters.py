"""Reusable aiogram filters."""

from __future__ import annotations

from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.models.user import User


class AdminFilter(BaseFilter):
    """Route updates by the *stored* role.

    This is UI routing only — every service call re-checks permissions, so a
    forged callback cannot bypass authorization by reaching another handler.
    """

    async def __call__(self, event: TelegramObject, **data: Any) -> bool:
        user: User | None = data.get("user")
        return user is not None and user.can_use_bot and user.is_admin


IsAdmin = AdminFilter()
