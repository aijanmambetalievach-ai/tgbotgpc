"""Authorization gate.

The bot is closed: unknown Telegram accounts get a polite refusal and their
update is dropped before any handler runs. The only exception is ``/start``,
which must reach the handler so an invite code can be redeemed.
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

START_PREFIX = "/start"


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

        session = data["session"]
        auth = AuthService(session)
        user = await auth.resolve_user(
            telegram_id=tg_user.id,
            telegram_username=tg_user.username,
            telegram_full_name=tg_user.full_name,
        )
        data["user"] = user

        inner = _inner_event(event)
        if user is None:
            if _is_start(inner):
                return await handler(event, data)
            await _deny(inner, texts.NO_ACCESS)
            logger.info(
                "access denied for unknown user",
                extra={
                    "operation": "auth",
                    "telegram_user_id": tg_user.id,
                    "result": "unknown",
                },
            )
            return None

        if not user.can_use_bot:
            await _deny(inner, texts.ACCESS_BLOCKED)
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


def _is_start(event: TelegramObject) -> bool:
    return isinstance(event, Message) and bool(event.text) and (
        event.text or ""
    ).startswith(START_PREFIX)


async def _deny(event: TelegramObject, text: str) -> None:
    if isinstance(event, Message):
        await event.answer(text)
    elif isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)
