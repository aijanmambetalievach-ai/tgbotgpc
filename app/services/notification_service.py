"""Outbound Telegram notifications.

Called **after** the database transaction has committed (requirement 42): a
failed or blocked chat must never roll back a correctly saved business
operation. Every send is therefore individually guarded and only logged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

from app.bot import texts
from app.bot.keyboards import purchaser as purchaser_kb
from app.bot.keyboards import tender_employee as employee_kb
from app.config.settings import Settings, get_settings
from app.models.enums import PurchaseRequestStatus
from app.models.procurement import Procurement
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_item import PurchaseRequestItem
from app.models.user import User
from app.services.excel_export_service import ExcelFile

logger = logging.getLogger(__name__)

#: Telegram tolerates roughly 30 messages/second to different chats; stay well
#: below that when fanning out to every participant.
BROADCAST_CHUNK = 20
BROADCAST_PAUSE_SECONDS = 1.0
MAX_RETRY_AFTER_SECONDS = 30


class NotificationService:
    def __init__(self, bot: Bot, settings: Settings | None = None) -> None:
        self.bot = bot
        self.settings = settings or get_settings()

    # -- low level ---------------------------------------------------------
    async def send(
        self,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        try:
            await self.bot.send_message(
                chat_id, text, reply_markup=reply_markup, parse_mode="HTML"
            )
            return True
        except TelegramRetryAfter as exc:
            delay = min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
            await asyncio.sleep(delay)
            return await self._send_once(chat_id, text, reply_markup)
        except TelegramAPIError as exc:
            logger.warning(
                "notification failed",
                extra={
                    "operation": "notify",
                    "telegram_user_id": chat_id,
                    "result": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            return False

    async def _send_once(
        self, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None
    ) -> bool:
        try:
            await self.bot.send_message(
                chat_id, text, reply_markup=reply_markup, parse_mode="HTML"
            )
            return True
        except TelegramAPIError as exc:  # pragma: no cover - network dependent
            logger.warning(
                "notification retry failed",
                extra={
                    "operation": "notify",
                    "telegram_user_id": chat_id,
                    "result": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            return False

    async def send_document(
        self, chat_id: int, excel: ExcelFile, caption: str | None = None
    ) -> bool:
        try:
            await self.bot.send_document(
                chat_id,
                BufferedInputFile(excel.content, filename=excel.filename),
                caption=caption,
                parse_mode="HTML",
            )
            return True
        except TelegramAPIError as exc:
            logger.warning(
                "document delivery failed",
                extra={
                    "operation": "notify_document",
                    "telegram_user_id": chat_id,
                    "result": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            return False

    async def broadcast(
        self,
        users: Iterable[User],
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> int:
        """Send the same message to many users, throttled. Returns delivered count."""
        delivered = 0
        for index, user in enumerate(users, start=1):
            if not user.can_use_bot:
                continue
            if await self.send(user.telegram_id, text, reply_markup):
                delivered += 1
            if index % BROADCAST_CHUNK == 0:
                await asyncio.sleep(BROADCAST_PAUSE_SECONDS)
        return delivered

    # -- business notifications -------------------------------------------
    async def notify_new_procurement(
        self, participants: Sequence[User], procurement: Procurement
    ) -> int:
        text = texts.new_procurement_notification(procurement, self.settings.timezone)
        markup = purchaser_kb.new_procurement_notification(procurement.id)
        delivered = await self.broadcast(participants, text, markup)
        logger.info(
            "procurement broadcast finished",
            extra={
                "operation": "notify_new_procurement",
                "procurement_id": procurement.id,
                "result": f"{delivered}/{len(participants)}",
            },
        )
        return delivered

    async def notify_reminder(
        self, participants: Sequence[User], procurement: Procurement
    ) -> int:
        text = texts.reminder_notification(procurement, self.settings.timezone)
        markup = purchaser_kb.new_procurement_notification(procurement.id)
        return await self.broadcast(participants, text, markup)

    async def notify_new_request(
        self,
        employees: Sequence[User],
        request: PurchaseRequest,
        procurement: Procurement | None,
        purchaser: User,
        items: Sequence[PurchaseRequestItem],
        excel: ExcelFile | None = None,
    ) -> int:
        text = texts.new_request_notification(
            request,
            procurement,
            purchaser,
            items,
            self.settings.timezone,
            self.settings.preview_items_limit,
        )
        markup = employee_kb.new_request_notification(request.id)
        delivered = 0
        for employee in employees:
            if not employee.can_use_bot:
                continue
            if await self.send(employee.telegram_id, text, markup):
                delivered += 1
                if excel is not None:
                    await self.send_document(employee.telegram_id, excel)
        return delivered

    async def notify_request_status(
        self,
        purchaser: User,
        request: PurchaseRequest,
        new_status: PurchaseRequestStatus,
        reason: str | None = None,
    ) -> bool:
        if not purchaser.can_use_bot:
            return False
        text = texts.request_status_notification(request, new_status, reason)
        return await self.send(purchaser.telegram_id, text)
