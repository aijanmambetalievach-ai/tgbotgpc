"""Integration test fixtures — require a live PostgreSQL database.

The whole module self-skips when ``TEST_DATABASE_URL`` is not configured, so
``pytest`` still runs the unit suite on a machine without a database.
"""

from __future__ import annotations

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
from app.models.content import Course, Lesson
from app.models.enums import (
    Audience,
    ClientCategory,
    ContentStatus,
    CourseDelivery,
    UserRole,
)
from app.models.user import User

TABLES = (
    "audit_logs",
    "application_messages",
    "applications",
    "lesson_progress",
    "lesson_questions",
    "lessons",
    "courses",
    "faq_entries",
    "bot_texts",
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
        await connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
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
    role: UserRole = UserRole.CLIENT,
    category: ClientCategory | None = ClientCategory.SUPPLIER,
    phone: str | None = "+996555000111",
    is_active: bool = True,
) -> User:
    user = User(
        telegram_id=telegram_id,
        full_name=full_name,
        role=role,
        category=category,
        phone=phone,
        is_active=is_active,
    )
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def admin(session: AsyncSession) -> User:
    return await create_user(
        session,
        telegram_id=1001,
        full_name="Администратор Центра",
        role=UserRole.ADMIN,
        category=None,
    )


@pytest.fixture
async def client(session: AsyncSession) -> User:
    return await create_user(session, telegram_id=2001, full_name="Айгуль Садыкова")


@pytest.fixture
async def other_client(session: AsyncSession) -> User:
    return await create_user(
        session, telegram_id=2002, full_name="Данияр Алиев", category=ClientCategory.PURCHASER
    )


async def create_course(
    session: AsyncSession,
    *,
    title: str = "Портал госзакупок с нуля",
    audience: Audience = Audience.ALL,
    status: ContentStatus = ContentStatus.PUBLISHED,
    position: int = 0,
) -> Course:
    course = Course(
        title=title,
        description="Три дня практики",
        audience=audience,
        delivery=CourseDelivery.ONLINE,
        schedule="15–17 ноября",
        price="4 500 сом",
        location="",
        status=status,
        position=position,
    )
    session.add(course)
    await session.commit()
    return course


async def create_lesson(
    session: AsyncSession,
    *,
    title: str,
    position: int,
    audience: Audience = Audience.ALL,
    status: ContentStatus = ContentStatus.PUBLISHED,
) -> Lesson:
    lesson = Lesson(
        title=title, body=f"Текст: {title}", audience=audience, position=position, status=status
    )
    session.add(lesson)
    await session.commit()
    return lesson
