"""Concurrency safety of the business-number generator."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.number_counter import NumberScope
from app.repositories.numbering import NumberingRepository

pytestmark = pytest.mark.integration

CONCURRENCY = 25


async def _allocate(factory: async_sessionmaker[AsyncSession], year: int) -> str:
    async with factory() as session:
        number = await NumberingRepository(session).next_procurement_number(year)
        await session.commit()
        return number


async def test_concurrent_allocation_never_duplicates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    numbers = await asyncio.gather(
        *(_allocate(session_factory, 2026) for _ in range(CONCURRENCY))
    )

    assert len(numbers) == CONCURRENCY
    assert len(set(numbers)) == CONCURRENCY, "duplicate business numbers were issued"

    values = sorted(int(number.rsplit("-", 1)[1]) for number in numbers)
    assert values == list(range(1, CONCURRENCY + 1)), "the sequence has gaps or repeats"


async def test_counters_are_isolated_per_scope_and_year(
    session: AsyncSession,
) -> None:
    repo = NumberingRepository(session)

    assert await repo.next_value(NumberScope.PROCUREMENT, 2026) == 1
    assert await repo.next_value(NumberScope.PROCUREMENT, 2026) == 2
    assert await repo.next_value(NumberScope.PURCHASE_REQUEST, 2026) == 1
    assert await repo.next_value(NumberScope.PROCUREMENT, 2027) == 1
    await session.commit()

    assert await repo.next_procurement_number(2026) == "TENDER-2026-000003"
    assert await repo.next_request_number(2026) == "REQ-2026-000002"
    await session.commit()
