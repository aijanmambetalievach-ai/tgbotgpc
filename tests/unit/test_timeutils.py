"""Timezone and deadline-parsing tests."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.domain.timeutils import (
    ensure_aware,
    format_date,
    format_datetime,
    format_human,
    format_timedelta_left,
    parse_deadline,
    to_local,
    to_utc,
    utcnow,
)

TZ = ZoneInfo("Asia/Bishkek")
DEFAULT_TIME = dt.time(18, 0)
NOW = dt.datetime(2026, 8, 22, 9, 0, tzinfo=dt.UTC)


def test_utcnow_is_aware_utc() -> None:
    value = utcnow()
    assert value.tzinfo is not None
    assert value.utcoffset() == dt.timedelta(0)


def test_ensure_aware_and_conversions() -> None:
    naive = dt.datetime(2026, 8, 25, 18, 0)
    aware = ensure_aware(naive, TZ)
    assert aware.tzinfo is TZ
    assert to_utc(naive, TZ).hour == 12  # Bishkek is UTC+6
    assert to_local(to_utc(naive, TZ), TZ).hour == 18


@pytest.mark.parametrize(
    ("raw", "expected_local", "explicit"),
    [
        ("25.08.2026", (2026, 8, 25, 18, 0), False),
        ("25.08.2026 18:00", (2026, 8, 25, 18, 0), True),
        ("25.08.2026 09:30", (2026, 8, 25, 9, 30), True),
        ("25/08/2026", (2026, 8, 25, 18, 0), False),
        ("25.08.26", (2026, 8, 25, 18, 0), False),
        ("2026-08-25 17:30", (2026, 8, 25, 17, 30), True),
        ("до 30 августа 17:00", (2026, 8, 30, 17, 0), True),
        ("30 августа 2026", (2026, 8, 30, 18, 0), False),
        ("Срок: 30.08.2026 17:00", (2026, 8, 30, 17, 0), True),
    ],
)
def test_parse_deadline(
    raw: str, expected_local: tuple[int, int, int, int, int], explicit: bool
) -> None:
    parsed = parse_deadline(raw, TZ, DEFAULT_TIME, now=NOW)
    assert parsed is not None
    local = to_local(parsed.value, TZ)
    assert (local.year, local.month, local.day, local.hour, local.minute) == expected_local
    assert parsed.time_was_explicit is explicit
    assert parsed.value.utcoffset() == dt.timedelta(0)


def test_year_omitted_rolls_into_the_future() -> None:
    # 1 January is already past on 2026-08-22 -> the user means 2027.
    parsed = parse_deadline("01.01", TZ, DEFAULT_TIME, now=NOW)
    assert parsed is not None
    assert to_local(parsed.value, TZ).year == 2027


@pytest.mark.parametrize("raw", ["", "как можно скорее", "32.13.2026", "просто текст"])
def test_unparsable_deadlines_return_none(raw: str) -> None:
    assert parse_deadline(raw, TZ, DEFAULT_TIME, now=NOW) is None


def test_formatting() -> None:
    value = dt.datetime(2026, 8, 25, 12, 0, tzinfo=dt.UTC)  # 18:00 Bishkek
    assert format_datetime(value, TZ) == "25.08.2026 18:00"
    assert format_date(value, TZ) == "25.08.2026"
    assert format_human(value, TZ) == "25 августа 2026, 18:00"


def test_time_left_rendering() -> None:
    deadline = dt.datetime(2026, 8, 25, 12, 0, tzinfo=dt.UTC)
    assert "осталось" in format_timedelta_left(deadline, NOW)
    assert format_timedelta_left(deadline, deadline + dt.timedelta(seconds=1)) == "срок истек"
