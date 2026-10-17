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


class DuplicateApplicationError(DomainError):
    default_message = "Вы уже записаны — заявка рассматривается."


class ApplicationClosedError(DomainError):
    default_message = "Эта заявка уже закрыта."


class ContentUnavailableError(DomainError):
    default_message = "Этот материал сейчас недоступен."
