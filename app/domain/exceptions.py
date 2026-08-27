"""Domain-level errors.

Every error carries a Russian, user-safe message: handlers can show
``exc.message`` directly without leaking internals.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for expected business rule violations."""

    default_message = "Операция невозможна."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class PermissionDeniedError(DomainError):
    default_message = "У вас нет прав для выполнения этого действия."


class NotFoundError(DomainError):
    default_message = "Запись не найдена."


class ValidationError(DomainError):
    default_message = "Некорректные данные."


class InvalidStatusTransitionError(DomainError):
    default_message = "Недопустимое изменение статуса."


class DeadlineExpiredError(DomainError):
    default_message = "Срок подачи заявок по этой закупке уже истек."


class NotAParticipantError(PermissionDeniedError):
    default_message = "Эта закупка вам недоступна."


class ProcurementNotAcceptingError(DomainError):
    default_message = "Эта закупка сейчас не принимает заявки."


class DuplicateSubmissionError(DomainError):
    default_message = "Заявка по этой закупке уже отправлена."


class LimitExceededError(DomainError):
    default_message = "Превышено допустимое ограничение."


class InviteError(DomainError):
    default_message = "Приглашение недействительно или уже использовано."
