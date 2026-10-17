"""Pure domain rules: quiz format, phone numbers, text safety, status machine."""

from __future__ import annotations

import pytest

from app.domain.exceptions import InvalidStatusTransitionError, ValidationError
from app.domain.quiz import parse_question
from app.domain.text import html_to_plain, normalize_phone, sanitize_excel_cell
from app.domain.transitions import can_transition, ensure_transition
from app.models.enums import CATEGORY_AUDIENCES, ApplicationStatus, Audience, ClientCategory

S = ApplicationStatus


# --- quiz ------------------------------------------------------------------------
def test_quiz_question_is_parsed() -> None:
    parsed = parse_question(
        "Сколько членов должно быть в закупочной комиссии?\n"
        "- Четное число\n"
        "+ Нечетное число, не менее трех\n"
        "- Любое"
    )
    assert parsed.question == "Сколько членов должно быть в закупочной комиссии?"
    assert parsed.options == ("Четное число", "Нечетное число, не менее трех", "Любое")
    assert parsed.correct_option == 1


def test_quiz_question_may_span_lines_and_use_dashes() -> None:
    parsed = parse_question(
        "Что такое ГОПП?\nВыберите один ответ\n– Гарантия\n+ Гарантийное обеспечение"
    )
    assert parsed.question == "Что такое ГОПП? Выберите один ответ"
    assert parsed.correct_option == 1


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("Вопрос?\n- один\n- два", "ровно один"),
        ("Вопрос?\n+ один\n+ два", "ровно один"),
        ("Вопрос?\n+ один", "от 2 до 6"),
        ("", "текст вопроса"),
        ("Вопрос?\n+ да\nпосторонняя строка\n- нет", "в начале"),
    ],
)
def test_quiz_question_errors_are_explained(raw: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_question(raw)


# --- phones ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0555 123 456", "+996555123456"),
        ("555123456", "+996555123456"),
        ("+996 (555) 12-34-56", "+996555123456"),
        ("996555123456", "+996555123456"),
        ("+7 701 123 45 67", "+77011234567"),
        ("12345", None),
        ("позвоните мне", None),
        ("", None),
    ],
)
def test_phone_normalisation(raw: str, expected: str | None) -> None:
    assert normalize_phone(raw) == expected


# --- text safety -------------------------------------------------------------------
def test_html_to_plain_strips_tags_and_unescapes() -> None:
    assert html_to_plain("<b>Жирный</b> &amp; <a href='x'>ссылка</a>") == "Жирный & ссылка"


@pytest.mark.parametrize("value", ["=HYPERLINK(1)", "+1", "-2", "@cmd"])
def test_excel_formula_injection_is_neutralised(value: str) -> None:
    assert sanitize_excel_cell(value) == "'" + value


# --- status machine ------------------------------------------------------------------
def test_staff_transitions() -> None:
    assert can_transition(S.NEW, S.IN_PROGRESS, by_staff=True)
    assert can_transition(S.NEW, S.DONE, by_staff=True)
    assert can_transition(S.IN_PROGRESS, S.REJECTED, by_staff=True)
    assert not can_transition(S.DONE, S.IN_PROGRESS, by_staff=True)
    assert not can_transition(S.NEW, S.CANCELLED, by_staff=True)


def test_client_can_only_cancel_open_applications() -> None:
    assert can_transition(S.NEW, S.CANCELLED, by_staff=False)
    assert can_transition(S.IN_PROGRESS, S.CANCELLED, by_staff=False)
    assert not can_transition(S.NEW, S.DONE, by_staff=False)
    with pytest.raises(InvalidStatusTransitionError):
        ensure_transition(S.DONE, S.CANCELLED, by_staff=False)


def test_category_audiences() -> None:
    assert Audience.SUPPLIER not in CATEGORY_AUDIENCES[ClientCategory.PURCHASER]
    assert Audience.ALL in CATEGORY_AUDIENCES[ClientCategory.SUPPLIER]
    # Beginners and clients who skipped the question see everything.
    assert set(CATEGORY_AUDIENCES[ClientCategory.BEGINNER]) == set(Audience)
    assert set(CATEGORY_AUDIENCES[None]) == set(Audience)
