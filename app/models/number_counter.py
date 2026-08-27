"""Database-backed, concurrency-safe counters for human-readable numbers.

A single row per ``(scope, year)`` is incremented with an atomic
``INSERT ... ON CONFLICT DO UPDATE ... RETURNING`` statement. PostgreSQL takes
a row lock for the duration of the update, so concurrent transactions are
serialised on that row and can never observe the same value — unlike an unsafe
``max(id) + 1`` read-then-write.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class NumberCounter(Base):
    __tablename__ = "number_counters"

    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    current_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class NumberScope:
    PROCUREMENT = "procurement"
    PURCHASE_REQUEST = "purchase_request"
