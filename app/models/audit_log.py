"""Audit trail for security- and data-sensitive operations."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base, IntPKMixin

# JSONB on PostgreSQL, plain JSON elsewhere (keeps unit tests engine-agnostic).
JSONType = JSONB().with_variant(JSON(), "sqlite")


class AuditLog(IntPKMixin, Base):
    """Who did what, to which entity, when.

    ``payload`` holds only non-sensitive descriptive metadata (ids, statuses,
    counts, truncated titles) — never tokens or raw personal data dumps.
    """

    __tablename__ = "audit_logs"

    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_logs_actor_user_id", "actor_user_id"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_action", "action"),
    )


class AuditAction:
    """Canonical audit action names (string constants, not an enum, so that
    adding a new action never requires a database migration)."""

    USER_REGISTERED = "user.registered"
    USER_BOOTSTRAPPED = "user.bootstrapped"
    USER_BLOCKED = "user.blocked"
    USER_UNBLOCKED = "user.unblocked"
    USER_PROFILE_UPDATED = "user.profile_updated"

    APPLICATION_CREATED = "application.created"
    APPLICATION_STATUS_CHANGED = "application.status_changed"
    APPLICATION_REPLIED = "application.replied"

    COURSE_SAVED = "course.saved"
    COURSE_STATUS_CHANGED = "course.status_changed"
    LESSON_SAVED = "lesson.saved"
    LESSON_STATUS_CHANGED = "lesson.status_changed"
    LESSON_DELETED = "lesson.deleted"
    QUIZ_CHANGED = "lesson.quiz_changed"
    FAQ_CHANGED = "faq.changed"
    BOT_TEXT_CHANGED = "bot_text.changed"

    BROADCAST_SENT = "broadcast.sent"
    EXPORT_APPLICATIONS = "export.applications"
    EXPORT_CLIENTS = "export.clients"
