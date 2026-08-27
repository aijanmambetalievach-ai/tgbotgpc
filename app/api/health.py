"""Liveness and readiness endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.database.session import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Process is alive. Never touches the database."""
    return {"status": "ok", "version": __version__}


@router.get("/ready", summary="Readiness probe")
async def ready(response: Response) -> dict[str, object]:
    """Ready to serve traffic: PostgreSQL must answer."""
    checks: dict[str, object] = {"database": False}
    try:
        engine = get_engine()
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:
        checks["error"] = type(exc).__name__
        logger.warning(
            "readiness check failed",
            extra={"operation": "ready", "result": "fail", "error_type": type(exc).__name__},
        )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "checks": checks}

    return {"status": "ready", "checks": checks}
