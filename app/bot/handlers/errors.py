"""Central error handling.

Expected business errors become a short Russian message; anything unexpected is
logged with a stack trace and the user gets a neutral apology (never an
internal detail).
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import CallbackQuery, ErrorEvent, Message

from app.bot import texts
from app.domain.exceptions import DomainError

logger = logging.getLogger(__name__)

router = Router(name="errors")


@router.errors()
async def handle_error(event: ErrorEvent) -> bool:
    exception = event.exception
    update = event.update

    message: Message | None = update.message
    callback: CallbackQuery | None = update.callback_query

    if isinstance(exception, DomainError):
        logger.info(
            "domain error",
            extra={
                "operation": "handler",
                "result": "domain_error",
                "error_type": type(exception).__name__,
            },
        )
        await _respond(message, callback, exception.message)
        return True

    logger.exception(
        "unhandled error",
        exc_info=exception,
        extra={"operation": "handler", "result": "error", "error_type": type(exception).__name__},
    )
    await _respond(message, callback, texts.GENERIC_ERROR)
    return True


async def _respond(message: Message | None, callback: CallbackQuery | None, text: str) -> None:
    try:
        if callback is not None:
            await callback.answer(text[:200], show_alert=True)
        elif message is not None:
            await message.answer(text)
    except Exception:  # pragma: no cover - the user may have blocked the bot
        logger.debug("could not deliver error message to the user")
