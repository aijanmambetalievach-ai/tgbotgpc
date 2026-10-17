"""Concurrency-safe generation of human-readable business numbers.

``ZV-2026-000123``.

The counter is incremented with a single atomic statement; PostgreSQL holds a
row lock for the duration of the ``ON CONFLICT DO UPDATE``, so two concurrent
transactions can never receive the same value. Numbers are allocated inside the
caller's transaction, which means a rolled-back operation simply leaves a gap —
gaps are acceptable, duplicates are not.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.number_counter import NumberCounter, NumberScope

#: "Заявка" — short, readable when dictated over the phone.
APPLICATION_PREFIX = "ZV"
NUMBER_WIDTH = 6


def format_number(prefix: str, year: int, value: int) -> str:
    return f"{prefix}-{year}-{value:0{NUMBER_WIDTH}d}"


class NumberingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_value(self, scope: str, year: int) -> int:
        dialect = self.session.get_bind().dialect.name
        insert = sqlite_insert if dialect == "sqlite" else pg_insert
        base = insert(NumberCounter).values(scope=scope, year=year, current_value=1)
        stmt: Any = base.on_conflict_do_update(
            index_elements=[NumberCounter.scope, NumberCounter.year],
            set_={"current_value": NumberCounter.current_value + 1},
        ).returning(NumberCounter.current_value)
        return int((await self.session.execute(stmt)).scalar_one())

    async def next_application_number(self, year: int) -> str:
        value = await self.next_value(NumberScope.APPLICATION, year)
        return format_number(APPLICATION_PREFIX, year, value)
