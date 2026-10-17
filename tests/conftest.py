"""Shared pytest fixtures."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from aiogram import Dispatcher

from app.bot.bot import create_dispatcher
from app.config.settings import Settings, get_settings
from app.models.enums import ClientCategory, UserRole
from app.models.user import User

BISHKEK = ZoneInfo("Asia/Bishkek")


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def dispatcher() -> Dispatcher:
    """One dispatcher per test session: aiogram routers are module-level
    singletons and can be attached to a single parent only."""
    return create_dispatcher()


@pytest.fixture(scope="session")
def tz() -> ZoneInfo:
    return BISHKEK


def make_user(
    user_id: int = 1,
    role: UserRole = UserRole.CLIENT,
    *,
    telegram_id: int | None = None,
    full_name: str = "Тестовый Клиент",
    phone: str | None = "+996555123456",
    category: ClientCategory | None = ClientCategory.SUPPLIER,
    is_active: bool = True,
) -> User:
    """Build a detached ``User`` for pure-logic tests (no database needed)."""
    user = User(
        telegram_id=telegram_id if telegram_id is not None else 100_000 + user_id,
        full_name=full_name,
        phone=phone,
        role=role,
        category=category,
        is_active=is_active,
    )
    user.id = user_id
    return user
