"""Number formatting and pagination arithmetic."""

from __future__ import annotations

import pytest

from app.repositories.base import Page, normalize_page, offset_for
from app.repositories.numbering import (
    PROCUREMENT_PREFIX,
    REQUEST_PREFIX,
    format_number,
)


def test_number_format_matches_specification() -> None:
    assert format_number(PROCUREMENT_PREFIX, 2026, 1) == "TENDER-2026-000001"
    assert format_number(PROCUREMENT_PREFIX, 2026, 123) == "TENDER-2026-000123"
    assert format_number(REQUEST_PREFIX, 2026, 345) == "REQ-2026-000345"
    assert format_number(REQUEST_PREFIX, 2027, 1_000_000) == "REQ-2027-1000000"


@pytest.mark.parametrize(
    ("total", "page_size", "requested", "expected"),
    [
        (0, 10, 1, 1),
        (0, 10, 5, 1),
        (25, 10, 1, 1),
        (25, 10, 3, 3),
        (25, 10, 99, 3),
        (25, 10, -4, 1),
    ],
)
def test_normalize_page(total: int, page_size: int, requested: int, expected: int) -> None:
    assert normalize_page(requested, page_size, total) == expected


def test_offset() -> None:
    assert offset_for(1, 10) == 0
    assert offset_for(3, 10) == 20
    assert offset_for(0, 10) == 0


def test_page_metadata() -> None:
    page: Page[int] = Page(items=[1, 2, 3], total=25, page=2, page_size=10)
    assert page.pages == 3
    assert page.has_prev is True
    assert page.has_next is True
    assert page.is_empty is False

    empty: Page[int] = Page(items=[], total=0, page=1, page_size=10)
    assert empty.pages == 1
    assert empty.has_prev is False
    assert empty.has_next is False
    assert empty.is_empty is True
