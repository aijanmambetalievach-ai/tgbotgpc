"""Deterministic parser for the "⚡ Быстро текстом" procurement flow.

Two input shapes are supported:

*labelled* ::

    Название: Канцелярские товары
    Срок: 30.08.2026 17:00
    Описание: Необходимо собрать потребность подразделений.

*free-form* ::

    Канцелярские товары
    до 30 августа 17:00
    Собрать потребность всех отделов

The result is **always** shown to the employee for confirmation — nothing is
published automatically.
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from app.domain.text import collapse_whitespace, normalize_unicode, strip_edge_punctuation
from app.domain.timeutils import parse_deadline
from app.parsers.base import ParsedProcurement, ParseError

DEFAULT_MAX_TITLE_LENGTH = 300
DEFAULT_MAX_DESCRIPTION_LENGTH = 5000

_LABELS: dict[str, tuple[str, ...]] = {
    "title": ("название", "наименование", "тема", "заголовок", "закупка", "title"),
    "deadline": ("срок", "срок подачи", "дедлайн", "крайний срок", "до", "deadline"),
    "description": ("описание", "комментарий", "детали", "примечание", "description"),
}
_LABEL_LOOKUP: dict[str, str] = {
    alias: field for field, aliases in _LABELS.items() for alias in aliases
}
_LABEL_LINE = re.compile(r"^\s*(?P<label>[A-Za-zА-Яа-яЁё \-]{2,20})\s*:\s*(?P<value>.*)$")

# A line that looks like it carries a date.
_DATE_HINT = re.compile(
    r"(\b\d{1,2}[.\-/]\d{1,2}([.\-/]\d{2,4})?\b)"
    r"|(\b\d{4}-\d{1,2}-\d{1,2}\b)"
    r"|(\b\d{1,2}\s+[а-яё]{3,8}\b)",
    re.IGNORECASE,
)
_DEADLINE_PREFIX = re.compile(r"^\s*(до|срок|дедлайн|крайний срок)\b[\s:—–-]*", re.IGNORECASE)

REASON_NO_TITLE = "не удалось определить название закупки"
REASON_NO_DEADLINE = "не удалось определить срок подачи заявок"


class RegexProcurementParser:
    """Implementation of :class:`ProcurementParserProtocol` without any LLM."""

    def __init__(
        self,
        timezone: ZoneInfo,
        default_deadline_time: dt.time,
        max_title_length: int = DEFAULT_MAX_TITLE_LENGTH,
        max_description_length: int = DEFAULT_MAX_DESCRIPTION_LENGTH,
    ) -> None:
        self.timezone = timezone
        self.default_deadline_time = default_deadline_time
        self.max_title_length = max_title_length
        self.max_description_length = max_description_length

    def parse(self, raw_text: str, now: dt.datetime | None = None) -> ParsedProcurement:
        text = collapse_whitespace(normalize_unicode(raw_text or ""))
        lines = [line for line in (part.strip() for part in text.split("\n")) if line]
        if not lines:
            return ParsedProcurement(
                title=None,
                description=None,
                deadline=None,
                deadline_time_was_explicit=False,
                errors=[ParseError(line="", reason=REASON_NO_TITLE)],
            )

        title, description_parts, deadline_text, leftovers = self._split_labelled(lines)

        title, description_parts, deadline_text = self._split_freeform(
            leftovers, title, description_parts, deadline_text
        )

        errors: list[ParseError] = []

        parsed_deadline = None
        if deadline_text:
            parsed_deadline = parse_deadline(
                deadline_text, self.timezone, self.default_deadline_time, now=now
            )
            if parsed_deadline is None:
                errors.append(ParseError(line=deadline_text, reason=REASON_NO_DEADLINE))
        else:
            errors.append(ParseError(line="", reason=REASON_NO_DEADLINE))

        if title:
            title = strip_edge_punctuation(title)[: self.max_title_length].strip()
        if not title:
            title = None
            errors.append(ParseError(line=lines[0], reason=REASON_NO_TITLE))

        joined = "\n".join(part for part in description_parts if part).strip()
        description: str | None = joined[: self.max_description_length] or None

        return ParsedProcurement(
            title=title,
            description=description,
            deadline=parsed_deadline.value if parsed_deadline else None,
            deadline_time_was_explicit=(
                parsed_deadline.time_was_explicit if parsed_deadline else False
            ),
            errors=errors,
        )

    # -- internals ---------------------------------------------------------
    def _split_labelled(
        self, lines: list[str]
    ) -> tuple[str | None, list[str], str | None, list[str]]:
        """Extract ``Label: value`` lines; return the rest untouched."""
        title: str | None = None
        deadline_text: str | None = None
        description_parts: list[str] = []
        leftovers: list[str] = []
        current_field: str | None = None

        for line in lines:
            match = _LABEL_LINE.match(line)
            field = None
            value = line
            if match:
                label = match.group("label").strip().lower().replace("ё", "е")
                field = _LABEL_LOOKUP.get(label)
                value = match.group("value").strip()

            if field == "title" and title is None:
                title, current_field = value, "title"
            elif field == "deadline" and deadline_text is None:
                deadline_text, current_field = value or line, "deadline"
            elif field == "description":
                description_parts.append(value)
                current_field = "description"
            elif current_field == "description" and not match:
                # continuation of a multi-line description
                description_parts.append(line)
            else:
                leftovers.append(line)
                current_field = None

        return title, description_parts, deadline_text, leftovers

    def _split_freeform(
        self,
        leftovers: list[str],
        title: str | None,
        description_parts: list[str],
        deadline_text: str | None,
    ) -> tuple[str | None, list[str], str | None]:
        """Interpret unlabelled lines: title first, a date line, the rest is description."""
        remaining: list[str] = []
        for line in leftovers:
            if deadline_text is None and self._looks_like_deadline(line):
                deadline_text = _DEADLINE_PREFIX.sub("", line).strip() or line
                continue
            remaining.append(line)

        if title is None and remaining:
            title = remaining.pop(0)

        description_parts = [*description_parts, *remaining]
        return title, description_parts, deadline_text

    @staticmethod
    def _looks_like_deadline(line: str) -> bool:
        if not _DATE_HINT.search(line):
            return False
        # Long sentences that merely mention a date are not deadlines.
        return len(line) <= 60 or bool(_DEADLINE_PREFIX.match(line))
