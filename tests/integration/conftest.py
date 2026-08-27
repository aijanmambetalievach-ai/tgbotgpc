"""Integration test fixtures — require a live PostgreSQL database.

The whole module self-skips when ``TEST_DATABASE_URL`` is not configured, so
``pytest`` still runs the unit suite on a machine without a database.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from alembic import command
from app.config.settings import Settings, get_settings
from app.domain.timeutils import utcnow
from app.models.enums import ParticipantSelectionMode, ProcurementStatus, UserRole
from app.models.procurement import Procurement
from app.models.user import User
from app.services.procurement_service import ProcurementDraftInput, ProcurementService

TABLES = (
    "audit_logs",
    "status_history",
    "purchase_request_items",
    "purchase_requests",
    "procurement_participants",
    "procurements",
    "invites",
    "number_counters",
    "users",
)


def _test_database_url() -> str | None:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    return get_settings().test_database_url


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured — integration tests skipped")
    return url


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> Iterator[str]:
    """Apply Alembic migrations once per test session.

    Using the real migrations (not ``create_all``) means the test suite also
    verifies that the migration scripts produce a working schema.
    """
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    command.upgrade(config, "head")

    yield database_url

    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous
    get_settings.cache_clear()


@pytest.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    created = create_async_engine(migrated_database, poolclass=NullPool, future=True)
    async with created.begin() as connection:
        await connection.execute(
            text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        )
    yield created
    await created.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as opened:
        yield opened


@pytest.fixture
def settings() -> Settings:
    return get_settings()


# --- data builders ----------------------------------------------------------
async def create_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    full_name: str,
    role: UserRole = UserRole.PURCHASER,
    is_active: bool = True,
    revoked_at: dt.datetime | None = None,
) -> User:
    user = User(
        telegram_id=telegram_id,
        full_name=full_name,
        role=role,
        is_active=is_active,
        revoked_at=revoked_at,
    )
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def employee(session: AsyncSession) -> User:
    return await create_user(
        session,
        telegram_id=1001,
        full_name="Сотрудник Тендера",
        role=UserRole.TENDER_EMPLOYEE,
    )


@pytest.fixture
async def purchasers(session: AsyncSession) -> list[User]:
    return [
        await create_user(session, telegram_id=2001, full_name="Иван Иванов"),
        await create_user(session, telegram_id=2002, full_name="Азамат Садыков"),
        await create_user(session, telegram_id=2003, full_name="Данияр Алиев"),
    ]


async def make_open_procurement(
    session: AsyncSession,
    employee: User,
    participants: list[User],
    *,
    title: str = "Продукты питания на сентябрь",
    deadline: dt.datetime | None = None,
) -> Procurement:
    service = ProcurementService(session)
    result = await service.create_and_publish(
        employee,
        ProcurementDraftInput(
            title=title,
            deadline=deadline or (utcnow() + dt.timedelta(days=3)),
            description="Сбор потребности подразделений.",
            participant_mode=ParticipantSelectionMode.MANUAL,
            participant_ids=[user.id for user in participants],
        ),
    )
    assert result.procurement.status is ProcurementStatus.OPEN
    return result.procurement
