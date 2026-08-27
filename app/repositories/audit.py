"""Audit log persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

#: Keys that must never reach the audit payload.
_FORBIDDEN_KEYS = {"token", "bot_token", "password", "secret", "authorization"}
_MAX_VALUE_LENGTH = 500


def _sanitize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Drop secrets and truncate long values before persisting metadata."""
    if not payload:
        return {}
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in _FORBIDDEN_KEYS:
            continue
        if isinstance(value, str) and len(value) > _MAX_VALUE_LENGTH:
            value = value[:_MAX_VALUE_LENGTH] + "…"
        clean[key] = value
    return clean


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def log(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: int | None = None,
        actor_user_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        record = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            payload=_sanitize_payload(payload),
        )
        self.session.add(record)
        return record

    async def list_for_entity(
        self, entity_type: str, entity_id: int, limit: int = 50
    ) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
