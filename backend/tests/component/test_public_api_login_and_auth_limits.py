from __future__ import annotations

# ruff: noqa: F403, F405
from .public_api_test_support import *


@pytest.mark.asyncio
@pytest.mark.component
async def test_login_returns_user_only_and_sets_cookie_for_test_env(
    public_api_client: AsyncClient,
    db_session,
) -> None:
    user = await create_user(db_session, "login@example.com", "password123")

    response = await public_api_client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "password123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert response.json() == {
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "is_active": True,
            "created_at": payload["user"]["created_at"],
            "updated_at": payload["user"]["updated_at"],
        }
    }
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header
    assert "Path=/" in cookie_header
    assert f"Max-Age={int(settings.jwt_expire_hours * 3600)}" in cookie_header
    assert "Secure" not in cookie_header


@pytest.mark.asyncio
@pytest.mark.component
async def test_login_sets_secure_cookie_outside_dev_and_test(
    public_api_client: AsyncClient,
    db_session,
    monkeypatch,
) -> None:
    await create_user(db_session, "prod@example.com", "password123")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("app_env", raising=False)
    monkeypatch.setattr(settings, "app_env", "production")

    response = await public_api_client.post(
        "/api/auth/login",
        json={"email": "prod@example.com", "password": "password123"},
    )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_login_uses_runtime_app_env_override_for_secure_cookie(
    public_api_client: AsyncClient,
    db_session,
    monkeypatch,
) -> None:
    await create_user(db_session, "env@example.com", "password123")
    monkeypatch.setenv("APP_ENV", "production")

    response = await public_api_client.post(
        "/api/auth/login",
        json={"email": "env@example.com", "password": "password123"},
    )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_login_rehashes_legacy_pbkdf2_hash_on_success(
    public_api_client: AsyncClient,
    db_session,
) -> None:
    user = User(
        email="legacy@example.com",
        hashed_password=LEGACY_PASSWORD123_HASH,
        role="user",
    )
    db_session.add(user)
    await db_session.commit()

    response = await public_api_client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "password123"},
    )

    assert response.status_code == 200
    refreshed = await db_session.get(User, user.id)
    assert refreshed is not None
    assert "argon2" in refreshed.hashed_password
    assert "pbkdf2-sha256" not in refreshed.hashed_password


@pytest.mark.asyncio
@pytest.mark.component
async def test_auth_specific_rate_limit_rejects_before_generic_limit(
    public_api_client: AsyncClient,
    monkeypatch,
) -> None:
    previous_global = rate_limit_buckets_snapshot()
    previous_auth = auth_rate_limit_buckets_snapshot()
    clear_auth_rate_limit_buckets_for_testing()
    try:
        monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_enabled", True)
        monkeypatch.setattr(
            crawler_runtime_settings, "api_rate_limit_max_requests", 100
        )
        monkeypatch.setattr(
            crawler_runtime_settings, "api_rate_limit_window_seconds", 60
        )
        monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_max_clients", 100)
        monkeypatch.setattr(auth_security, "AUTH_LOGIN_RATE_LIMIT", 1)

        first = await public_api_client.post(
            "/api/auth/login",
            json={"email": "missing@example.com", "password": "wrong-password"},
        )
        second = await public_api_client.post(
            "/api/auth/login",
            json={"email": "missing@example.com", "password": "wrong-password"},
        )

        assert first.status_code == 401
        assert second.status_code == 429
        assert second.json() == {"detail": "Rate limit exceeded"}
        assert int(second.headers["retry-after"]) > 0
    finally:
        restore_rate_limit_buckets_for_testing(previous_global)
        restore_auth_rate_limit_buckets_for_testing(previous_auth)


@pytest.mark.asyncio
@pytest.mark.component
async def test_failed_login_logs_structured_event_without_secrets(
    public_api_client: AsyncClient,
    caplog,
) -> None:
    caplog.set_level(logging.WARNING, logger="app.auth")

    response = await public_api_client.post(
        "/api/auth/login",
        json={"email": "Missing@Example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    event = None
    for record in caplog.records:
        if record.msg == "auth.login_failed":
            event = record
            break
    assert event is not None
    assert event.__dict__["reason"] == "bad_credentials"
    assert event.__dict__["client_id_hash"]
    assert event.__dict__["email_hash"]
    assert "email" not in event.__dict__
    assert "client_ip" not in event.__dict__
    assert "password" not in event.__dict__
    assert "token" not in event.__dict__
