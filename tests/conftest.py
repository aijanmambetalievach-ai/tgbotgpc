"""Shared pytest fixtures."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.config.settings import Settings, get_settings
from app.models.enums import UserRole
from app.models.user import User

BISHKEK = ZoneInfo("Asia/Bishkek")


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def tz() -> ZoneInfo:
    return BISHKEK


@pytest.fixture
def now() -> dt.datetime:
    """Fixed 'current time' so date parsing tests are deterministic."""
    return dt.datetime(2026, 8, 22, 9, 0, tzinfo=dt.UTC)


def make_user(
    user_id: int = 1,
    role: UserRole = UserRole.PURCHASER,
    *,
    telegram_id: int | None = None,
    full_name: str = "Тестовый Пользователь",
    is_active: bool = True,
    revoked_at: dt.datetime | None = None,
) -> User:
    """Build a detached ``User`` for pure-logic tests (no database needed)."""
    user = User(
        telegram_id=telegram_id if telegram_id is not None else 100_000 + user_id,
        full_name=full_name,
        role=role,
        is_active=is_active,
        revoked_at=revoked_at,
    )
    user.id = user_id
    return user


@pytest.fixture
def employee() -> User:
    return make_user(1, UserRole.TENDER_EMPLOYEE, full_name="Сотрудник Тендера")


@pytest.fixture
def purchaser() -> User:
    return make_user(2, UserRole.PURCHASER, full_name="Иван Иванов")
