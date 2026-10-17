"""Telegram handlers.

Registration order matters: ``common`` owns the commands and the global
cancel, the client routers come next (their menu buttons interrupt any
dialog), then the admin-only routers and finally the global error handler.
"""

from aiogram import Router

from app.bot.handlers import (
    admin_applications,
    admin_content,
    admin_misc,
    client,
    client_flow,
    common,
    errors,
)


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(common.router)
    root.include_router(client.router)
    root.include_router(client_flow.router)
    root.include_router(admin_applications.router)
    root.include_router(admin_content.router)
    root.include_router(admin_misc.router)
    root.include_router(errors.router)
    return root


__all__ = [
    "admin_applications",
    "admin_content",
    "admin_misc",
    "build_router",
    "client",
    "client_flow",
    "common",
    "errors",
]
