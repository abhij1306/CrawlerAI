from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_admin
from app.main import app


@pytest.fixture
async def memory_api_client(db_session: AsyncSession, test_user):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[require_admin] = _override_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.component
async def test_extraction_memory_api_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/knowledge/sites")
    assert response.status_code == 401
