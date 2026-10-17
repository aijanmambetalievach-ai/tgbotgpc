"""Small helpers shared by handlers (handlers stay thin)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from app.bot import texts
from app.bot.keyboards.common import admin_menu, client_menu
from app.config.settings import get_settings
from app.domain.text import escape_html, html_to_plain
from app.models.enums import CATEGORY_SERVICES, ApplicationType, MediaType
from app.models.user import User
from app.services.application_service import Attachment

logger = logging.getLogger(__name__)

#: Longest escape produced by ``escape_html`` (``&amp;``).
MAX_ENTITY_LENGTH = 5


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
    """Never exceed the Telegram message limit.

    Cutting HTML could leave an unclosed tag (Telegram would reject the whole
    message), so an oversized text is flattened to plain text first.
    """
    limit = get_settings().max_message_length
    if len(text) <= limit:
        return text
    cut = escape_html(html_to_plain(text))[: limit - 40]
    # Do not leave half of an escape sequence such as "&am" at the end.
    amp = cut.rfind("&", len(cut) - MAX_ENTITY_LENGTH)
    if amp != -1 and ";" not in cut[amp:]:
        cut = cut[:amp]
    return cut.rstrip() + "\n\n<i>…сообщение сокращено</i>"


async def answer_html(message: Message, text: str, reply_markup: Any = None) -> Message:
    return await message.answer(
        truncate_for_telegram(text), reply_markup=reply_markup, parse_mode="HTML"
    )


async def notify_stale(callback: CallbackQuery) -> None:
    await callback.answer(texts.STALE_CALLBACK, show_alert=True)


def extract_attachment(message: Message) -> Attachment | None:
    """The photo / video / document of a message, if any (largest photo size)."""
    if message.photo:
        return Attachment(MediaType.PHOTO, message.photo[-1].file_id)
    if message.video:
        return Attachment(MediaType.VIDEO, message.video.file_id)
    if message.document:
        return Attachment(MediaType.DOCUMENT, message.document.file_id)
    return None


def plain_text(message: Message) -> str:
    """What a client typed (text or media caption), as plain text."""
    return message.text or message.caption or ""


def rich_text(message: Message) -> str:
    """What an admin typed, as Telegram HTML — formatting is preserved."""
    if not (message.text or message.caption):
        return ""
    return message.html_text


def chat_id_of(callback: CallbackQuery) -> int:
    return callback.from_user.id


async def send_html(bot: Bot, chat_id: int, text: str, reply_markup: Any = None) -> Message:
    return await bot.send_message(
        chat_id, truncate_for_telegram(text), reply_markup=reply_markup, parse_mode="HTML"
    )


async def send_media(
    bot: Bot,
    chat_id: int,
    media_type: MediaType,
    file_id: str,
    caption: str | None = None,
    reply_markup: Any = None,
) -> Message:
    senders: dict[MediaType, Callable[..., Awaitable[Message]]] = {
        MediaType.PHOTO: bot.send_photo,
        MediaType.VIDEO: bot.send_video,
        MediaType.DOCUMENT: bot.send_document,
    }
    return await senders[media_type](
        chat_id, file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML"
    )


def menu_for(user: User, *, client_side: bool = False) -> ReplyKeyboardMarkup:
    """Admins get the admin keyboard unless they are trying the client side."""
    if user.is_admin and not client_side:
        return admin_menu()
    # Admins previewing the client side see every service.
    offered = CATEGORY_SERVICES[user.category]
    return client_menu(show_support=user.is_admin or ApplicationType.SUPPORT in offered)
