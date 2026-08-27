"""Lightweight anti-spam.

An in-memory sliding window per Telegram user. Deliberately not Redis-backed:
the bot runs as a single process, and the goal is protecting the database from
accidental button mashing, not defeating a determined attacker.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.bot import texts
from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

MAX_TRACKED_USERS = 10_000


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self.limit = settings.rate_limit_messages
        self.window = float(settings.rate_limit_window_seconds)
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        now = time.monotonic()
        hits = self._hits[tg_user.id]
        while hits and now - hits[0] > self.window:
            hits.popleft()

        if len(hits) >= self.limit:
            await self._warn(event)
            logger.info(
                "rate limited",
                extra={
                    "operation": "throttle",
                    "telegram_user_id": tg_user.id,
                    "result": "blocked",
                },
            )
            return None

        hits.append(now)
        self._evict_if_needed()
        return await handler(event, data)

    def _evict_if_needed(self) -> None:
        if len(self._hits) <= MAX_TRACKED_USERS:
            return
        stale = [key for key, hits in self._hits.items() if not hits]
        for key in stale:
            del self._hits[key]

    @staticmethod
    async def _warn(event: TelegramObject) -> None:
        inner: TelegramObject = event
        if isinstance(event, Update):
            inner = event.message or event.callback_query or event
        if isinstance(inner, CallbackQuery):
            await inner.answer(texts.RATE_LIMITED, show_alert=False)
        elif isinstance(inner, Message):
            await inner.answer(texts.RATE_LIMITED)
