"""Structured per-update logging."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

logger = logging.getLogger("app.bot.update")

#: Never log full message bodies — only their shape.
MAX_LOGGED_COMMAND = 32


class UpdateLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        kind, detail = _describe(event)
        started = time.perf_counter()
        try:
            result = await handler(event, data)
        except Exception as exc:
            logger.exception(
                "update failed",
                extra={
                    "operation": kind,
                    "telegram_user_id": getattr(tg_user, "id", None),
                    "result": "error",
                    "error_type": type(exc).__name__,
                },
            )
            raise
        logger.debug(
            "update handled",
            extra={
                "operation": kind,
                "telegram_user_id": getattr(tg_user, "id", None),
                "result": detail,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return result


def _describe(event: TelegramObject) -> tuple[str, str]:
    inner: TelegramObject = event
    if isinstance(event, Update):
        inner = event.message or event.callback_query or event
    if isinstance(inner, CallbackQuery):
        payload = (inner.data or "").split(":", 1)[0]
        return "callback", payload[:MAX_LOGGED_COMMAND]
    if isinstance(inner, Message):
        text = inner.text or ""
        if text.startswith("/"):
            return "command", text.split()[0][:MAX_LOGGED_COMMAND]
        return "message", f"len={len(text)}"
    return "update", type(inner).__name__
