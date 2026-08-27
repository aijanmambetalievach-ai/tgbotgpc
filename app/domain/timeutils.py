"""Timezone-aware date/time helpers.

Rules enforced across the codebase:

* storage and business logic always use **aware UTC** datetimes;
* naive datetimes never cross a layer boundary;
* every user-facing string is rendered in the configured application timezone.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

UTC = dt.UTC

MONTHS_NOMINATIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

_MONTH_ALIASES: dict[str, int] = {}
for _index, _name in enumerate(MONTHS_NOMINATIVE, start=1):
    _MONTH_ALIASES[_name] = _index
for _index, _name in enumerate(
    (
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    ),
    start=1,
):
    _MONTH_ALIASES[_name] = _index
for _index, _name in enumerate(
    ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"),
    start=1,
):
    _MONTH_ALIASES.setdefault(_name, _index)


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


def format_timedelta_left(deadline: dt.datetime, now: dt.datetime) -> str:
    """Human readable remaining time, e.g. ``осталось 2 дн. 4 ч.``"""
    delta = deadline - now
    if delta.total_seconds() <= 0:
        return "срок истек"
    days, seconds = delta.days, delta.seconds
    hours, minutes = seconds // 3600, (seconds % 3600) // 60
    if days:
        return f"осталось {days} дн. {hours} ч."
    if hours:
        return f"осталось {hours} ч. {minutes} мин."
    return f"осталось {minutes} мин."


@dataclass(frozen=True, slots=True)
class ParsedDeadline:
    """Result of interpreting a user-supplied deadline string."""

    value: dt.datetime
    """Aware UTC datetime."""
    time_was_explicit: bool
    """``False`` when only a date was given and the default time was applied."""
    source_text: str


_DATE_NUMERIC = re.compile(
    r"\b(?P<day>\d{1,2})[.\-/](?P<month>\d{1,2})(?:[.\-/](?P<year>\d{2,4}))?\b"
)
_DATE_ISO = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")
_DATE_WORDS = re.compile(
    r"\b(?P<day>\d{1,2})\s+(?P<month>[а-яё]{3,8})\.?(?:\s+(?P<year>\d{4}))?",
    re.IGNORECASE,
)
_TIME = re.compile(r"\b(?P<hour>[01]?\d|2[0-3])[:.](?P<minute>[0-5]\d)\b")


def parse_deadline(
    raw: str,
    tz: ZoneInfo,
    default_time: dt.time,
    now: dt.datetime | None = None,
) -> ParsedDeadline | None:
    """Parse a deadline written by a human.

    Supported shapes (case-insensitive, extra words are ignored)::

        25.08.2026            25.08.2026 18:00
        25/08/26              2026-08-25 17:30
        до 30 августа 17:00   30 августа 2026

    The time is interpreted in ``tz`` and converted to UTC. When no time is
    present, ``default_time`` is applied and ``time_was_explicit`` is ``False``
    so the UI can show the assumption to the user before confirmation.
    """
    text = raw.strip().lower().replace("ё", "е")
    if not text:
        return None
    now = now or utcnow()
    local_now = to_local(now, tz)

    day = month = year = None
    date_span: tuple[int, int] | None = None

    match = _DATE_ISO.search(text)
    if match:
        year, month, day = (
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
        date_span = match.span()
    if day is None:
        match = _DATE_NUMERIC.search(text)
        if match:
            day, month = int(match.group("day")), int(match.group("month"))
            raw_year = match.group("year")
            year = _expand_year(int(raw_year)) if raw_year else None
            date_span = match.span()
    if day is None:
        match = _DATE_WORDS.search(text)
        if match:
            month_name = match.group("month")
            month = _MONTH_ALIASES.get(month_name) or _MONTH_ALIASES.get(month_name[:3])
            if month is None:
                return None
            day = int(match.group("day"))
            raw_year = match.group("year")
            year = int(raw_year) if raw_year else None
            date_span = match.span()

    if day is None or month is None:
        return None

    # Look for the time *outside* the date itself, otherwise "25.08.26" would
    # be misread as 08:26.
    remainder = f"{text[: date_span[0]]} {text[date_span[1] :]}" if date_span else text
    time_match = _TIME.search(remainder)
    if time_match:
        hour, minute = int(time_match.group("hour")), int(time_match.group("minute"))
        explicit = True
    else:
        hour, minute = default_time.hour, default_time.minute
        explicit = False

    candidate_year = year if year is not None else local_now.year
    try:
        local_dt = dt.datetime(
            candidate_year, month, day, hour, minute, tzinfo=tz
        )
    except ValueError:
        return None

    # Year omitted and the date already passed -> the user means next year.
    if year is None and local_dt <= local_now:
        try:
            local_dt = local_dt.replace(year=candidate_year + 1)
        except ValueError:  # 29 February edge case
            return None

    return ParsedDeadline(
        value=local_dt.astimezone(UTC), time_was_explicit=explicit, source_text=raw.strip()
    )


def _expand_year(value: int) -> int:
    """``26`` -> ``2026``; four digit years pass through unchanged."""
    if value >= 1000:
        return value
    return 2000 + value
