"""Status transition rules for procurements and purchase requests."""

from __future__ import annotations

from app.domain.exceptions import InvalidStatusTransitionError
from app.models.enums import (
    PROCUREMENT_STATUS_LABELS,
    REQUEST_STATUS_LABELS,
    ProcurementStatus,
    PurchaseRequestStatus,
)

PROCUREMENT_TRANSITIONS: dict[ProcurementStatus, frozenset[ProcurementStatus]] = {
    ProcurementStatus.DRAFT: frozenset({ProcurementStatus.OPEN, ProcurementStatus.CANCELLED}),
    ProcurementStatus.OPEN: frozenset({ProcurementStatus.CLOSED, ProcurementStatus.CANCELLED}),
    # Reopening a closed procurement is deliberately allowed: an employee may
    # need to extend the deadline after closing it too early.
    ProcurementStatus.CLOSED: frozenset(
        {ProcurementStatus.COMPLETED, ProcurementStatus.OPEN, ProcurementStatus.CANCELLED}
    ),
    ProcurementStatus.COMPLETED: frozenset(),
    ProcurementStatus.CANCELLED: frozenset(),
}

REQUEST_TRANSITIONS: dict[PurchaseRequestStatus, frozenset[PurchaseRequestStatus]] = {
    PurchaseRequestStatus.DRAFT: frozenset(
        {PurchaseRequestStatus.SUBMITTED, PurchaseRequestStatus.CANCELLED}
    ),
    PurchaseRequestStatus.SUBMITTED: frozenset(
        {
            PurchaseRequestStatus.VIEWED,
            PurchaseRequestStatus.IN_PROGRESS,
            PurchaseRequestStatus.COMPLETED,
            PurchaseRequestStatus.REJECTED,
            PurchaseRequestStatus.CANCELLED,
        }
    ),
    PurchaseRequestStatus.VIEWED: frozenset(
        {
            PurchaseRequestStatus.IN_PROGRESS,
            PurchaseRequestStatus.COMPLETED,
            PurchaseRequestStatus.REJECTED,
            PurchaseRequestStatus.CANCELLED,
        }
    ),
    PurchaseRequestStatus.IN_PROGRESS: frozenset(
        {
            PurchaseRequestStatus.COMPLETED,
            PurchaseRequestStatus.REJECTED,
            PurchaseRequestStatus.CANCELLED,
        }
    ),
    PurchaseRequestStatus.COMPLETED: frozenset(),
    PurchaseRequestStatus.REJECTED: frozenset({PurchaseRequestStatus.IN_PROGRESS}),
    PurchaseRequestStatus.CANCELLED: frozenset(),
}

#: Statuses an employee may set from the request card.
EMPLOYEE_SETTABLE_REQUEST_STATUSES: tuple[PurchaseRequestStatus, ...] = (
    PurchaseRequestStatus.VIEWED,
    PurchaseRequestStatus.IN_PROGRESS,
    PurchaseRequestStatus.COMPLETED,
    PurchaseRequestStatus.REJECTED,
)


def can_transition_procurement(current: ProcurementStatus, new: ProcurementStatus) -> bool:
    return new in PROCUREMENT_TRANSITIONS.get(current, frozenset())


def ensure_procurement_transition(current: ProcurementStatus, new: ProcurementStatus) -> None:
    if not can_transition_procurement(current, new):
        raise InvalidStatusTransitionError(
            f"Нельзя перевести закупку из статуса «{PROCUREMENT_STATUS_LABELS[current]}» "
            f"в «{PROCUREMENT_STATUS_LABELS[new]}»."
        )


def can_transition_request(
    current: PurchaseRequestStatus, new: PurchaseRequestStatus
) -> bool:
    return new in REQUEST_TRANSITIONS.get(current, frozenset())


def ensure_request_transition(current: PurchaseRequestStatus, new: PurchaseRequestStatus) -> None:
    if not can_transition_request(current, new):
        raise InvalidStatusTransitionError(
            f"Нельзя перевести заявку из статуса «{REQUEST_STATUS_LABELS[current]}» "
            f"в «{REQUEST_STATUS_LABELS[new]}»."
        )
