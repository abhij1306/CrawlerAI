from __future__ import annotations

import pytest

from app.core import config


def _patch_secret_guard_settings(monkeypatch, **overrides) -> None:
    values = {
        "app_env": "production",
        "jwt_secret_key": "secure-jwt-secret-value",
        "encryption_key": "secure-encryption-secret-value",
        "default_admin_password": "VeryStrongPassword123!",
        "default_admin_email": "owner@example.com",
        "bootstrap_admin_once": True,
        "database_url": "postgresql+asyncpg://crawler:strong%40password@db.internal:5432/crawlerai",
        "redis_url": "rediss://redis.internal:6379/1",
        "frontend_url": "https://app.example.com",
        "frontend_origins": "https://app.example.com",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setattr(config.settings, name, value)


@pytest.mark.unit
def test_secret_guard_uses_runtime_app_env_override(monkeypatch) -> None:
    monkeypatch.setattr(config, "_RUNTIME_APP_ENV", None)
    monkeypatch.setenv("APP_ENV", "development")
    _patch_secret_guard_settings(
        monkeypatch,
        app_env="production",
        jwt_secret_key="change-me",
    )

    config._check_secret_defaults()


@pytest.mark.unit
def test_secret_guard_warns_for_legacy_admin_password_without_blocking(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(config, "_RUNTIME_APP_ENV", None)
    caplog.set_level("WARNING", logger="app.core.config")
    _patch_secret_guard_settings(
        monkeypatch,
        default_admin_password="OldPass123!",
    )

    config._check_secret_defaults()

    assert any(
        "weaker than the current recommendation" in record.message
        for record in caplog.records
    )


@pytest.mark.unit
def test_secret_guard_rejects_known_weak_admin_password(monkeypatch) -> None:
    monkeypatch.setattr(config, "_RUNTIME_APP_ENV", None)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("app_env", raising=False)
    _patch_secret_guard_settings(
        monkeypatch,
        default_admin_password="AdminPassword123!",
    )

    with pytest.raises(RuntimeError, match="insecure placeholder"):
        config._check_secret_defaults()


@pytest.mark.unit
def test_admin_password_strength_requires_16_characters() -> None:
    assert "at least 16 characters" in config.admin_password_strength_issues(
        "Short123!"
    )
    assert config.admin_password_strength_issues("VeryStrongPassword123!") == []


@pytest.mark.unit
def test_admin_password_strength_edge_cases() -> None:
    assert config.admin_password_strength_issues("Abcdefghijklm1!x") == []
    assert "an uppercase letter" in config.admin_password_strength_issues(
        "abcdefghijklm1!x"
    )
    assert "a lowercase letter" in config.admin_password_strength_issues(
        "ABCDEFGHIJKLM1!X"
    )
    assert "a digit" in config.admin_password_strength_issues("Abcdefghijklmn!x")
    assert "a special character" in config.admin_password_strength_issues(
        "Abcdefghijklm12x"
    )


@pytest.mark.unit
def test_database_url_components_encode_credentials() -> None:
    configured = config.Settings(
        _env_file=None,
        JWT_SECRET_KEY="secure-jwt",
        ENCRYPTION_KEY="secure-encryption",
        DATABASE_URL="",
        DATABASE_HOST="db.internal",
        DATABASE_PORT=5433,
        DATABASE_NAME="crawl/data",
        DATABASE_USER="crawl@example.com",
        DATABASE_PASSWORD="p@ss:/ word",
    )

    assert configured.database_url == (
        "postgresql+asyncpg://crawl%40example.com:p%40ss%3A%2F%20word"
        "@db.internal:5433/crawl%2Fdata"
    )
    assert configured.database_password == ""


@pytest.mark.unit
def test_complete_database_url_takes_precedence_over_components() -> None:
    complete = "postgresql+asyncpg://direct:secret@database.internal:5432/crawlerai"
    configured = config.Settings(
        _env_file=None,
        JWT_SECRET_KEY="secure-jwt",
        ENCRYPTION_KEY="secure-encryption",
        DATABASE_URL=complete,
        DATABASE_HOST="ignored.internal",
        DATABASE_PASSWORD="ignored",
    )

    assert configured.database_url == complete


@pytest.mark.unit
def test_production_database_issues_rejects_invalid_port() -> None:
    assert config.production_database_issues(
        "postgresql+asyncpg://crawler:secret@db.internal:not-a-port/crawlerai"
    ) == ["database_url is invalid"]


@pytest.mark.unit
def test_production_guard_rejects_local_database_redis_and_origin(monkeypatch) -> None:
    monkeypatch.setattr(config, "_RUNTIME_APP_ENV", None)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("app_env", raising=False)
    _patch_secret_guard_settings(
        monkeypatch,
        database_url="postgresql+asyncpg://postgres:postgres@localhost/crawlerai",
        redis_url="redis://localhost:6379/1",
        frontend_url="http://localhost:3001",
        frontend_origins="",
    )

    with pytest.raises(RuntimeError) as exc_info:
        config._check_secret_defaults()

    message = str(exc_info.value)
    assert "database_url must not target localhost" in message
    assert "redis_url must use rediss://" in message
    assert "frontend origins must use https://" in message
