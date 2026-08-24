from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import auth_service
from app.core.config import settings
from app.core.dependencies import get_db
from app.main import app
from app.models.bootstrap import BootstrapRecord
from app.models.user import User

LEGACY_PASSWORD123_HASH = (
    "$pbkdf2-sha256$29000$Y3Jhd2xlcmFpLWxlZ2FjeQ$"
    "F7j4hPy493QxNr/jRcYlrrBPTfVKMk2RGskTbjrUnL8"
)
LEGACY_STRONG_PASSWORD_HASH = (
    "$pbkdf2-sha256$29000$Y3Jhd2xlcmFpLWxlZ2FjeQ$"
    "/tCNK5jBshr8iUnQoaY0WGkZRULPc/FV2ZEnIt8bq8o"
)


@pytest.fixture
async def auth_api_client(db_session):
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
async def test_bootstrap_admin_user_creates_admin(db_session, monkeypatch) -> None:
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "VeryStrongPassword123!")
    monkeypatch.setattr(settings, "default_admin_password", "VeryStrongPassword123!")
    monkeypatch.setattr(
        auth_service,
        "load_admin_bootstrap_settings",
        lambda: SimpleNamespace(
            bootstrap_admin_once=True,
            default_admin_email="Admin@Example.com",
            default_admin_password="VeryStrongPassword123!",
        ),
    )

    user = await auth_service.bootstrap_admin_user(db_session)

    assert user is not None
    assert user.email == "admin@example.com"
    assert user.role == "admin"
    assert user.is_active is True
    assert await db_session.get(BootstrapRecord, "initial-admin") is not None
    assert "DEFAULT_ADMIN_PASSWORD" not in os.environ
    assert settings.default_admin_password is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_bootstrap_admin_restart_is_noop(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        auth_service,
        "load_admin_bootstrap_settings",
        lambda: SimpleNamespace(
            bootstrap_admin_once=True,
            default_admin_email="restart@example.com",
            default_admin_password="VeryStrongPassword123!",
        ),
    )

    created = await auth_service.bootstrap_admin_user(db_session)
    restarted = await auth_service.bootstrap_admin_user(db_session)

    assert created is not None
    assert restarted is None
    users = list(await db_session.scalars(select(User)))
    assert [user.email for user in users] == ["restart@example.com"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_bootstrap_admin_refuses_existing_identity(
    db_session, monkeypatch
) -> None:
    existing = await auth_service.create_user(
        db_session, "existing@example.com", "OriginalPassword123!", role="user"
    )
    existing.is_active = False
    await db_session.commit()
    monkeypatch.setattr(
        auth_service,
        "load_admin_bootstrap_settings",
        lambda: SimpleNamespace(
            bootstrap_admin_once=True,
            default_admin_email="existing@example.com",
            default_admin_password="ReplacementPassword123!",
        ),
    )

    with pytest.raises(RuntimeError, match="refusing promotion"):
        await auth_service.bootstrap_admin_user(db_session)

    await db_session.refresh(existing)
    assert existing.role == "user"
    assert existing.is_active is False
    assert await db_session.get(BootstrapRecord, "initial-admin") is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_concurrent_bootstrap_creates_one_admin(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        auth_service,
        "load_admin_bootstrap_settings",
        lambda: SimpleNamespace(
            bootstrap_admin_once=True,
            default_admin_email="race@example.com",
            default_admin_password="VeryStrongPassword123!",
        ),
    )
    factory = async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    async def _run():
        async with factory() as session:
            return await auth_service.bootstrap_admin_user(session)

    first, second = await asyncio.gather(_run(), _run())

    assert sum(result is not None for result in (first, second)) == 1
    users = list(
        await db_session.scalars(select(User).where(User.email == "race@example.com"))
    )
    assert len(users) == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_authenticate_user_requires_active_user(db_session) -> None:
    user = await auth_service.create_user(
        db_session,
        "login@example.com",
        "VeryStrongPassword123!",
    )

    authenticated = await auth_service.authenticate_user(
        db_session,
        "login@example.com",
        "VeryStrongPassword123!",
    )
    bad_password = await auth_service.authenticate_user(
        db_session,
        "login@example.com",
        "wrong-password",
    )
    user.is_active = False
    await db_session.commit()
    inactive = await auth_service.authenticate_user(
        db_session,
        "login@example.com",
        "VeryStrongPassword123!",
    )

    assert authenticated is not None
    token, authenticated_user = authenticated
    assert token
    assert authenticated_user.id == user.id
    assert bad_password is None
    assert inactive is None


@pytest.mark.component
def test_default_admin_password_validation_warns_without_blocking(caplog) -> None:
    caplog.set_level("WARNING", logger="app.auth")

    auth_service._validate_default_admin_password("Short123!")

    assert any(
        "weaker than the current recommendation" in record.message
        for record in caplog.records
    )


@pytest.mark.component
def test_hash_password_uses_argon2_by_default() -> None:
    hashed = auth_service.hash_password("password123")

    assert hashed != "password123"
    assert auth_service.verify_password("password123", hashed) is True
    assert auth_service.password_needs_rehash(hashed) is False


@pytest.mark.component
def test_password_needs_rehash_detects_legacy_pbkdf2_hash() -> None:
    assert auth_service.password_needs_rehash(LEGACY_PASSWORD123_HASH) is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_authenticate_user_rehash_does_not_commit_unrelated_changes(
    db_session,
) -> None:
    legacy_user = await auth_service.create_user(
        db_session,
        "legacy@example.com",
        "VeryStrongPassword123!",
    )
    legacy_user.hashed_password = LEGACY_STRONG_PASSWORD_HASH
    await db_session.commit()
    await db_session.refresh(legacy_user)

    other_user = await auth_service.create_user(
        db_session,
        "other@example.com",
        "VeryStrongPassword123!",
    )
    other_user.is_active = False

    authenticated = await auth_service.authenticate_user(
        db_session,
        "legacy@example.com",
        "VeryStrongPassword123!",
    )

    observer_factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with observer_factory() as observer_session:
        observed_other_user = await observer_session.get(
            type(other_user), other_user.id
        )

    assert authenticated is not None
    assert observed_other_user is not None
    assert observed_other_user.is_active is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_register_rejects_short_password(
    auth_api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "registration_enabled", True)

    response = await auth_api_client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "short123"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.component
async def test_register_accepts_policy_compliant_password(
    auth_api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "registration_enabled", True)

    response = await auth_api_client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "LongEnoughPassword1!"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "new@example.com"


@pytest.mark.asyncio
@pytest.mark.component
async def test_login_still_accepts_legacy_short_password(
    auth_api_client: AsyncClient, db_session
) -> None:
    await auth_service.create_user(db_session, "legacy@example.com", "short123")

    response = await auth_api_client.post(
        "/api/auth/login",
        json={"email": "legacy@example.com", "password": "short123"},
    )

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.component
async def test_user_update_rejects_unknown_role(
    auth_api_client: AsyncClient, test_user
) -> None:
    login = await auth_api_client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "password123"},
    )
    assert login.status_code == 200

    response = await auth_api_client.patch(
        f"/api/users/{test_user.id}",
        json={"role": "superuser"},
        headers={
            "Origin": "http://127.0.0.1:3001",
            "X-CSRF-Token": auth_api_client.cookies.get("csrf_token"),
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.component
async def test_user_update_accepts_known_role(
    auth_api_client: AsyncClient, db_session, test_user
) -> None:
    managed = await auth_service.create_user(
        db_session, "managed@example.com", "VeryStrongPassword123!"
    )
    login = await auth_api_client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "password123"},
    )
    assert login.status_code == 200

    response = await auth_api_client.patch(
        f"/api/users/{managed.id}",
        json={"role": "admin"},
        headers={
            "Origin": "http://127.0.0.1:3001",
            "X-CSRF-Token": auth_api_client.cookies.get("csrf_token"),
        },
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
