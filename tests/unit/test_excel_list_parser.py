"""Importing a purchase list from an uploaded Excel workbook."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.parsers.excel_list_parser import (
    REASON_EMPTY_FILE,
    REASON_UNREADABLE_FILE,
    ExcelPurchaseListParser,
)
from app.parsers.purchase_list_parser import REASON_NO_UNIT
from app.services.excel_export_service import build_items_template

EXAMPLE_FILE = Path("docs/test.xlsx")


@pytest.fixture
def parser() -> ExcelPurchaseListParser:
    return ExcelPurchaseListParser()


def build(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- the shape produced by an exported request ------------------------------
def test_exported_request_layout(parser: ExcelPurchaseListParser) -> None:
    content = build(
        [
            ["Закупка:", "вне закупки (инициативная заявка)"],
            ["Название:", "—"],
            ["Заявка:", "REQ-2026-000003"],
            ["Закупщик:", "Test"],
            ["Дата:", "25.08.2026 19:46"],
            ["Статус:", "Отправлена"],
            [],
            ["№", "Наименование", "Количество", "Ед. измерения", "Комментарий"],
            [1, "Бумага А4", 20, "пач", None],
            [2, "Картриджи", 5, "шт", None],
            [3, "Ручки", 100, "шт", None],
        ]
    )
    result = parser.parse_file(content)

    assert result.errors == []
    assert [item.name for item in result.items] == ["Бумага А4", "Картриджи", "Ручки"]
    assert [item.unit for item in result.items] == ["пач", "шт", "шт"]
    assert [item.quantity for item in result.items] == [
        Decimal(20),
        Decimal(5),
        Decimal(100),
    ]
    # Header metadata must never leak in as an item.
    assert all("Закупщик" not in item.name for item in result.items)


@pytest.mark.skipif(not EXAMPLE_FILE.exists(), reason="example workbook is not in the repo")
def test_real_example_file(parser: ExcelPurchaseListParser) -> None:
    result = parser.parse_file(EXAMPLE_FILE.read_bytes())
    assert result.errors == []
    assert [(item.name, str(item.quantity), item.unit) for item in result.items] == [
        ("Бумага А4", "20", "пач"),
        ("Картриджи", "5", "шт"),
        ("Ручки", "100", "шт"),
    ]


# --- other layouts ----------------------------------------------------------
def test_plain_header_table(parser: ExcelPurchaseListParser) -> None:
    content = build(
        [
            ["Наименование", "Количество", "Ед. изм."],
            ["Сахар", 50, "кг"],
            ["Масло", 5.5, "литров"],
        ]
    )
    result = parser.parse_file(content)
    assert result.errors == []
    assert result.items[0].quantity == Decimal("50")
    assert result.items[1].quantity == Decimal("5.5")
    assert result.items[1].unit == "л"


def test_columns_in_any_order(parser: ExcelPurchaseListParser) -> None:
    content = build(
        [
            ["Ед. измерения", "Комментарий", "Товар", "Кол-во"],
            ["кг", "первый сорт", "Мука", 100],
        ]
    )
    result = parser.parse_file(content)
    assert result.errors == []
    item = result.items[0]
    assert (item.name, item.unit, item.quantity) == ("Мука", "кг", Decimal(100))
    assert item.comment == "первый сорт"


def test_table_without_headers(parser: ExcelPurchaseListParser) -> None:
    content = build([["Сахар", 50, "кг"], ["Яйца", 200, "шт"]])
    result = parser.parse_file(content)
    assert result.errors == []
    assert [item.name for item in result.items] == ["Сахар", "Яйца"]


def test_single_column_free_text(parser: ExcelPurchaseListParser) -> None:
    content = build([["1. Сахар — 50 кг"], ["2. Масло — 5,5 л"]])
    result = parser.parse_file(content)
    assert result.errors == []
    assert [item.unit for item in result.items] == ["кг", "л"]
    assert result.items[1].quantity == Decimal("5.5")


def test_quantity_and_unit_in_one_cell(parser: ExcelPurchaseListParser) -> None:
    content = build([["Наименование", "Количество"], ["Сахар", "50 кг"]])
    result = parser.parse_file(content)
    assert result.errors == []
    assert (result.items[0].quantity, result.items[0].unit) == (Decimal(50), "кг")


def test_comma_decimal_in_text_cell(parser: ExcelPurchaseListParser) -> None:
    content = build([["Наименование", "Количество", "Ед."], ["Масло", "5,5", "л"]])
    result = parser.parse_file(content)
    assert result.errors == []
    assert result.items[0].quantity == Decimal("5.5")


def test_blank_rows_are_skipped(parser: ExcelPurchaseListParser) -> None:
    content = build(
        [
            ["Наименование", "Количество", "Ед."],
            ["Сахар", 50, "кг"],
            [None, None, None],
            ["", "", ""],
            ["Мука", 100, "кг"],
        ]
    )
    result = parser.parse_file(content)
    assert result.errors == []
    assert len(result.items) == 2


# --- errors are reported, never guessed -------------------------------------
def test_missing_unit_is_an_error(parser: ExcelPurchaseListParser) -> None:
    content = build([["Наименование", "Количество"], ["Сахар", 50]])
    result = parser.parse_file(content)
    assert result.items == []
    assert REASON_NO_UNIT in result.errors[0].reason


def test_unknown_unit_is_an_error(parser: ExcelPurchaseListParser) -> None:
    content = build([["Наименование", "Количество", "Ед."], ["Бумага", 500, "листов"]])
    result = parser.parse_file(content)
    assert result.items == []
    assert "неизвестная единица" in result.errors[0].reason


def test_zero_and_text_quantities_are_errors(parser: ExcelPurchaseListParser) -> None:
    content = build(
        [
            ["Наименование", "Количество", "Ед."],
            ["Сахар", 0, "кг"],
            ["Масло", "несколько", "л"],
            ["Мука", 100, "кг"],
        ]
    )
    result = parser.parse_file(content)
    assert [item.name for item in result.items] == ["Мука"]
    assert len(result.errors) == 2


def test_good_and_bad_rows_coexist(parser: ExcelPurchaseListParser) -> None:
    content = build(
        [
            ["Наименование", "Количество", "Ед."],
            ["Сахар", 50, "кг"],
            ["Масло", None, None],
            ["Яйца", 200, "шт"],
        ]
    )
    result = parser.parse_file(content)
    assert [item.name for item in result.items] == ["Сахар", "Яйца"]
    assert len(result.errors) == 1


def test_empty_workbook(parser: ExcelPurchaseListParser) -> None:
    result = parser.parse_file(build([]))
    assert result.items == []
    assert result.errors[0].reason == REASON_EMPTY_FILE


@pytest.mark.parametrize(
    "content",
    [b"", b"not a spreadsheet at all", b"PK\x03\x04 broken zip"],
)
def test_garbage_input_is_rejected_gracefully(
    parser: ExcelPurchaseListParser, content: bytes
) -> None:
    result = parser.parse_file(content)
    assert result.items == []
    assert result.errors[0].reason == REASON_UNREADABLE_FILE


def test_formulas_are_not_evaluated() -> None:
    """A formula without a cached value yields an error row, never a computed one."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Наименование", "Количество", "Ед."])
    sheet.append(["Сахар", "=1+1", "кг"])
    buffer = BytesIO()
    workbook.save(buffer)

    result = ExcelPurchaseListParser().parse_file(buffer.getvalue())
    assert result.items == []
    assert result.errors


def test_row_and_item_limits_are_enforced() -> None:
    rows: list[list[object]] = [["Наименование", "Количество", "Ед."]]
    rows += [[f"Товар {i}", 1, "шт"] for i in range(20)]
    parser = ExcelPurchaseListParser(max_items=5)
    result = parser.parse_file(build(rows))
    assert len(result.items) == 5
    assert any("слишком много строк" in error.reason for error in result.errors)

    capped = ExcelPurchaseListParser(max_rows=3).parse_file(build(rows))
    assert len(capped.items) <= 2


def test_long_names_are_clipped() -> None:
    parser = ExcelPurchaseListParser(max_name_length=10)
    content = build([["Наименование", "Количество", "Ед."], ["Т" * 200, 1, "шт"]])
    result = parser.parse_file(content)
    assert len(result.items[0].name) <= 10


# --- template round-trip ----------------------------------------------------
def test_generated_template_parses_back(parser: ExcelPurchaseListParser) -> None:
    template = build_items_template()
    assert template.filename.endswith(".xlsx")

    result = parser.parse_file(template.content)
    assert result.errors == []
    assert [item.name for item in result.items] == ["Сахар", "Масло", "Яйца"]
    assert result.items[1].quantity == Decimal("5.5")
    assert result.items[1].comment == "подсолнечное"
