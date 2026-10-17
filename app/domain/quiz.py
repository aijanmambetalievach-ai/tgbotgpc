"""Parsing the admin's plain-text quiz question format.

The admin writes one question per message::

    Сколько членов должно быть в закупочной комиссии?
    - Четное число
    + Нечетное число, не менее трех
    - Любое

The first non-option line is the question; ``+`` marks the correct answer and
``-`` marks the wrong ones. Exactly one correct answer, 2–6 options in total.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.exceptions import ValidationError
from app.domain.text import sanitize_text

MIN_OPTIONS = 2
MAX_OPTIONS = 6
MAX_QUESTION_LENGTH = 500
#: Telegram inline buttons are cramped; long options are shown in the message.
MAX_OPTION_LENGTH = 200

_OPTION = re.compile(r"^\s*(?P<mark>[+\-–—•*])\s*(?P<text>.+?)\s*$")


@dataclass(frozen=True, slots=True)
class ParsedQuestion:
    question: str
    options: tuple[str, ...]
    correct_option: int


def parse_question(raw: str) -> ParsedQuestion:
    question_lines: list[str] = []
    options: list[str] = []
    correct: list[int] = []

    for line in (raw or "").splitlines():
        if not line.strip():
            continue
        match = _OPTION.match(line)
        if match and (options or question_lines):
            text = sanitize_text(match.group("text"), MAX_OPTION_LENGTH)
            if not text:
                continue
            if match.group("mark") == "+":
                correct.append(len(options))
            options.append(text)
        elif options:
            raise ValidationError(
                "Текст вопроса должен быть в начале, а варианты — после него, "
                "каждый с новой строки и со знаком «+» или «-»."
            )
        else:
            question_lines.append(line)

    question = sanitize_text(" ".join(question_lines), MAX_QUESTION_LENGTH)
    if not question:
        raise ValidationError("Не найден текст вопроса.")
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise ValidationError(
            f"Нужно от {MIN_OPTIONS} до {MAX_OPTIONS} вариантов ответа, "
            "каждый с новой строки и со знаком «+» или «-»."
        )
    if len(correct) != 1:
        raise ValidationError("Отметьте знаком «+» ровно один правильный вариант.")
    return ParsedQuestion(question=question, options=tuple(options), correct_option=correct[0])
