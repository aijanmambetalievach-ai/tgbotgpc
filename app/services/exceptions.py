"""Service-layer view of the domain errors (re-export for convenience)."""

from app.domain.exceptions import (
    DeadlineExpiredError,
    DomainError,
    DuplicateSubmissionError,
    InvalidStatusTransitionError,
    InviteError,
    LimitExceededError,
    NotAParticipantError,
    NotFoundError,
    PermissionDeniedError,
    ProcurementNotAcceptingError,
    ValidationError,
)

__all__ = [
    "DeadlineExpiredError",
    "DomainError",
    "DuplicateSubmissionError",
    "InvalidStatusTransitionError",
    "InviteError",
    "LimitExceededError",
    "NotAParticipantError",
    "NotFoundError",
    "PermissionDeniedError",
    "ProcurementNotAcceptingError",
    "ValidationError",
]
