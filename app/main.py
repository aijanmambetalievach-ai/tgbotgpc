"""Application entrypoint.

Runs the Telegram bot (long polling) and the FastAPI health server in one
process — a modular monolith, not two deployables.

    python -m app.main
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from aiogram import Bot, Dispatcher
from fastapi import FastAPI

from app import __version__
from app.api.router import api_router
from app.bot.bot import create_bot, create_dispatcher
from app.config.logging import setup_logging
from app.config.settings import Settings, get_settings
from app.database.session import dispose_engine, init_engine, session_scope
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_engine()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """FastAPI factory (also used by tests and `uvicorn app.main:create_app`)."""
    settings = settings or get_settings()
    app = FastAPI(
        title="Tender Bot API",
        version=__version__,
        docs_url="/docs" if settings.app_env != "prod" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.include_router(api_router)
    return app


async def _bootstrap(settings: Settings) -> None:
    """Seed the configured tender employees before serving traffic."""
    if not settings.bootstrap_admin_ids:
        logger.warning(
            "BOOTSTRAP_ADMIN_TELEGRAM_IDS is empty — no tender employee will be seeded",
            extra={"operation": "bootstrap", "result": "skipped"},
        )
        return
    async with session_scope() as session:
        created = await AuthService(session, settings).bootstrap_employees()
    logger.info(
        "bootstrap finished",
        extra={"operation": "bootstrap", "result": f"created={len(created)}"},
    )


async def _run_api(settings: Settings) -> None:
    config = uvicorn.Config(
        create_app(settings),
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    await uvicorn.Server(config).serve()


async def _run_bot(bot: Bot, dispatcher: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=False)
    await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)
    logger.info(
        "starting tender bot",
        extra={"operation": "startup", "result": settings.app_env},
    )

    init_engine(settings)
    await _bootstrap(settings)

    bot = create_bot(settings)
    dispatcher = create_dispatcher(settings)

    tasks: list[asyncio.Task[None]] = [asyncio.create_task(_run_bot(bot, dispatcher))]
    if settings.api_enabled:
        tasks.append(asyncio.create_task(_run_api(settings)))

    stop = asyncio.Event()
    _install_signal_handlers(stop)
    waiter = asyncio.create_task(stop.wait())

    try:
        done, _pending = await asyncio.wait(
            [*tasks, waiter], return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            if task is not waiter and task.exception() is not None:
                raise task.exception()  # type: ignore[misc]
    finally:
        logger.info("shutting down", extra={"operation": "shutdown"})
        for task in [*tasks, waiter]:
            task.cancel()
        for task in [*tasks, waiter]:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        with contextlib.suppress(Exception):
            await dispatcher.storage.close()
        with contextlib.suppress(Exception):
            await bot.session.close()
        await dispose_engine()


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows: asyncio does not support add_signal_handler; the default
            # KeyboardInterrupt path is used instead.
            signal.signal(sig, lambda *_: stop.set())


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):  # pragma: no cover - manual stop
        logger.info("stopped by user")
    except Exception:
        logging.getLogger(__name__).exception("fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
