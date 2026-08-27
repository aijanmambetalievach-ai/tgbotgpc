"""Telegram handlers.

Registration order matters: ``common`` owns the commands, then the two
role-scoped routers, and finally the global error handler.
"""

from aiogram import Router

from app.bot.handlers import common, errors, purchaser, tender_employee


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(common.router)
    root.include_router(tender_employee.router)
    root.include_router(purchaser.router)
    root.include_router(errors.router)
    return root


__all__ = ["build_router", "common", "errors", "purchaser", "tender_employee"]
