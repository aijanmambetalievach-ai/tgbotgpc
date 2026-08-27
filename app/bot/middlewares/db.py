"""Per-update database session."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database.session import get_session_factory


class DbSessionMiddleware(BaseMiddleware):
    """Open one session per update and guarantee it is closed."""

    def __init__(self, session_factory: async_sessionmaker[Any] | None = None) -> None:
        self._factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        factory = self._factory or get_session_factory()
        async with factory() as session:
            data["session"] = session
            try:
                return await handler(event, data)
            except Exception:
                await session.rollback()
                raise
