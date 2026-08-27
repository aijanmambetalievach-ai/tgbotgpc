"""RBAC matrix and status-transition rules (pure logic, no database)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.domain.exceptions import InvalidStatusTransitionError, PermissionDeniedError
from app.domain.permissions import Permission, has_permission, require_any, require_permission
from app.domain.transitions import (
    can_transition_procurement,
    can_transition_request,
    ensure_procurement_transition,
    ensure_request_transition,
)
from app.models.enums import ProcurementStatus, PurchaseRequestStatus, UserRole
from tests.conftest import make_user

EMPLOYEE_ONLY = [
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
    Permission.EXPORT_PROCUREMENT,
    Permission.STATISTICS_VIEW,
]


@pytest.mark.parametrize("permission", EMPLOYEE_ONLY)
def test_purchaser_is_denied_administrative_permissions(permission: Permission) -> None:
    purchaser = make_user(2, UserRole.PURCHASER)
    assert has_permission(purchaser, permission) is False
    with pytest.raises(PermissionDeniedError):
        require_permission(purchaser, permission)


@pytest.mark.parametrize("permission", EMPLOYEE_ONLY)
def test_employee_is_granted_administrative_permissions(permission: Permission) -> None:
    employee = make_user(1, UserRole.TENDER_EMPLOYEE)
    assert has_permission(employee, permission) is True
    require_permission(employee, permission)


def test_purchaser_can_submit_and_view_own() -> None:
    purchaser = make_user(2, UserRole.PURCHASER)
    assert has_permission(purchaser, Permission.REQUEST_SUBMIT)
    assert has_permission(purchaser, Permission.REQUEST_VIEW_OWN)
    assert has_permission(purchaser, Permission.EXPORT_REQUEST)


def test_employee_cannot_submit_requests() -> None:
    employee = make_user(1, UserRole.TENDER_EMPLOYEE)
    assert has_permission(employee, Permission.REQUEST_SUBMIT) is False


def test_admin_has_every_permission() -> None:
    admin = make_user(3, UserRole.ADMIN)
    for permission in Permission:
        assert has_permission(admin, permission) is True


def test_blocked_user_loses_all_permissions() -> None:
    blocked = make_user(4, UserRole.TENDER_EMPLOYEE, is_active=False)
    for permission in Permission:
        assert has_permission(blocked, permission) is False
    with pytest.raises(PermissionDeniedError):
        require_permission(blocked, Permission.PROCUREMENT_CREATE)


def test_revoked_user_loses_all_permissions() -> None:
    revoked = make_user(
        5, UserRole.PURCHASER, revoked_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    )
    assert has_permission(revoked, Permission.REQUEST_SUBMIT) is False


def test_require_any() -> None:
    purchaser = make_user(2, UserRole.PURCHASER)
    require_any(purchaser, Permission.REQUEST_VIEW_ALL, Permission.REQUEST_VIEW_OWN)
    with pytest.raises(PermissionDeniedError):
        require_any(purchaser, Permission.USER_MANAGE, Permission.STATISTICS_VIEW)


# --- procurement transitions ------------------------------------------------
@pytest.mark.parametrize(
    ("current", "new"),
    [
        (ProcurementStatus.DRAFT, ProcurementStatus.OPEN),
        (ProcurementStatus.DRAFT, ProcurementStatus.CANCELLED),
        (ProcurementStatus.OPEN, ProcurementStatus.CLOSED),
        (ProcurementStatus.OPEN, ProcurementStatus.CANCELLED),
        (ProcurementStatus.CLOSED, ProcurementStatus.COMPLETED),
        (ProcurementStatus.CLOSED, ProcurementStatus.OPEN),
    ],
)
def test_allowed_procurement_transitions(
    current: ProcurementStatus, new: ProcurementStatus
) -> None:
    assert can_transition_procurement(current, new)
    ensure_procurement_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (ProcurementStatus.DRAFT, ProcurementStatus.CLOSED),
        (ProcurementStatus.DRAFT, ProcurementStatus.COMPLETED),
        (ProcurementStatus.OPEN, ProcurementStatus.COMPLETED),
        (ProcurementStatus.COMPLETED, ProcurementStatus.OPEN),
        (ProcurementStatus.CANCELLED, ProcurementStatus.OPEN),
        (ProcurementStatus.CANCELLED, ProcurementStatus.COMPLETED),
    ],
)
def test_forbidden_procurement_transitions(
    current: ProcurementStatus, new: ProcurementStatus
) -> None:
    assert not can_transition_procurement(current, new)
    with pytest.raises(InvalidStatusTransitionError):
        ensure_procurement_transition(current, new)


# --- request transitions ----------------------------------------------------
@pytest.mark.parametrize(
    ("current", "new"),
    [
        (PurchaseRequestStatus.DRAFT, PurchaseRequestStatus.SUBMITTED),
        (PurchaseRequestStatus.SUBMITTED, PurchaseRequestStatus.VIEWED),
        (PurchaseRequestStatus.SUBMITTED, PurchaseRequestStatus.IN_PROGRESS),
        (PurchaseRequestStatus.SUBMITTED, PurchaseRequestStatus.REJECTED),
        (PurchaseRequestStatus.VIEWED, PurchaseRequestStatus.IN_PROGRESS),
        (PurchaseRequestStatus.IN_PROGRESS, PurchaseRequestStatus.COMPLETED),
    ],
)
def test_allowed_request_transitions(
    current: PurchaseRequestStatus, new: PurchaseRequestStatus
) -> None:
    assert can_transition_request(current, new)
    ensure_request_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (PurchaseRequestStatus.DRAFT, PurchaseRequestStatus.COMPLETED),
        (PurchaseRequestStatus.DRAFT, PurchaseRequestStatus.VIEWED),
        (PurchaseRequestStatus.COMPLETED, PurchaseRequestStatus.IN_PROGRESS),
        (PurchaseRequestStatus.COMPLETED, PurchaseRequestStatus.DRAFT),
        (PurchaseRequestStatus.CANCELLED, PurchaseRequestStatus.SUBMITTED),
        (PurchaseRequestStatus.SUBMITTED, PurchaseRequestStatus.DRAFT),
    ],
)
def test_forbidden_request_transitions(
    current: PurchaseRequestStatus, new: PurchaseRequestStatus
) -> None:
    assert not can_transition_request(current, new)
    with pytest.raises(InvalidStatusTransitionError):
        ensure_request_transition(current, new)
