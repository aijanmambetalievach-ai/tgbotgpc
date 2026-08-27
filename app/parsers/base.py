"""Parser contracts and result value objects.

Business logic depends only on these protocols. The MVP ships deterministic
regex implementations; an ``LLMPurchaseListParser`` can be dropped in later
without touching services or handlers.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ParsedItem:
    """One recognised line of a purchase list."""

    name: str
    quantity: Decimal
    unit: str
    source_text: str
    confidence: float | None = None
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class ParseError:
    """One line the parser refused to guess."""

    line: str
    reason: str


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Outcome of parsing a purchase list."""

    items: list[ParsedItem] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.items) and not self.errors

    @property
    def has_items(self) -> bool:
        return bool(self.items)


@dataclass(frozen=True, slots=True)
class ParsedProcurement:
    """Outcome of parsing a free-form procurement announcement."""

    title: str | None
    description: str | None
    deadline: dt.datetime | None
    deadline_time_was_explicit: bool
    errors: list[ParseError] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return bool(self.title) and self.deadline is not None


@runtime_checkable
class PurchaseListParserProtocol(Protocol):
    """Turns free-form purchaser text into structured items."""

    def parse(self, raw_text: str) -> ParseResult: ...


@runtime_checkable
class PurchaseListFileParserProtocol(Protocol):
    """Turns an uploaded spreadsheet into the same structured items.

    Deliberately mirrors :class:`PurchaseListParserProtocol` so the preview,
    correction and submission flow is identical no matter how the purchaser
    supplied the list.
    """

    def parse_file(self, content: bytes) -> ParseResult: ...


@runtime_checkable
class ProcurementParserProtocol(Protocol):
    """Turns a free-form employee message into procurement fields."""

    def parse(self, raw_text: str, now: dt.datetime | None = None) -> ParsedProcurement: ...
