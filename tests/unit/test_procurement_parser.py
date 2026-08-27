"""Quick-mode procurement parser tests."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.domain.timeutils import to_local
from app.parsers.procurement_parser import RegexProcurementParser

TZ = ZoneInfo("Asia/Bishkek")
NOW = dt.datetime(2026, 8, 22, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def parser() -> RegexProcurementParser:
    return RegexProcurementParser(timezone=TZ, default_deadline_time=dt.time(18, 0))


def test_labelled_message(parser: RegexProcurementParser) -> None:
    parsed = parser.parse(
        "Название: Канцелярские товары\n"
        "Срок: 30.08.2026 17:00\n"
        "Описание: Необходимо собрать потребность подразделений.",
        now=NOW,
    )

    assert parsed.title == "Канцелярские товары"
    assert parsed.description == "Необходимо собрать потребность подразделений."
    assert parsed.deadline is not None
    local = to_local(parsed.deadline, TZ)
    assert (local.year, local.month, local.day, local.hour, local.minute) == (
        2026, 8, 30, 17, 0,
    )
    assert parsed.deadline_time_was_explicit is True
    assert parsed.is_complete


def test_free_form_message(parser: RegexProcurementParser) -> None:
    parsed = parser.parse(
        "Канцелярские товары\nдо 30 августа 17:00\nСобрать потребность всех отделов",
        now=NOW,
    )

    assert parsed.title == "Канцелярские товары"
    assert parsed.description == "Собрать потребность всех отделов"
    assert parsed.deadline is not None
    local = to_local(parsed.deadline, TZ)
    assert (local.month, local.day, local.hour) == (8, 30, 17)
    assert parsed.is_complete


def test_date_without_time_uses_configured_default(parser: RegexProcurementParser) -> None:
    parsed = parser.parse("Название: Продукты\nСрок: 25.09.2026", now=NOW)

    assert parsed.deadline is not None
    local = to_local(parsed.deadline, TZ)
    assert (local.hour, local.minute) == (18, 0)
    assert parsed.deadline_time_was_explicit is False


def test_missing_deadline_is_reported_not_invented(parser: RegexProcurementParser) -> None:
    parsed = parser.parse("Название: Продукты питания\nОписание: сбор потребности", now=NOW)

    assert parsed.title == "Продукты питания"
    assert parsed.deadline is None
    assert not parsed.is_complete
    assert any("срок" in error.reason for error in parsed.errors)


def test_empty_message(parser: RegexProcurementParser) -> None:
    parsed = parser.parse("   \n  ", now=NOW)
    assert parsed.title is None
    assert parsed.deadline is None
    assert parsed.errors


def test_unparsable_date_is_an_error(parser: RegexProcurementParser) -> None:
    parsed = parser.parse("Название: Продукты\nСрок: как можно скорее", now=NOW)
    assert parsed.deadline is None
    assert parsed.errors


def test_multiline_description_is_kept(parser: RegexProcurementParser) -> None:
    parsed = parser.parse(
        "Название: Продукты\nСрок: 30.08.2026\nОписание: Первая строка\nВторая строка",
        now=NOW,
    )
    assert parsed.description is not None
    assert "Первая строка" in parsed.description
    assert "Вторая строка" in parsed.description


def test_long_values_are_truncated() -> None:
    parser = RegexProcurementParser(
        timezone=TZ,
        default_deadline_time=dt.time(18, 0),
        max_title_length=10,
        max_description_length=12,
    )
    parsed = parser.parse(
        f"Название: {'A' * 100}\nСрок: 30.08.2026\nОписание: {'B' * 100}", now=NOW
    )
    assert parsed.title is not None and len(parsed.title) <= 10
    assert parsed.description is not None and len(parsed.description) <= 12


def test_deadline_is_stored_as_utc(parser: RegexProcurementParser) -> None:
    parsed = parser.parse("Название: Продукты\nСрок: 30.08.2026 17:00", now=NOW)
    assert parsed.deadline is not None
    assert parsed.deadline.tzinfo is not None
    assert parsed.deadline.utcoffset() == dt.timedelta(0)
    # Bishkek is UTC+6 -> 17:00 local is 11:00 UTC.
    assert parsed.deadline.hour == 11
