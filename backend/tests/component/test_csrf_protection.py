from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth_service import create_user
from app.core.dependencies import get_db
from app.main import _crawler_app_state, app


@pytest.fixture
async def csrf_client(db_session):
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    crawler_state = _crawler_app_state()
    crawler_state.auth_rate_limit_buckets.clear()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    crawler_state.auth_rate_limit_buckets.clear()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.component
async def test_cookie_auth_unsafe_request_requires_origin_and_proof(
    csrf_client: AsyncClient, db_session
) -> None:
    user = await create_user(db_session, "csrf@example.com", "password123")
    login = await csrf_client.post(
        "/api/auth/login", json={"email": user.email, "password": "password123"}
    )
    token = csrf_client.cookies.get("csrf_token")
    assert login.status_code == 200
    assert token

    missing = await csrf_client.post("/api/auth/logout")
    cross_site = await csrf_client.post(
        "/api/auth/logout",
        headers={"Origin": "https://evil.example", "X-CSRF-Token": token},
    )
    missing_proof = await csrf_client.post(
        "/api/auth/logout", headers={"Origin": "http://127.0.0.1:3001"}
    )
    accepted = await csrf_client.post(
        "/api/auth/logout",
        headers={
            "Origin": "http://127.0.0.1:3001",
            "X-CSRF-Token": token,
        },
    )

    assert missing.status_code == 403
    assert cross_site.status_code == 403
    assert missing_proof.status_code == 403
    assert accepted.status_code == 204


@pytest.mark.asyncio
@pytest.mark.component
async def test_bearer_authenticated_unsafe_request_is_csrf_exempt(
    csrf_client: AsyncClient, db_session
) -> None:
    user = await create_user(db_session, "bearer@example.com", "password123")
    login = await csrf_client.post(
        "/api/auth/login", json={"email": user.email, "password": "password123"}
    )
    access_token = csrf_client.cookies.get("access_token")
    assert login.status_code == 200
    assert access_token

    response = await csrf_client.post(
        "/api/api-keys",
        json={"name": "Bearer client"},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 201
