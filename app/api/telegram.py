"""Telegram webhook endpoint (used when ``WEBHOOK_BASE_URL`` is set).

Telegram POSTs every update here. The request is acknowledged immediately and
the update is processed in the background: Telegram waits only a few seconds
for an answer, and a slow handler (an Excel export, a broadcast) must not make
it retry and deliver the same update twice.
"""

from __future__ import annotations

import asyncio
import logging
import secrets

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, Header, Request, Response, status
from pydantic import ValidationError

from app.config.settings import WEBHOOK_PATH

logger = logging.getLogger(__name__)


def build_webhook_router(bot: Bot, dispatcher: Dispatcher, secret: str) -> APIRouter:
    router = APIRouter(tags=["telegram"])
    #: Strong references so in-flight updates are not garbage-collected.
    in_flight: set[asyncio.Task[object]] = set()

    @router.post(WEBHOOK_PATH, include_in_schema=False)
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> Response:
        if not secrets.compare_digest(x_telegram_bot_api_secret_token or "", secret):
            logger.warning("webhook call with a wrong secret", extra={"operation": "webhook"})
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        try:
            update = Update.model_validate(await request.json(), context={"bot": bot})
        except (ValueError, ValidationError):
            return Response(status_code=status.HTTP_400_BAD_REQUEST)

        task: asyncio.Task[object] = asyncio.create_task(dispatcher.feed_update(bot, update))
        in_flight.add(task)
        task.add_done_callback(in_flight.discard)
        return Response(status_code=status.HTTP_200_OK)

    return router
