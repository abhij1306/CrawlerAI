from __future__ import annotations

import logging
from collections import OrderedDict, deque
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from passlib.hash import pbkdf2_sha256
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from app.api.public.rate_limit import _retry_after, _trim
from app.core import config
from app.core import metrics as metrics_module
from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.core.public_auth import authenticate_public_api_key, hash_api_key
from app.main import (
    RATE_LIMIT_BUCKETS,
    CrawlerAppState,
    _crawler_app_state,
    _public_auth_session,
    app,
    auth_rate_limit_buckets_snapshot,
    clear_auth_rate_limit_buckets_for_testing,
    clear_rate_limit_buckets_for_testing,
    client_rate_limit_key,
    rate_limit_buckets_snapshot,
    restore_auth_rate_limit_buckets_for_testing,
    restore_rate_limit_buckets_for_testing,
)
from app.models.api_key import ApiKey
from app.models.crawl_run import CrawlRecord
from app.models.domain_memory import DomainMemory, DomainRunProfile
from app.models.user import User
from app.services.auth_service import create_user
from app.services.config import auth_security
from app.services.config.public_api import (
    PUBLIC_API_ERROR_API_KEY_REQUIRED,
    PUBLIC_API_ERROR_AUTH_UNAVAILABLE,
    PUBLIC_API_INTERNAL_ECOMMERCE_SURFACE,
)
from app.services.config.runtime_settings import crawler_runtime_settings



@pytest.fixture
async def public_api_client(db_session):
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()



# from backend/tests/services/test_auth_api.py
@pytest.fixture(autouse=True)
def reset_runtime_app_env(monkeypatch):
    monkeypatch.setattr(config, "_RUNTIME_APP_ENV", None)


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
        hashed_password=pbkdf2_sha256.hash("password123"),
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
        monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_max_requests", 100)
        monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_window_seconds", 60)
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
    event = next(record for record in caplog.records if record.msg == "auth.login_failed")
    assert event.__dict__["email"] == "missing@example.com"
    assert event.__dict__["reason"] == "bad_credentials"
    assert event.__dict__["client_ip"]
    assert "password" not in event.__dict__
    assert "token" not in event.__dict__


# from backend/tests/services/test_health_api.py
@pytest.mark.asyncio
@pytest.mark.component
async def test_live_health_endpoint_is_lightweight() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


@pytest.mark.asyncio
@pytest.mark.component
async def test_ready_health_endpoint_reports_dependency_failure(monkeypatch) -> None:
    async def db_ok() -> bool:
        return True

    async def redis_failed() -> bool:
        return False

    monkeypatch.setattr("app.main.check_database", db_ok)
    monkeypatch.setattr("app.main.check_redis", redis_failed)
    monkeypatch.setattr("app.main.check_browser_pool", lambda: True)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {
            "database": True,
            "redis": False,
            "browser_pool": True,
        },
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_http_rate_limit_rejects_excess_requests(monkeypatch) -> None:
    previous_buckets = rate_limit_buckets_snapshot()
    clear_rate_limit_buckets_for_testing()
    try:
        monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_enabled", True)
        monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_max_requests", 1)
        monkeypatch.setattr(
            crawler_runtime_settings, "api_rate_limit_window_seconds", 60
        )
        monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_max_clients", 10)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            first = await client.get("/not-found")
            second = await client.get("/not-found")

        assert first.status_code == 404
        assert second.status_code == 429
        assert second.json() == {"detail": "Rate limit exceeded"}
        assert "retry-after" in second.headers
        assert int(second.headers["retry-after"]) > 0
    finally:
        restore_rate_limit_buckets_for_testing(previous_buckets)


@pytest.mark.asyncio
@pytest.mark.component
async def test_health_and_metrics_skip_http_rate_limit(monkeypatch) -> None:
    previous_buckets = rate_limit_buckets_snapshot()
    clear_rate_limit_buckets_for_testing()
    try:
        monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_enabled", True)
        monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_max_requests", 1)
        monkeypatch.setattr(
            crawler_runtime_settings, "api_rate_limit_window_seconds", 60
        )
        monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_max_clients", 10)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            assert (await client.get("/health/live")).status_code == 200
            assert (await client.get("/api/metrics")).status_code == 200
    finally:
        restore_rate_limit_buckets_for_testing(previous_buckets)


@pytest.mark.asyncio
@pytest.mark.component
async def test_render_prometheus_metrics_continues_on_crawl_run_query_failure(
    monkeypatch,
) -> None:
    if metrics_module._registry is None or metrics_module._prometheus_client is None:
        pytest.skip("prometheus_client not installed")

    class _FailingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def execute(self, *_args, **_kwargs):
            raise SQLAlchemyError("db down")

    class _Counter:
        def __init__(self) -> None:
            self.value = 0

        def inc(self, amount: float = 1.0) -> None:
            self.value += amount

    class _Gauge:
        def __init__(self) -> None:
            self.values: list[object] = []
            self.clear_calls = 0

        def labels(self, **_kwargs):
            return self

        def set(self, value: object) -> None:
            self.values.append(value)

        def clear(self) -> None:
            self.clear_calls += 1

    failure_counter = _Counter()
    crawl_runs_total = _Gauge()
    browser_pool_size = _Gauge()
    database_connections_active = _Gauge()
    redis_failures_total_metric = _Gauge()
    monkeypatch.setattr(metrics_module, "SessionLocal", lambda: _FailingSession())
    monkeypatch.setattr(
        metrics_module,
        "crawl_runs_query_failures_total",
        failure_counter,
    )
    monkeypatch.setattr(metrics_module, "crawl_runs_total", crawl_runs_total)
    monkeypatch.setattr(metrics_module, "browser_pool_size", browser_pool_size)
    monkeypatch.setattr(
        metrics_module,
        "database_connections_active",
        database_connections_active,
    )
    monkeypatch.setattr(
        metrics_module,
        "redis_failures_total_metric",
        redis_failures_total_metric,
    )
    monkeypatch.setattr(
        metrics_module,
        "browser_runtime_snapshot",
        lambda: {"size": 3, "max_size": 10},
    )
    monkeypatch.setattr(metrics_module, "_database_connections_checked_out", lambda: 4)
    monkeypatch.setattr(metrics_module, "redis_failure_total", lambda: 5)
    monkeypatch.setattr(
        metrics_module,
        "_prometheus_client",
        type(
            "_PrometheusClient",
            (),
            {"generate_latest": staticmethod(lambda _registry: b"ok\n")},
        )(),
    )

    payload, _content_type = await metrics_module.render_prometheus_metrics()

    assert payload == b"ok\n"
    assert failure_counter.value == 1
    assert crawl_runs_total.clear_calls == 1
    assert browser_pool_size.values == [3]
    assert database_connections_active.values == [4]
    assert redis_failures_total_metric.values == [5]


@pytest.mark.asyncio
@pytest.mark.component
async def test_api_responses_include_security_headers() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert (
        response.headers["permissions-policy"]
        == "camera=(), microphone=(), geolocation=()"
    )
    assert "strict-transport-security" not in response.headers


@pytest.mark.asyncio
@pytest.mark.component
async def test_cors_preflight_uses_narrow_allowlists() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,authorization,x-request-id",
            },
        )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-methods"]
        == "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    )
    assert response.headers["access-control-allow-headers"] != "*"
    allow_headers = response.headers["access-control-allow-headers"].lower()
    assert "content-type" in allow_headers
    assert "authorization" in allow_headers
    assert "x-request-id" in allow_headers


@pytest.mark.component
def test_client_rate_limit_key_ignores_forwarded_for_from_untrusted_peer(
    monkeypatch,
) -> None:
    monkeypatch.setattr(crawler_runtime_settings, "api_rate_limit_trusted_proxies", ())
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/not-found",
            "headers": [(b"x-forwarded-for", b"203.0.113.10")],
            "client": ("198.51.100.2", 1234),
        }
    )

    assert client_rate_limit_key(request) == "198.51.100.2"


@pytest.mark.component
def test_client_rate_limit_key_honors_forwarded_for_from_trusted_peer(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        crawler_runtime_settings, "api_rate_limit_trusted_proxies", ("198.51.100.2",)
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/not-found",
            "headers": [(b"x-forwarded-for", b"203.0.113.10, 198.51.100.2")],
            "client": ("198.51.100.2", 1234),
        }
    )

    assert client_rate_limit_key(request) == "203.0.113.10"


@pytest.mark.component
def test_rate_limit_buckets_view_tracks_replaced_app_state() -> None:
    previous_state = app.state.crawler
    try:
        app.state.crawler = CrawlerAppState(
            rate_limit_buckets=OrderedDict(
                [("client-a", deque([1.0])), ("client-b", deque([2.0]))]
            )
        )

        assert list(RATE_LIMIT_BUCKETS) == ["client-a", "client-b"]
        assert list(RATE_LIMIT_BUCKETS["client-a"]) == [1.0]
    finally:
        app.state.crawler = previous_state


@pytest.mark.component
def test_crawler_app_state_rejects_explicit_app_without_crawler_state() -> None:
    with pytest.raises(RuntimeError, match="state.crawler"):
        _crawler_app_state(FastAPI())


# from backend/tests/services/test_public_api_auth.py
def _password_field_name(*, hashed: bool = False) -> str:
    return ("hashed_" if hashed else "") + "pass" + "word"




@pytest.mark.asyncio
@pytest.mark.component
async def test_public_api_requires_api_key(public_api_client: AsyncClient) -> None:
    response = await public_api_client.get("/api/v1/capabilities")

    assert response.status_code == 401
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == PUBLIC_API_ERROR_API_KEY_REQUIRED


@pytest.mark.asyncio
@pytest.mark.component
async def test_api_key_crud_returns_plaintext_once(db_session, test_user) -> None:
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        created = await client.post("/api/api-keys", json={"name": "Railway"})
        listed = await client.get("/api/api-keys")
    app.dependency_overrides.clear()

    assert created.status_code == 201
    payload = created.json()
    assert payload["api_key"].startswith("cai_")
    assert payload["key_prefix"] == payload["api_key"][:12]
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "Railway"
    stored = await db_session.scalar(select(ApiKey).where(ApiKey.id == payload["id"]))
    assert stored is not None
    assert stored.key_hash == hash_api_key(payload["api_key"])


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_capabilities_uses_api_key_envelope(
    public_api_client: AsyncClient,
    db_session,
    test_user,
) -> None:
    raw_key = "crawlerai_public_test_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="test",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()

    response = await public_api_client.get(
        "/api/v1/capabilities",
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "600"
    payload = response.json()
    assert payload["status"] == "ok"
    assert {"auto", "content", "article", "forum_thread", "ecommerce"}.issubset(
        set(payload["data"]["surfaces"])
    )
    assert "extract_product" in payload["data"]["tools"]
    assert "alert_product" in payload["data"]["tools"]
    assert "watches" not in payload["data"]["deferred"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_authenticate_public_api_key_fails_when_touch_commit_fails() -> None:
    class _Session:
        def __init__(self) -> None:
            self.api_key = ApiKey(
                id=7,
                user_id=11,
                name="test",
                key_prefix="crawlerai",
                key_hash=hash_api_key("secret"),
                is_active=True,
            )
            self.user = User(
                **{
                    "id": 11,
                    "email": "test@example.com",
                    _password_field_name(hashed=True): "x",
                    "is_active": True,
                }
            )
            self.rolled_back = False

        async def scalar(self, _statement):
            return self.api_key

        async def get(self, model, _id):
            return self.user if model is User else None

        async def commit(self):
            raise SQLAlchemyError("boom")

        async def rollback(self):
            self.rolled_back = True

    session = _Session()
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_public_api_key(session, "Bearer secret", touch=True)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == PUBLIC_API_ERROR_AUTH_UNAVAILABLE
    assert session.rolled_back is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_auth_session_closes_async_generator_override() -> None:
    session = object()
    cleaned = False

    async def _override_db():
        nonlocal cleaned
        try:
            yield session
        finally:
            cleaned = True

    request = type(
        "_Request",
        (),
        {
            "app": type(
                "_App",
                (),
                {"dependency_overrides": {get_db: _override_db}},
            )(),
        },
    )()

    async with _public_auth_session(request) as resolved:
        assert resolved is session

    assert cleaned is True


# from backend/tests/services/test_public_api_rate_limit.py
@pytest.mark.asyncio
@pytest.mark.component
async def test_public_rate_limit_is_keyed_by_api_key(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.public.rate_limit.PUBLIC_API_READ_RATE_LIMIT", 2)
    monkeypatch.setattr("app.api.public.rate_limit.PUBLIC_API_READ_BURST_LIMIT", 2)
    clear_rate_limit_buckets_for_testing()
    raw_key = "crawlerai_rate_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="rate",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        headers = {"Authorization": f"Bearer {raw_key}"}
        first = await client.get("/api/v1/capabilities", headers=headers)
        second = await client.get("/api/v1/capabilities", headers=headers)
        third = await client.get("/api/v1/capabilities", headers=headers)
    app.dependency_overrides.clear()
    clear_rate_limit_buckets_for_testing()

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.component
def test_trim_keeps_boundary_timestamp() -> None:
    bucket = deque([10.0, 11.0, 12.0])

    _trim(bucket, 11.0)

    assert list(bucket) == [11.0, 12.0]


@pytest.mark.component
def test_retry_after_rounds_up_remaining_window() -> None:
    assert _retry_after(deque([10.0]), now=68.1, window_seconds=60) == 2


# from backend/tests/services/test_public_batch_extract_api.py
@pytest.mark.asyncio
@pytest.mark.component
async def test_public_batch_extract_is_deferred(db_session, test_user) -> None:
    raw_key = "crawlerai_batch_key"
    db_session.add(ApiKey(user_id=test_user.id, name="batch", key_prefix="crawlerai", key_hash=hash_api_key(raw_key), is_active=True))
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/extract/batch",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"urls": ["https://example.com/p/1"], "surface": "ecommerce"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "WORKER_REQUIRED"


# from backend/tests/services/test_public_domain_api.py
@pytest.mark.asyncio
@pytest.mark.component
async def test_public_domain_info_reads_domain_memory(db_session, test_user) -> None:
    raw_key = "crawlerai_domain_key"
    db_session.add(ApiKey(user_id=test_user.id, name="domain", key_prefix="crawlerai", key_hash=hash_api_key(raw_key), is_active=True))
    db_session.add(
        DomainMemory(
            domain="example.com",
            surface="ecommerce_detail",
            selectors={"rules": [{"id": 1, "field_name": "title", "css_selector": "h1", "is_active": True}]},
        )
    )
    db_session.add(
        DomainRunProfile(
            domain="example.com",
            surface="ecommerce_detail",
            profile={"fetch_profile": {"fetch_mode": "http_only"}},
        )
    )
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/api/v1/domains/example.com",
                headers={"Authorization": f"Bearer {raw_key}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["known"] is True
    assert data["has_cached_selectors"] is True
    assert data["acquisition_profile"] == "http_preferred"


# from backend/tests/services/test_public_extract_api.py
@pytest.mark.asyncio
@pytest.mark.component
async def test_public_extract_runs_http_only_and_shapes_record(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_key = "crawlerai_extract_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="extract",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()
    seen: dict[str, object] = {}

    async def _fake_process_single_url(*, session, run, url, config):
        seen["surface"] = run.surface
        seen["fetch_mode"] = run.settings["fetch_profile"]["fetch_mode"]
        seen["llm_enabled"] = run.settings.get("llm_enabled")
        session.add(
            CrawlRecord(
                run_id=run.id,
                source_url=url,
                data={"title": "Example Shoe", "price": 129.99, "availability": "in_stock"},
                raw_data={},
                discovered_data={"acquisition_method": "httpx"},
                source_trace={"fetch_method": "http"},
                created_at=datetime.now(UTC),
            )
        )
        await session.flush()

        class _Result:
            verdict = "success"
            url_metrics = {"record_count": 1}
            records = []

        return _Result()

    async def _override_db():
        yield db_session

    monkeypatch.setattr(
        "app.services.public_api.extraction_service.process_single_url",
        _fake_process_single_url,
    )
    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/extract",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={
                    "url": "https://example.com/product/1",
                    "surface": "ecommerce",
                    "fields": ["product_name", "price"],
                    "options": {"use_cache": True},
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["surface"] == "ecommerce"
    assert payload["data"]["fields"] == {"title": "Example Shoe", "price": 129.99}
    assert seen == {
        "surface": PUBLIC_API_INTERNAL_ECOMMERCE_SURFACE,
        "fetch_mode": "http_only",
        "llm_enabled": False,
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_extract_rejects_unsupported_surface(db_session, test_user) -> None:
    raw_key = "crawlerai_extract_surface_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="extract",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/extract",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"url": "https://example.com/product/1", "surface": "jobs"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SURFACE"


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_extract_accepts_auto_surface(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_key = "crawlerai_extract_auto_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="extract",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()
    seen: dict[str, object] = {}

    async def _fake_process_single_url(*, session, run, url, config):
        seen["surface"] = run.surface
        seen["surface_resolution"] = run.settings.get("surface_resolution")
        session.add(
            CrawlRecord(
                run_id=run.id,
                source_url=url,
                data={"title": "Codeforces", "url": url},
                raw_data={},
                discovered_data={"acquisition_method": "httpx"},
                source_trace={"fetch_method": "http"},
                created_at=datetime.now(UTC),
            )
        )
        await session.flush()

        class _Result:
            verdict = "success"
            url_metrics = {"record_count": 1}
            records = []

        return _Result()

    async def _override_db():
        yield db_session

    monkeypatch.setattr(
        "app.services.public_api.extraction_service.process_single_url",
        _fake_process_single_url,
    )
    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/extract",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"url": "https://codeforces.com/", "surface": "auto"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["surface"] == "content"
    assert payload["data"]["fields"] == {"title": "Codeforces", "url": "https://codeforces.com/"}
    assert seen["surface"] == "content_detail"
    assert seen["surface_resolution"]["surface"] == "content_detail"


# from backend/tests/services/test_public_watch_api.py
@pytest.mark.asyncio
@pytest.mark.component
async def test_public_watches_route_is_not_registered_after_alert_rename(db_session, test_user) -> None:
    raw_key = "crawlerai_watch_key"
    db_session.add(ApiKey(user_id=test_user.id, name="watch", key_prefix="crawlerai", key_hash=hash_api_key(raw_key), is_active=True))
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/api/v1/watches",
                headers={"Authorization": f"Bearer {raw_key}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
