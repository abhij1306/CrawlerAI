# Centralized application settings.
from __future__ import annotations

import os
from pathlib import Path
import re
from threading import Lock
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BASE_DIR.parent


def _resolve_project_path(value: str | Path, *, anchor: Path = PROJECT_ROOT) -> Path:
    raw_path = Path(value)
    return raw_path if raw_path.is_absolute() else (anchor / raw_path).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Support both repo-root and backend-local .env files.
        env_file=(str(PROJECT_ROOT / ".env"), str(BASE_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Invoro"
    app_env: str = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "app_env"),
    )
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_url: str = "http://127.0.0.1:3000"
    frontend_origins: str = ""
    jwt_secret_key: str = Field(
        validation_alias=AliasChoices("JWT_SECRET_KEY", "jwt_secret_key"),
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 1
    encryption_key: str = Field(
        validation_alias=AliasChoices("ENCRYPTION_KEY", "encryption_key"),
    )
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/crawl_db"
    redis_url: str = "redis://localhost:6379/0"
    redis_state_enabled: bool = False
    celery_dispatch_enabled: bool = True
    scheduler_driver: Literal["dev", "celery"] = Field(
        default="dev",
        validation_alias=AliasChoices("SCHEDULER_DRIVER", "scheduler_driver"),
    )
    artifacts_dir: Path = Field(default=BASE_DIR / "artifacts")
    acquisition_cache_dir: Path = Field(
        default=BASE_DIR / "artifacts" / "acquisition_cache"
    )
    cookie_store_dir: Path = Field(default=BASE_DIR / "cookie_store")
    playwright_headless: bool = True
    browser_pool_size: int = 4
    browser_context_timeout_seconds: float = 30.0
    http_timeout_seconds: float = 20.0
    http_max_connections: int = 100
    http_max_keepalive_connections: int = 40
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "MISTRAL_API_KEY",
            "MISTRALAI_API_KEY",
            "mistral_api_key",
        ),
    )
    nvidia_api_key: str = ""
    openrouter_api_key: str = ""
    request_id_header: str = "X-Request-ID"
    crawl_log_db_min_level: str = "info"
    crawl_log_db_url_progress_sample_rate: int = 4
    crawl_log_db_max_rows_per_run: int = 1000
    crawl_log_file_enabled: bool = True
    crawl_log_file_dir: Path = Field(default=BASE_DIR / "artifacts" / "run_logs")
    logfire_enabled: bool = False
    logfire_token: str = Field(
        default="",
        validation_alias=AliasChoices("LOGFIRE_TOKEN", "logfire_token"),
    )
    logfire_service_name: str = "invoro-backend"
    logfire_environment: str = ""
    logfire_capture_headers: bool = False
    logfire_send_to_logfire: bool | Literal["if-token-present"] = Field(
        default="if-token-present",
        validation_alias=AliasChoices(
            "LOGFIRE_SEND_TO_LOGFIRE",
            "logfire_send_to_logfire",
        ),
    )
    logfire_enabled_in_tests: bool = False
    system_max_concurrent_urls: int = 8
    llm_cache_ttl_seconds: int = 86400
    default_admin_email: str = Field(
        default="",
        validation_alias=AliasChoices("DEFAULT_ADMIN_EMAIL", "default_admin_email"),
    )
    default_admin_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DEFAULT_ADMIN_PASSWORD",
            "default_admin_password",
        ),
    )
    bootstrap_admin_once: bool = Field(
        default=False,
        validation_alias=AliasChoices("BOOTSTRAP_ADMIN_ONCE", "bootstrap_admin_once"),
    )
    # When false, POST /api/auth/register returns 403 (POC single-admin dev). Enable for production multi-tenant.
    registration_enabled: bool = False

    # Database pool tuning (ignored for SQLite).
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 600
    db_pool_timeout_seconds: int = 10
    db_pool_pre_ping: bool = True

    @field_validator(
        "artifacts_dir",
        "acquisition_cache_dir",
        "cookie_store_dir",
        "crawl_log_file_dir",
        mode="before",
    )
    @classmethod
    def _resolve_repo_relative_paths(cls, value: str | Path) -> Path:
        return _resolve_project_path(value, anchor=PROJECT_ROOT)

    @field_validator("scheduler_driver", mode="before")
    @classmethod
    def _normalize_scheduler_driver(cls, value: object) -> str:
        return str(value or "dev").strip().lower()


def _load_settings() -> Settings:
    # BaseSettings reads required values from environment/.env at runtime.
    return Settings()  # type: ignore[call-arg]


settings = _load_settings()
_RUNTIME_APP_ENV: str | None = None
_RUNTIME_APP_ENV_LOCK = Lock()


# ---------------------------------------------------------------------------
# Security guard: reject default secrets in non-dev environments
# ---------------------------------------------------------------------------
_INSECURE_DEFAULTS = {
    "change-me",
    "change-me-32-bytes-minimum-change-me",
    "replace-with-64-byte-random-secret",
    "replace-with-32-byte-minimum-secret",
}
_INSECURE_ADMIN_PASSWORD_DEFAULTS = {"AdminPassword123!", "YourSecurePassword123!"}
_INSECURE_ADMIN_EMAIL_DEFAULTS = {"admin@admin.com", "admin@example.invalid"}
_MIN_ADMIN_PASSWORD_LENGTH = 16


def _is_non_dev_environment(env_name: str) -> bool:
    normalized = str(env_name or "").strip().lower()
    return normalized not in {"", "development", "dev", "local", "test", "testing"}


def admin_password_strength_issues(password: str) -> list[str]:
    issues: list[str] = []
    if len(password) < _MIN_ADMIN_PASSWORD_LENGTH:
        issues.append(f"at least {_MIN_ADMIN_PASSWORD_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        issues.append("an uppercase letter")
    if not re.search(r"[a-z]", password):
        issues.append("a lowercase letter")
    if not re.search(r"\d", password):
        issues.append("a digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        issues.append("a special character")
    return issues


def runtime_app_env() -> str:
    global _RUNTIME_APP_ENV
    if _RUNTIME_APP_ENV is not None:
        return _RUNTIME_APP_ENV
    with _RUNTIME_APP_ENV_LOCK:
        if _RUNTIME_APP_ENV is not None:
            return _RUNTIME_APP_ENV
        if os.getenv("APP_ENV") is not None or os.getenv("app_env") is not None:
            _RUNTIME_APP_ENV = str(_load_settings().app_env or "development")
            return _RUNTIME_APP_ENV
        _RUNTIME_APP_ENV = str(settings.app_env or "development")
        return _RUNTIME_APP_ENV


def _check_secret_defaults() -> None:
    """Warn loudly (or crash outside dev/test) if default secrets are still set."""
    import logging

    logger = logging.getLogger("app.core.config")
    env = runtime_app_env().lower()
    issues: list[str] = []
    warnings: list[str] = []
    if settings.jwt_secret_key in _INSECURE_DEFAULTS:
        issues.append("jwt_secret_key is set to a default value")
    if settings.encryption_key in _INSECURE_DEFAULTS:
        issues.append("encryption_key is set to a default value")
    default_admin_password = str(settings.default_admin_password or "").strip()
    default_admin_email = str(settings.default_admin_email or "").strip().lower()
    if default_admin_password in _INSECURE_ADMIN_PASSWORD_DEFAULTS:
        issues.append("admin bootstrap secret is set to an insecure placeholder value")
    if settings.bootstrap_admin_once and default_admin_password:
        password_issues = admin_password_strength_issues(default_admin_password)
        if password_issues:
            warnings.append("admin bootstrap secret strength requirements not met")
    if settings.bootstrap_admin_once and not default_admin_password:
        issues.append(
            "bootstrap_admin_once requires a non-empty admin bootstrap secret"
        )
    if (
        settings.bootstrap_admin_once
        and default_admin_email in _INSECURE_ADMIN_EMAIL_DEFAULTS
    ):
        issues.append("bootstrap_admin_once requires a non-default default_admin_email")
    if warnings:
        logger.warning(
            "SECURITY WARNING: admin bootstrap secret is weaker than the current recommendation",
            extra={"warnings": warnings, "warning_count": len(warnings)},
        )
    if not issues:
        return
    msg = (
        "SECURITY WARNING: insecure default secrets detected:\n  - "
        + "\n  - ".join(issues)
        + '\nGenerate secure values: python -c "import secrets; print(secrets.token_urlsafe(64))"'
    )
    if _is_non_dev_environment(env):
        raise RuntimeError(msg)
    logger.warning(
        "SECURITY WARNING: insecure default secrets detected",
        extra={"issues": issues, "issue_count": len(issues)},
    )


_check_secret_defaults()


def get_frontend_origins() -> list[str]:
    if settings.frontend_origins.strip():
        return [
            origin.strip()
            for origin in settings.frontend_origins.split(",")
            if origin.strip()
        ]

    origin = settings.frontend_url.rstrip("/")
    variants = {origin}
    if "127.0.0.1" in origin:
        variants.add(origin.replace("127.0.0.1", "localhost"))
    if "localhost" in origin:
        variants.add(origin.replace("localhost", "127.0.0.1"))
    return sorted(variants)


def load_admin_bootstrap_settings() -> Settings:
    fresh = _load_settings()
    resolved = settings.model_copy()
    if (
        os.getenv("DEFAULT_ADMIN_EMAIL") is not None
        or os.getenv("default_admin_email") is not None
    ):
        resolved = resolved.model_copy(
            update={"default_admin_email": fresh.default_admin_email}
        )
    if (
        os.getenv("DEFAULT_ADMIN_PASSWORD") is not None
        or os.getenv("default_admin_password") is not None
    ):
        resolved = resolved.model_copy(
            update={"default_admin_password": fresh.default_admin_password}
        )
    if (
        os.getenv("BOOTSTRAP_ADMIN_ONCE") is not None
        or os.getenv("bootstrap_admin_once") is not None
    ):
        resolved = resolved.model_copy(
            update={"bootstrap_admin_once": fresh.bootstrap_admin_once}
        )
    return resolved
