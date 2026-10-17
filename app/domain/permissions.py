"""Access control.

Enforced in the service layer — hiding a button in Telegram is never treated
as a security control. There are only two roles, so the rules are simple:
administrators manage everything, clients only ever touch their own records.
"""

from __future__ import annotations

from app.domain.exceptions import PermissionDeniedError
from app.models.user import User

BLOCKED_MESSAGE = "Ваш доступ к боту приостановлен."


def require_active(user: User) -> None:
    if not user.can_use_bot:
        raise PermissionDeniedError(BLOCKED_MESSAGE)


def require_admin(user: User) -> None:
    """Raise :class:`PermissionDeniedError` unless ``user`` is an active admin."""
    require_active(user)
    if not user.is_admin:
        raise PermissionDeniedError()


def require_owner_or_admin(user: User, owner_id: int) -> None:
    require_active(user)
    if not user.is_admin and user.id != owner_id:
        raise PermissionDeniedError()
