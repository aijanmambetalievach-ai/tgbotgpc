"""Registration and access gate.

The bot is public: an unknown Telegram account is registered as a client on
its first update. Blocked users get a polite refusal and their update is
dropped before any handler runs.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from aiogram.types import User as TgUser

from app.bot import texts
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return None

        user = await AuthService(data["session"]).resolve_or_register(
            telegram_id=tg_user.id,
            telegram_username=tg_user.username,
            telegram_full_name=tg_user.full_name,
        )
        data["user"] = user

        if not user.can_use_bot:
            await _deny(_inner_event(event), texts.ACCESS_BLOCKED)
            logger.info(
                "access denied for blocked user",
                extra={
                    "operation": "auth",
                    "telegram_user_id": tg_user.id,
                    "user_id": user.id,
                    "result": "blocked",
                },
            )
            return None

        return await handler(event, data)


def _inner_event(event: TelegramObject) -> TelegramObject:
    if isinstance(event, Update):
        return event.message or event.callback_query or event
    return event


async def _deny(event: TelegramObject, text: str) -> None:
    if isinstance(event, Message):
        await event.answer(text)
    elif isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)
