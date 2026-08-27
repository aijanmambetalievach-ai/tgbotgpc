"""Bot and dispatcher factories."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import build_router
from app.bot.middlewares.auth import AuthMiddleware
from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.logging import UpdateLoggingMiddleware
from app.bot.middlewares.throttling import ThrottlingMiddleware
from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def create_bot(settings: Settings | None = None) -> Bot:
    settings = settings or get_settings()
    token = settings.bot_token.get_secret_value()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not configured. Copy .env.example to .env and set the token "
            "issued by @BotFather."
        )
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_dispatcher(settings: Settings | None = None) -> Dispatcher:
    """Wire middlewares and routers.

    Middleware order (outermost first):
    logging → throttling → database session → authorization.
    Authorization runs last so it already has a session to look the user up in.
    """
    settings = settings or get_settings()
    dispatcher = Dispatcher(storage=MemoryStorage())

    dispatcher.update.outer_middleware(UpdateLoggingMiddleware())
    dispatcher.update.outer_middleware(ThrottlingMiddleware(settings))
    dispatcher.update.outer_middleware(DbSessionMiddleware())
    dispatcher.update.outer_middleware(AuthMiddleware())

    dispatcher.include_router(build_router())
    return dispatcher
