"""HTTP API surface.

Today this only exposes health probes; it is deliberately a real FastAPI app so
a future web admin panel can be added without re-architecting anything.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import health

api_router = APIRouter()
api_router.include_router(health.router)

__all__ = ["api_router"]
