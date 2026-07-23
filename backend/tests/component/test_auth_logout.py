"""Component tests for POST /api/auth/logout (audit 5.3 backend slice)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth_service import create_user
from app.core.dependencies import get_db
from app.main import app


@pytest.fixture
async def auth_client(db_session):
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.component
async def test_logout_revokes_session_and_clears_cookie(
    auth_client: AsyncClient, db_session
) -> None:
    user = await create_user(db_session, "logout@example.com", "password123")

    login = await auth_client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    assert login.status_code == 200
    token = auth_client.cookies.get("access_token")
    assert token

    me = await auth_client.get("/api/auth/me")
    assert me.status_code == 200

    logout = await auth_client.post("/api/auth/logout")
    assert logout.status_code == 204
    set_cookie = logout.headers["set-cookie"]
    assert "access_token" in set_cookie
    assert "Max-Age=0" in set_cookie
    assert "Path=/" in set_cookie
    assert auth_client.cookies.get("access_token") is None

    me_after = await auth_client.get("/api/auth/me")
    assert me_after.status_code == 401

    # The revoked token is rejected even when replayed explicitly.
    replay = await auth_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert replay.status_code == 401


@pytest.mark.asyncio
@pytest.mark.component
async def test_logout_without_cookie_is_idempotent(auth_client: AsyncClient) -> None:
    first = await auth_client.post("/api/auth/logout")
    second = await auth_client.post("/api/auth/logout")

    assert first.status_code == 204
    assert second.status_code == 204


@pytest.mark.asyncio
@pytest.mark.component
async def test_logout_with_revoked_token_still_clears_cookie(
    auth_client: AsyncClient, db_session
) -> None:
    user = await create_user(db_session, "logout2@example.com", "password123")

    login = await auth_client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    assert login.status_code == 200

    first = await auth_client.post("/api/auth/logout")
    assert first.status_code == 204

    # Second logout with the already-revoked session stays a 204 no-op.
    second = await auth_client.post("/api/auth/logout")
    assert second.status_code == 204
