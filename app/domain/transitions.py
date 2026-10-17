"""Application status machine.

    NEW ──► IN_PROGRESS ──► DONE
     │           │
     ├──► DONE   ├──► REJECTED
     ├──► REJECTED
     └──► CANCELLED (by the client, while still open)

Closed statuses are terminal: a finished conversation is never silently
reopened — the client simply creates a new application.
"""

from __future__ import annotations

from app.domain.exceptions import InvalidStatusTransitionError
from app.models.enums import ApplicationStatus

S = ApplicationStatus

STAFF_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    S.NEW: frozenset({S.IN_PROGRESS, S.DONE, S.REJECTED}),
    S.IN_PROGRESS: frozenset({S.DONE, S.REJECTED}),
    S.DONE: frozenset(),
    S.REJECTED: frozenset(),
    S.CANCELLED: frozenset(),
}

CLIENT_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    S.NEW: frozenset({S.CANCELLED}),
    S.IN_PROGRESS: frozenset({S.CANCELLED}),
    S.DONE: frozenset(),
    S.REJECTED: frozenset(),
    S.CANCELLED: frozenset(),
}

CLOSED_STATUSES: frozenset[ApplicationStatus] = frozenset({S.DONE, S.REJECTED, S.CANCELLED})


def can_transition(
    current: ApplicationStatus, target: ApplicationStatus, *, by_staff: bool
) -> bool:
    table = STAFF_TRANSITIONS if by_staff else CLIENT_TRANSITIONS
    return target in table[current]


def ensure_transition(
    current: ApplicationStatus, target: ApplicationStatus, *, by_staff: bool
) -> None:
    if not can_transition(current, target, by_staff=by_staff):
        raise InvalidStatusTransitionError()
