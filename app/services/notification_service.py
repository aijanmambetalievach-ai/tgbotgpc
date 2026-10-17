"""Outbound Telegram notifications.

Called **after** the database transaction has committed: a failed or blocked
chat must never roll back a correctly saved business operation. Every send is
therefore individually guarded and only logged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from functools import partial
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from app.bot import texts
from app.bot.keyboards import admin as admin_kb
from app.bot.keyboards import client as client_kb
from app.models.application import ApplicationMessage
from app.models.enums import MediaType
from app.models.user import User
from app.services.application_service import CreatedApplication, PostedMessage, StatusChange

logger = logging.getLogger(__name__)

#: Telegram tolerates roughly 30 messages/second to different chats; stay well
#: below that when fanning out to every client.
BROADCAST_CHUNK = 20
BROADCAST_PAUSE_SECONDS = 1.0
MAX_RETRY_AFTER_SECONDS = 30


class NotificationService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    # -- low level ---------------------------------------------------------
    async def _guarded(
        self, chat_id: int, operation: str, call: Callable[[], Awaitable[Any]]
    ) -> bool:
        """Run one Telegram call; retry once after a flood-wait, never raise."""
        for attempt in range(2):
            try:
                await call()
                return True
            except TelegramRetryAfter as exc:
                if attempt:
                    break
                await asyncio.sleep(min(exc.retry_after, MAX_RETRY_AFTER_SECONDS))
            except TelegramAPIError as exc:
                logger.warning(
                    "notification failed",
                    extra={
                        "operation": operation,
                        "telegram_user_id": chat_id,
                        "result": "failed",
                        "error_type": type(exc).__name__,
                    },
                )
                return False
        return False

    async def send(
        self, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
    ) -> bool:
        return await self._guarded(
            chat_id,
            "notify",
            lambda: self.bot.send_message(
                chat_id, text, reply_markup=reply_markup, parse_mode="HTML"
            ),
        )

    async def send_media(
        self,
        chat_id: int,
        media_type: MediaType,
        file_id: str,
        caption: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        senders: dict[MediaType, Callable[..., Awaitable[Any]]] = {
            MediaType.PHOTO: self.bot.send_photo,
            MediaType.VIDEO: self.bot.send_video,
            MediaType.DOCUMENT: self.bot.send_document,
        }
        sender = senders[media_type]
        return await self._guarded(
            chat_id,
            "notify_media",
            lambda: sender(
                chat_id, file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML"
            ),
        )

    async def send_attachments(self, chat_id: int, messages: Iterable[ApplicationMessage]) -> int:
        sent = 0
        for message in messages:
            if (
                message.media_type
                and message.media_file_id
                and await self.send_media(chat_id, message.media_type, message.media_file_id)
            ):
                sent += 1
        return sent

    async def _to_many(
        self,
        users: Sequence[User],
        text: str,
        markup: InlineKeyboardMarkup | None,
        attachment: ApplicationMessage | None = None,
    ) -> int:
        delivered = 0
        for user in users:
            if not user.can_use_bot:
                continue
            if attachment is not None:
                await self.send_attachments(user.telegram_id, [attachment])
            if await self.send(user.telegram_id, text, markup):
                delivered += 1
        return delivered

    # -- business notifications -------------------------------------------
    async def notify_new_application(self, created: CreatedApplication) -> int:
        application = created.application
        delivered = await self._to_many(
            created.admins,
            texts.new_application_notification(application, created.client),
            admin_kb.application_notification(application.id),
            created.first_message,
        )
        logger.info(
            "new application announced",
            extra={
                "operation": "notify_new_application",
                "entity_id": application.id,
                "result": f"{delivered}/{len(created.admins)}",
            },
        )
        return delivered

    async def notify_client_message(self, posted: PostedMessage) -> int:
        return await self._to_many(
            posted.recipients,
            texts.client_message_notification(
                posted.application, posted.client, posted.message.text
            ),
            admin_kb.application_notification(posted.application.id),
            posted.message,
        )

    async def notify_staff_reply(self, posted: PostedMessage) -> bool:
        client = posted.client
        if not client.can_use_bot:
            return False
        if posted.message.media_type:
            await self.send_attachments(client.telegram_id, [posted.message])
        return await self.send(
            client.telegram_id,
            texts.staff_reply_notification(posted.application, posted.message.text),
            client_kb.reply_to_staff(posted.application.id),
        )

    async def notify_status(self, change: StatusChange) -> bool:
        if not change.client.can_use_bot:
            return False
        return await self.send(
            change.client.telegram_id, texts.status_notification(change.application)
        )

    async def notify_cancelled(self, change: StatusChange, admins: Sequence[User]) -> int:
        return await self._to_many(
            admins, texts.client_cancelled_notification(change.application, change.client), None
        )

    async def broadcast_copy(
        self, users: Sequence[User], from_chat_id: int, message_id: int
    ) -> int:
        """Copy one admin message to many clients, throttled.

        ``copy_message`` keeps text formatting and media exactly as the admin
        composed them, without the "forwarded from" header.
        """
        delivered = 0
        for index, user in enumerate(users, start=1):
            if user.can_use_bot and await self._guarded(
                user.telegram_id,
                "broadcast",
                partial(self.bot.copy_message, user.telegram_id, from_chat_id, message_id),
            ):
                delivered += 1
            if index % BROADCAST_CHUNK == 0:
                await asyncio.sleep(BROADCAST_PAUSE_SECONDS)
        return delivered
