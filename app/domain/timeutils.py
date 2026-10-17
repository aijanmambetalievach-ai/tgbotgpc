"""Timezone-aware date/time helpers.

Rules enforced across the codebase:

* storage and business logic always use **aware UTC** datetimes;
* naive datetimes never cross a layer boundary;
* every user-facing string is rendered in the configured application timezone.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

UTC = dt.UTC

MONTHS_NOMINATIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def utcnow() -> dt.datetime:
    """Current time as an aware UTC datetime."""
    return dt.datetime.now(tz=UTC)


def ensure_aware(value: dt.datetime, tz: ZoneInfo | dt.tzinfo = UTC) -> dt.datetime:
    """Attach ``tz`` to a naive datetime; leave aware datetimes alone."""
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value


def to_utc(value: dt.datetime, tz: ZoneInfo | dt.tzinfo = UTC) -> dt.datetime:
    return ensure_aware(value, tz).astimezone(UTC)


def to_local(value: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    return ensure_aware(value, UTC).astimezone(tz)


def format_datetime(value: dt.datetime, tz: ZoneInfo) -> str:
    """``25.08.2026 18:00``"""
    return to_local(value, tz).strftime("%d.%m.%Y %H:%M")


def format_date(value: dt.datetime, tz: ZoneInfo) -> str:
    """``25.08.2026``"""
    return to_local(value, tz).strftime("%d.%m.%Y")


def format_human(value: dt.datetime, tz: ZoneInfo) -> str:
    """``25 августа 2026, 18:00``"""
    local = to_local(value, tz)
    return f"{local.day} {MONTHS_NOMINATIVE[local.month - 1]} {local.year}, {local:%H:%M}"
