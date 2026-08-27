"""Parser tests — the acceptance examples from the specification and more."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.parsers.purchase_list_parser import (
    REASON_BAD_QUANTITY,
    REASON_NO_NAME,
    REASON_NO_QUANTITY,
    REASON_NO_UNIT,
    RegexPurchaseListParser,
)


@pytest.fixture
def parser() -> RegexPurchaseListParser:
    return RegexPurchaseListParser()


@pytest.mark.parametrize(
    ("line", "name", "quantity", "unit"),
    [
        ("Сахар 50 кг", "Сахар", Decimal("50"), "кг"),
        ("Сахар, 50кг", "Сахар", Decimal("50"), "кг"),
        ("1. Сахар количество 50 кг", "Сахар", Decimal("50"), "кг"),
        ("Сахар - 50 килограмм", "Сахар", Decimal("50"), "кг"),
        ("Сахар — 50 кг", "Сахар", Decimal("50"), "кг"),
        ("Масло 5.5 л", "Масло", Decimal("5.5"), "л"),
        ("Масло 5,5 литров", "Масло", Decimal("5.5"), "л"),
        ("Яйца 200 шт", "Яйца", Decimal("200"), "шт"),
        ("Яйца 200шт", "Яйца", Decimal("200"), "шт"),
        ("Бумага 20 пачек", "Бумага", Decimal("20"), "пач"),
        ("2 масло кол 60 литров", "Масло", Decimal("60"), "л"),
        ("1 сахар, количество 50кг", "Сахар", Decimal("50"), "кг"),
        ("Мука 100 килограмм", "Мука", Decimal("100"), "кг"),
        ("Молоко 100 л", "Молоко", Decimal("100"), "л"),
        ("Картофель 150 кг", "Картофель", Decimal("150"), "кг"),
        ("Кабель 25 м", "Кабель", Decimal("25"), "м"),
        ("Плитка 30 м2", "Плитка", Decimal("30"), "м²"),
        ("Бетон 4 м3", "Бетон", Decimal("4"), "м³"),
        ("Вода 12 бутылок", "Вода", Decimal("12"), "бут"),
        ("Крупа 3 мешка", "Крупа", Decimal("3"), "меш"),
    ],
)
def test_parses_single_line(
    parser: RegexPurchaseListParser,
    line: str,
    name: str,
    quantity: Decimal,
    unit: str,
) -> None:
    result = parser.parse(line)
    assert result.errors == []
    assert len(result.items) == 1
    item = result.items[0]
    assert item.name == name
    assert item.quantity == quantity
    assert isinstance(item.quantity, Decimal)
    assert item.unit == unit
    assert item.source_text


def test_parses_numbered_multiline_list(parser: RegexPurchaseListParser) -> None:
    text = "1. Сахар — 50 кг\n2. Масло — 60 л\n3. Мука — 100 кг\n4. Яйца — 200 шт"
    result = parser.parse(text)

    assert result.errors == []
    assert [item.name for item in result.items] == ["Сахар", "Масло", "Мука", "Яйца"]
    assert [item.unit for item in result.items] == ["кг", "л", "кг", "шт"]
    assert [str(item.quantity) for item in result.items] == ["50", "60", "100", "200"]


def test_parses_free_form_list(parser: RegexPurchaseListParser) -> None:
    text = "1 сахар, количество 50кг\n2 масло кол 60 литров\n3 мука 100 кг\n4 яйца 200шт"
    result = parser.parse(text)

    assert result.errors == []
    assert [item.name for item in result.items] == ["Сахар", "Масло", "Мука", "Яйца"]
    assert [item.unit for item in result.items] == ["кг", "л", "кг", "шт"]


def test_semicolons_split_items(parser: RegexPurchaseListParser) -> None:
    result = parser.parse("Сахар 50 кг; Масло 60 л")
    assert len(result.items) == 2


def test_decimal_precision_is_exact(parser: RegexPurchaseListParser) -> None:
    result = parser.parse("Масло 5,5 л")
    assert result.items[0].quantity == Decimal("5.5")
    # Never float: 0.1 + 0.2 style drift must be impossible.
    assert result.items[0].quantity * 3 == Decimal("16.5")


@pytest.mark.parametrize(
    ("line", "reason_fragment"),
    [
        ("Масло несколько больших бутылок", REASON_NO_QUANTITY),
        ("просто какой-то текст", REASON_NO_QUANTITY),
        ("Сахар 50", REASON_NO_UNIT),
        ("Сахар 0 кг", REASON_BAD_QUANTITY),
        ("50 кг", REASON_NO_NAME),
    ],
)
def test_malformed_lines_become_errors(
    parser: RegexPurchaseListParser, line: str, reason_fragment: str
) -> None:
    result = parser.parse(line)
    assert result.items == []
    assert len(result.errors) == 1
    assert reason_fragment in result.errors[0].reason
    assert result.errors[0].line == line


def test_unknown_unit_is_reported_not_guessed(parser: RegexPurchaseListParser) -> None:
    result = parser.parse("Бумага 500 листов")
    assert result.items == []
    assert "неизвестная единица измерения" in result.errors[0].reason


def test_mixed_valid_and_invalid_lines(parser: RegexPurchaseListParser) -> None:
    result = parser.parse("Сахар 50 кг\nМасло несколько бутылок\nМука 100 кг")
    assert [item.name for item in result.items] == ["Сахар", "Мука"]
    assert len(result.errors) == 1
    assert result.errors[0].line == "Масло несколько бутылок"


def test_blank_lines_are_ignored(parser: RegexPurchaseListParser) -> None:
    result = parser.parse("\n\nСахар 50 кг\n\n\nМука 100 кг\n")
    assert len(result.items) == 2
    assert result.errors == []


def test_max_items_limit_is_enforced() -> None:
    parser = RegexPurchaseListParser(max_items=2)
    result = parser.parse("А 1 кг\nБ 2 кг\nВ 3 кг")
    assert len(result.items) == 2
    assert any("максимальное количество" in error.reason for error in result.errors)


def test_long_names_are_truncated() -> None:
    parser = RegexPurchaseListParser(max_name_length=10)
    result = parser.parse(f"{'Товар' * 20} 5 кг")
    assert len(result.items[0].name) <= 10


def test_parse_line_returns_error_object(parser: RegexPurchaseListParser) -> None:
    parsed, error = parser.parse_line("Сахар 50")
    assert parsed is None
    assert error is not None and REASON_NO_UNIT in error.reason

    parsed, error = parser.parse_line("Сахар 50 кг")
    assert error is None
    assert parsed is not None and parsed.name == "Сахар"


def test_confidence_is_reported(parser: RegexPurchaseListParser) -> None:
    item = parser.parse("Сахар 50 кг").items[0]
    assert item.confidence is not None
    assert 0 < item.confidence <= 1
