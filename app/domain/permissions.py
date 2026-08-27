"""Role-based access control.

RBAC is enforced here and called from the service layer — hiding a button in
Telegram is never treated as a security control.
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.exceptions import PermissionDeniedError
from app.models.enums import UserRole
from app.models.user import User


class Permission(StrEnum):
    """Discrete capabilities the system checks for."""

    # User management
    USER_MANAGE = "user.manage"
    USER_VIEW = "user.view"

    # Procurements
    PROCUREMENT_CREATE = "procurement.create"
    PROCUREMENT_UPDATE = "procurement.update"
    PROCUREMENT_PUBLISH = "procurement.publish"
    PROCUREMENT_CLOSE = "procurement.close"
    PROCUREMENT_CANCEL = "procurement.cancel"
    PROCUREMENT_COMPLETE = "procurement.complete"
    PROCUREMENT_VIEW_ALL = "procurement.view_all"
    PROCUREMENT_EXTEND_DEADLINE = "procurement.extend_deadline"
    PROCUREMENT_REMIND = "procurement.remind"

    # Purchase requests
    REQUEST_SUBMIT = "request.submit"
    REQUEST_VIEW_OWN = "request.view_own"
    REQUEST_VIEW_ALL = "request.view_all"
    REQUEST_CHANGE_STATUS = "request.change_status"

    # Exports & analytics
    EXPORT_REQUEST = "export.request"
    EXPORT_PROCUREMENT = "export.procurement"
    STATISTICS_VIEW = "statistics.view"


_EMPLOYEE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.USER_MANAGE,
        Permission.USER_VIEW,
        Permission.PROCUREMENT_CREATE,
        Permission.PROCUREMENT_UPDATE,
        Permission.PROCUREMENT_PUBLISH,
        Permission.PROCUREMENT_CLOSE,
        Permission.PROCUREMENT_CANCEL,
        Permission.PROCUREMENT_COMPLETE,
        Permission.PROCUREMENT_VIEW_ALL,
        Permission.PROCUREMENT_EXTEND_DEADLINE,
        Permission.PROCUREMENT_REMIND,
        Permission.REQUEST_VIEW_ALL,
        Permission.REQUEST_CHANGE_STATUS,
        Permission.EXPORT_REQUEST,
        Permission.EXPORT_PROCUREMENT,
        Permission.STATISTICS_VIEW,
    }
)

_PURCHASER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.REQUEST_SUBMIT,
        Permission.REQUEST_VIEW_OWN,
        Permission.EXPORT_REQUEST,
    }
)

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.ADMIN: frozenset(Permission),
    UserRole.TENDER_EMPLOYEE: _EMPLOYEE_PERMISSIONS,
    UserRole.PURCHASER: _PURCHASER_PERMISSIONS,
}


def permissions_for(role: UserRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(user: User, permission: Permission) -> bool:
    """A revoked or blocked user has no permissions at all."""
    if not user.can_use_bot:
        return False
    return permission in permissions_for(user.role)


def require_permission(user: User, permission: Permission) -> None:
    """Raise :class:`PermissionDeniedError` unless ``user`` holds ``permission``."""
    if not user.can_use_bot:
        raise PermissionDeniedError("Ваш доступ к системе приостановлен.")
    if permission not in permissions_for(user.role):
        raise PermissionDeniedError()


def require_any(user: User, *permissions: Permission) -> None:
    if not user.can_use_bot:
        raise PermissionDeniedError("Ваш доступ к системе приостановлен.")
    granted = permissions_for(user.role)
    if not any(permission in granted for permission in permissions):
        raise PermissionDeniedError()
