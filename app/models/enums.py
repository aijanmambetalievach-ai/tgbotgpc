"""Domain enumerations shared by models, services and the UI layer."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """System roles.

    ``ADMIN`` is a superset of ``TENDER_EMPLOYEE`` reserved for system
    maintenance; the product currently exposes only the two business roles.
    """

    ADMIN = "ADMIN"
    TENDER_EMPLOYEE = "TENDER_EMPLOYEE"
    PURCHASER = "PURCHASER"


class ProcurementStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class PurchaseRequestStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VIEWED = "VIEWED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ParticipantSelectionMode(StrEnum):
    """How the participant list was chosen when the procurement was created."""

    ALL_ACTIVE = "ALL_ACTIVE"
    MANUAL = "MANUAL"


PROCUREMENT_STATUS_LABELS: dict[ProcurementStatus, str] = {
    ProcurementStatus.DRAFT: "Черновик",
    ProcurementStatus.OPEN: "Активна",
    ProcurementStatus.CLOSED: "Закрыта",
    ProcurementStatus.CANCELLED: "Отменена",
    ProcurementStatus.COMPLETED: "Завершена",
}

PROCUREMENT_STATUS_ICONS: dict[ProcurementStatus, str] = {
    ProcurementStatus.DRAFT: "📝",
    ProcurementStatus.OPEN: "🟢",
    ProcurementStatus.CLOSED: "🔒",
    ProcurementStatus.CANCELLED: "❌",
    ProcurementStatus.COMPLETED: "✅",
}

REQUEST_STATUS_LABELS: dict[PurchaseRequestStatus, str] = {
    PurchaseRequestStatus.DRAFT: "Черновик",
    PurchaseRequestStatus.SUBMITTED: "Отправлена",
    PurchaseRequestStatus.VIEWED: "Просмотрена",
    PurchaseRequestStatus.IN_PROGRESS: "В работе",
    PurchaseRequestStatus.COMPLETED: "Завершена",
    PurchaseRequestStatus.REJECTED: "Отклонена",
    PurchaseRequestStatus.CANCELLED: "Отменена",
}

REQUEST_STATUS_ICONS: dict[PurchaseRequestStatus, str] = {
    PurchaseRequestStatus.DRAFT: "📝",
    PurchaseRequestStatus.SUBMITTED: "📥",
    PurchaseRequestStatus.VIEWED: "👀",
    PurchaseRequestStatus.IN_PROGRESS: "🟡",
    PurchaseRequestStatus.COMPLETED: "✅",
    PurchaseRequestStatus.REJECTED: "❌",
    PurchaseRequestStatus.CANCELLED: "🚫",
}

ROLE_LABELS: dict[UserRole, str] = {
    UserRole.ADMIN: "Администратор",
    UserRole.TENDER_EMPLOYEE: "Сотрудник тендерного отдела",
    UserRole.PURCHASER: "Закупщик",
}


def procurement_status_label(status: ProcurementStatus) -> str:
    return PROCUREMENT_STATUS_LABELS[status]


def request_status_label(status: PurchaseRequestStatus) -> str:
    return REQUEST_STATUS_LABELS[status]
