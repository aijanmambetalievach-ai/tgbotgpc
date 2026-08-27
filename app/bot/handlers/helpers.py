"""Small helpers shared by handlers (handlers stay thin)."""

from __future__ import annotations

import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.bot import texts
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


async def edit_or_send(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit the message behind a callback; fall back to sending a new one.

    Telegram raises ``message is not modified`` when a user taps the same
    button twice — that is an expected idempotent no-op, not an error.
    """
    text = truncate_for_telegram(text)
    message = callback.message
    if message is None or not isinstance(message, Message):
        if callback.from_user is not None and callback.bot is not None:
            await callback.bot.send_message(
                callback.from_user.id, text, reply_markup=reply_markup, parse_mode="HTML"
            )
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        if "message can't be edited" in str(exc) or "message to edit not found" in str(exc):
            await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
            return
        raise


def truncate_for_telegram(text: str) -> str:
    """Never exceed the Telegram message limit."""
    limit = get_settings().max_message_length
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n\n<i>…сообщение сокращено</i>"


async def answer_html(
    message: Message, text: str, reply_markup: Any = None
) -> Message:
    return await message.answer(
        truncate_for_telegram(text), reply_markup=reply_markup, parse_mode="HTML"
    )


async def notify_stale(callback: CallbackQuery) -> None:
    await callback.answer(texts.STALE_CALLBACK, show_alert=True)
