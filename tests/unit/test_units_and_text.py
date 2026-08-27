"""Unit registry, text sanitisation and Excel-safety tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.text import (
    escape_html,
    format_quantity,
    normalize_item_name,
    sanitize_excel_cell,
    sanitize_filename,
    sanitize_text,
    truncate,
)
from app.domain.units import canonical_units, is_known_unit, normalize_unit, register_unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("килограмм", "кг"),
        ("килограмма", "кг"),
        ("килограммов", "кг"),
        ("кг", "кг"),
        ("КГ", "кг"),
        ("литр", "л"),
        ("литра", "л"),
        ("литров", "л"),
        ("л", "л"),
        ("штука", "шт"),
        ("штуки", "шт"),
        ("штук", "шт"),
        ("шт", "шт"),
        ("г", "г"),
        ("тонна", "т"),
        ("м", "м"),
        ("м2", "м²"),
        ("м3", "м³"),
        ("упаковка", "уп"),
        ("упаковок", "уп"),
        ("коробка", "кор"),
        ("коробок", "кор"),
        ("пачка", "пач"),
        ("пачек", "пач"),
        ("ящик", "ящ"),
        ("ящиков", "ящ"),
        ("мешок", "меш"),
        ("мешков", "меш"),
        ("рулон", "рул"),
        ("рулонов", "рул"),
        ("комплект", "компл"),
        ("комплектов", "компл"),
        ("бутылка", "бут"),
        ("бутылок", "бут"),
        ("канистра", "кан"),
        ("канистр", "кан"),
    ],
)
def test_unit_normalisation(raw: str, expected: str) -> None:
    assert normalize_unit(raw) == expected


def test_unknown_unit_returns_none() -> None:
    assert normalize_unit("попугаев") is None
    assert normalize_unit("") is None
    assert normalize_unit(None) is None
    assert is_known_unit("кг") is True


def test_registry_is_extensible() -> None:
    assert normalize_unit("бухта") is None
    register_unit("бух", ("бухта", "бухты", "бухт"))
    try:
        assert normalize_unit("бухта") == "бух"
        assert "бух" in canonical_units()
    finally:
        # keep global state clean for the rest of the suite
        from app.domain import units

        units._UNIT_DEFINITIONS.pop("бух", None)
        units._rebuild_index()


# --- Excel formula injection ------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    ["=SUM(A1:A5)", "+cmd", "@formula", "-1+1", "=1+1", "\tinjected", "\rinjected"],
)
def test_formula_injection_is_neutralised(payload: str) -> None:
    result = sanitize_excel_cell(payload)
    assert isinstance(result, str)
    assert result.startswith("'")
    assert result[1:] == payload


def test_ordinary_values_are_untouched() -> None:
    assert sanitize_excel_cell("Сахар") == "Сахар"
    assert sanitize_excel_cell(50) == 50
    assert sanitize_excel_cell(Decimal("5.5")) == Decimal("5.5")
    assert sanitize_excel_cell(None) is None


def test_zero_width_prefixed_formula_is_caught() -> None:
    assert sanitize_excel_cell("​=SUM(A1)").startswith("'")


# --- filenames ---------------------------------------------------------------
def test_filename_keeps_cyrillic_but_strips_separators() -> None:
    assert sanitize_filename("REQ-2026-000345_Иван_Иванов") == "REQ-2026-000345_Иван_Иванов"
    assert "/" not in sanitize_filename("a/b/c")
    assert "\\" not in sanitize_filename("a\\b")
    assert ".." not in sanitize_filename("../../etc/passwd")


def test_filename_never_empty_or_reserved() -> None:
    assert sanitize_filename("") == "file"
    assert sanitize_filename("   ") == "file"
    assert sanitize_filename("CON") == "file"
    assert sanitize_filename("\x00\x01") == "file"


def test_filename_length_is_bounded() -> None:
    assert len(sanitize_filename("Я" * 500)) <= 120


# --- text helpers ------------------------------------------------------------
def test_sanitize_text_normalises_and_truncates() -> None:
    assert sanitize_text("  Привет   мир  ", 100) == "Привет мир"
    assert sanitize_text("a" * 50, 10) == "a" * 10
    assert sanitize_text(None, 10) == ""
    assert "\x07" not in sanitize_text("bad\x07text", 100)


def test_normalize_item_name_is_conservative() -> None:
    assert normalize_item_name("  Сахар ") == "сахар"
    assert normalize_item_name("Сахар") == normalize_item_name("сахар")
    assert normalize_item_name("Ёлка") == normalize_item_name("Елка")
    # Deliberately NOT merged: different products must stay different.
    assert normalize_item_name("Масло") != normalize_item_name("Масло подсолнечное")


def test_format_quantity_strips_trailing_zeros() -> None:
    assert format_quantity(Decimal("50.000")) == "50"
    assert format_quantity(Decimal("5.50")) == "5.5"
    assert format_quantity(Decimal("0.125")) == "0.125"
    assert format_quantity(Decimal("1E+2")) == "100"


def test_escape_html_and_truncate() -> None:
    assert escape_html("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"
    assert truncate("abcdef", 4) == "abc…"
    assert truncate("abc", 10) == "abc"
