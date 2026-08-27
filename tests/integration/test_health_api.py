"""FastAPI health / readiness endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app import __version__
from app.database.session import dispose_engine, init_engine
from app.main import create_app

pytestmark = pytest.mark.integration


async def test_health_does_not_need_the_database() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_ready_reports_database_availability(migrated_database: str) -> None:
    await dispose_engine()
    init_engine()
    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] is True
    finally:
        await dispose_engine()
