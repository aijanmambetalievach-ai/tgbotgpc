"""Deterministic parser for purchaser item lists.

Design rules:

* it never invents data — an ambiguous line becomes a :class:`ParseError`
  that the user is asked to fix;
* quantities are :class:`~decimal.Decimal`, never ``float``;
* units are normalised through :mod:`app.domain.units`.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.domain.text import (
    collapse_whitespace,
    humanize_name,
    normalize_unicode,
    strip_edge_punctuation,
)
from app.domain.units import alias_pattern, normalize_unit
from app.parsers.base import ParsedItem, ParseError, ParseResult

DEFAULT_MAX_ITEMS = 500
DEFAULT_MAX_NAME_LENGTH = 300

_ALIAS_PATTERN = alias_pattern()

# Leading enumeration: "1." / "1)" / "1 -" / "1 "
_LEADING_INDEX = re.compile(r"^\s*(?P<index>\d{1,4})\s*(?P<sep>[.)\]:\-–—]+|\s)\s*")

# Noise words used around a quantity ("количество", "кол-во", "в количестве").
_NOISE = re.compile(
    r"\b(?:в\s+)?(?:кол[\s\-–—]*в[оа]?|количеств[оаеу]м?|колич|кол)\b\.?",
    re.IGNORECASE,
)

# "... 50 кг" at the very end of the line.
_TRAILING_QTY = re.compile(
    r"(?P<qty>\d+(?:[.,]\d+)?)\s*(?P<unit>[^\W\d_]{1,14}[²³]?|[²³])?\s*$",
    re.UNICODE,
)

# "50 кг" anywhere, but only when followed by a *known* unit.
_ANY_QTY_UNIT = re.compile(
    rf"(?P<qty>\d+(?:[.,]\d+)?)\s*(?P<unit>{_ALIAS_PATTERN})(?![^\W\d_])",
    re.IGNORECASE | re.UNICODE,
)

_HAS_DIGIT = re.compile(r"\d")
_LINE_SPLIT = re.compile(r"[\n;]+")

REASON_NO_QUANTITY = "не удалось определить количество"
REASON_NO_UNIT = "не указана единица измерения"
REASON_UNKNOWN_UNIT = "неизвестная единица измерения"
REASON_NO_NAME = "не указано наименование товара"
REASON_BAD_QUANTITY = "количество должно быть больше нуля"
REASON_TOO_MANY = "превышено максимальное количество позиций"


class RegexPurchaseListParser:
    """Regex/heuristics based implementation of :class:`PurchaseListParserProtocol`."""

    def __init__(
        self,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_name_length: int = DEFAULT_MAX_NAME_LENGTH,
    ) -> None:
        self.max_items = max_items
        self.max_name_length = max_name_length

    # -- public API --------------------------------------------------------
    def parse(self, raw_text: str) -> ParseResult:
        items: list[ParsedItem] = []
        errors: list[ParseError] = []

        for raw_line in self._iter_lines(raw_text):
            if len(items) >= self.max_items:
                errors.append(ParseError(line=raw_line, reason=REASON_TOO_MANY))
                break
            parsed, error = self.parse_line(raw_line)
            if parsed is not None:
                items.append(parsed)
            elif error is not None:
                errors.append(error)

        return ParseResult(items=items, errors=errors)

    def parse_line(self, raw_line: str) -> tuple[ParsedItem | None, ParseError | None]:
        """Parse a single line. Exposed so the UI can re-parse one fixed row."""
        source = collapse_whitespace(normalize_unicode(raw_line))
        if not source:
            return None, None

        working = self._strip_leading_index(source)
        working = _NOISE.sub(" ", working)
        working = collapse_whitespace(working)

        if not _HAS_DIGIT.search(working):
            return None, ParseError(line=source, reason=REASON_NO_QUANTITY)

        extracted = self._extract_quantity(working)
        if extracted is None:
            return None, ParseError(line=source, reason=REASON_NO_QUANTITY)

        quantity_text, unit_text, name_part, confidence = extracted

        if unit_text is None or not unit_text.strip():
            return None, ParseError(line=source, reason=REASON_NO_UNIT)

        unit = normalize_unit(unit_text)
        if unit is None:
            return None, ParseError(
                line=source, reason=f"{REASON_UNKNOWN_UNIT}: «{unit_text.strip()}»"
            )

        try:
            quantity = Decimal(quantity_text.replace(",", ".").replace(" ", ""))
        except InvalidOperation:
            return None, ParseError(line=source, reason=REASON_NO_QUANTITY)
        if quantity <= 0:
            return None, ParseError(line=source, reason=REASON_BAD_QUANTITY)

        name = humanize_name(strip_edge_punctuation(name_part))
        if not name:
            return None, ParseError(line=source, reason=REASON_NO_NAME)
        if len(name) > self.max_name_length:
            name = name[: self.max_name_length].rstrip()

        if _HAS_DIGIT.search(name):
            confidence = min(confidence, 0.8)

        return (
            ParsedItem(
                name=name,
                quantity=quantity,
                unit=unit,
                source_text=source,
                confidence=round(confidence, 2),
            ),
            None,
        )

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _iter_lines(raw_text: str) -> list[str]:
        return [line for line in (part.strip() for part in _LINE_SPLIT.split(raw_text)) if line]

    @staticmethod
    def _strip_leading_index(line: str) -> str:
        """Drop "1." / "1)" style numbering, but never the quantity itself."""
        match = _LEADING_INDEX.match(line)
        if not match:
            return line
        remainder = line[match.end() :]
        separator = match.group("sep").strip()
        if separator:
            # "1." / "1)" — unambiguous enumeration.
            return remainder or line
        # "1 сахар 50 кг" — only an index when a quantity remains afterwards.
        if _HAS_DIGIT.search(remainder):
            return remainder
        return line

    def _extract_quantity(self, working: str) -> tuple[str, str | None, str, float] | None:
        """Return ``(quantity_text, unit_text, name_part, confidence)``."""
        trailing = _TRAILING_QTY.search(working)
        if trailing:
            unit_text = trailing.group("unit")
            if unit_text and normalize_unit(unit_text):
                return (
                    trailing.group("qty"),
                    unit_text,
                    working[: trailing.start()],
                    1.0,
                )

        # Quantity + known unit somewhere in the middle ("Сахар 50 кг белый").
        matches = list(_ANY_QTY_UNIT.finditer(working))
        if matches:
            match = matches[-1]
            name_part = (working[: match.start()] + " " + working[match.end() :]).strip()
            return match.group("qty"), match.group("unit"), name_part, 0.85

        if trailing:
            # A number was found but the unit is missing or unrecognised.
            return (
                trailing.group("qty"),
                trailing.group("unit"),
                working[: trailing.start()],
                0.5,
            )
        return None


def get_default_purchase_list_parser(
    max_items: int = DEFAULT_MAX_ITEMS, max_name_length: int = DEFAULT_MAX_NAME_LENGTH
) -> RegexPurchaseListParser:
    return RegexPurchaseListParser(max_items=max_items, max_name_length=max_name_length)
