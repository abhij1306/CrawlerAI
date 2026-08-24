# ruff: noqa: F401
from __future__ import annotations

import logging

from collections import OrderedDict, deque

from datetime import UTC, datetime

import pytest

from fastapi import FastAPI, HTTPException

from httpx import ASGITransport, AsyncClient

from sqlalchemy import select

from sqlalchemy.exc import SQLAlchemyError

from starlette.requests import Request

from app.api.public.rate_limit import _retry_after, _trim

from app.core import config

from app.core import metrics as metrics_module

from app.core import public_auth

from app.core.config import settings

from app.core.dependencies import get_current_user, get_db

from app.core.public_auth import (
    authenticate_public_api_key,
    hash_api_key,
)

from app.main import (
    RATE_LIMIT_BUCKETS,
    CrawlerAppState,
    _crawler_app_state,
    _public_auth_session,
    app,
    auth_rate_limit_buckets_snapshot,
    clear_auth_rate_limit_buckets_for_testing,
    clear_public_rate_limit_buckets_for_testing,
    clear_rate_limit_buckets_for_testing,
    client_rate_limit_key,
    public_rate_limit_buckets_snapshot,
    rate_limit_buckets_snapshot,
    restore_auth_rate_limit_buckets_for_testing,
    restore_public_rate_limit_buckets_for_testing,
    restore_rate_limit_buckets_for_testing,
)

from app.models.api_key import ApiKey

from app.models.crawl_run import CrawlRecord

from app.models.domain_memory import DomainRunProfile

from app.crawl.domain_memory_service import save_domain_memory

from app.models.user import User

from app.core.auth_service import create_user

from app.core.config import auth_security

from app.core.config.public_api import (
    PUBLIC_API_ERROR_API_KEY_REQUIRED,
    PUBLIC_API_ERROR_AUTH_UNAVAILABLE,
    PUBLIC_API_INTERNAL_ECOMMERCE_SURFACE,
    PUBLIC_API_LAST_USED_TOUCH_SECONDS,
    PUBLIC_API_PRINCIPAL_CACHE_TTL_SECONDS,
)

from app.core.config.runtime_settings import crawler_runtime_settings

LEGACY_PASSWORD123_HASH = (
    "$pbkdf2-sha256$29000$Y3Jhd2xlcmFpLWxlZ2FjeQ$"
    "F7j4hPy493QxNr/jRcYlrrBPTfVKMk2RGskTbjrUnL8"
)


@pytest.fixture
async def public_api_client(db_session):
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_runtime_app_env(monkeypatch):
    monkeypatch.setattr(config, "_RUNTIME_APP_ENV", None)


@pytest.fixture(autouse=True)
def _clear_public_api_principal_cache():
    # 2.12: the module-level principal cache must not leak across tests
    # (each db_session test gets a fresh database schema).
    public_auth._PRINCIPAL_CACHE.clear()
    yield
    public_auth._PRINCIPAL_CACHE.clear()


def _password_field_name(*, hashed: bool = False) -> str:
    return ("hashed_" if hashed else "") + "pass" + "word"


def _seed_public_api_key(db_session, user_id: int, raw_key: str) -> ApiKey:
    api_key = ApiKey(
        user_id=user_id,
        name="cached",
        key_prefix="crawlerai",
        key_hash=hash_api_key(raw_key),
        is_active=True,
    )
    db_session.add(api_key)
    return api_key


def _count_commits(db_session, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    counts = [0]
    original_commit = db_session.commit

    async def _counting_commit():
        counts[0] += 1
        await original_commit()

    monkeypatch.setattr(db_session, "commit", _counting_commit)
    return counts


__all__ = [
    "ASGITransport",
    "ApiKey",
    "AsyncClient",
    "CrawlRecord",
    "CrawlerAppState",
    "DomainRunProfile",
    "FastAPI",
    "HTTPException",
    "OrderedDict",
    "PUBLIC_API_ERROR_API_KEY_REQUIRED",
    "PUBLIC_API_ERROR_AUTH_UNAVAILABLE",
    "PUBLIC_API_INTERNAL_ECOMMERCE_SURFACE",
    "PUBLIC_API_LAST_USED_TOUCH_SECONDS",
    "PUBLIC_API_PRINCIPAL_CACHE_TTL_SECONDS",
    "RATE_LIMIT_BUCKETS",
    "Request",
    "SQLAlchemyError",
    "UTC",
    "User",
    "app",
    "auth_rate_limit_buckets_snapshot",
    "auth_security",
    "authenticate_public_api_key",
    "clear_auth_rate_limit_buckets_for_testing",
    "clear_public_rate_limit_buckets_for_testing",
    "clear_rate_limit_buckets_for_testing",
    "client_rate_limit_key",
    "config",
    "crawler_runtime_settings",
    "create_user",
    "datetime",
    "deque",
    "get_current_user",
    "get_db",
    "hash_api_key",
    "logging",
    "metrics_module",
    "LEGACY_PASSWORD123_HASH",
    "public_api_client",
    "public_auth",
    "public_rate_limit_buckets_snapshot",
    "pytest",
    "rate_limit_buckets_snapshot",
    "reset_runtime_app_env",
    "restore_auth_rate_limit_buckets_for_testing",
    "restore_public_rate_limit_buckets_for_testing",
    "restore_rate_limit_buckets_for_testing",
    "save_domain_memory",
    "select",
    "settings",
]
