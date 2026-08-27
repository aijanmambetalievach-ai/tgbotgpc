"""ORM models.

Importing this package registers every table on ``Base.metadata`` — Alembic's
env.py relies on that for autogenerate.
"""

from app.models.audit_log import AuditAction, AuditLog
from app.models.enums import (
    ParticipantSelectionMode,
    ProcurementStatus,
    PurchaseRequestStatus,
    UserRole,
)
from app.models.invite import Invite
from app.models.number_counter import NumberCounter, NumberScope
from app.models.procurement import Procurement
from app.models.procurement_participant import ProcurementParticipant
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_item import PurchaseRequestItem
from app.models.status_history import StatusHistory
from app.models.user import User

__all__ = [
    "AuditAction",
    "AuditLog",
    "Invite",
    "NumberCounter",
    "NumberScope",
    "ParticipantSelectionMode",
    "Procurement",
    "ProcurementParticipant",
    "ProcurementStatus",
    "PurchaseRequest",
    "PurchaseRequestItem",
    "PurchaseRequestStatus",
    "StatusHistory",
    "User",
    "UserRole",
]
