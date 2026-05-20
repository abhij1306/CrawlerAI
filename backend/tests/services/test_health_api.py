from __future__ import annotations

from collections import OrderedDict, deque

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

import app.main as main_module
from app.main import (
    CrawlerAppState,
    RATE_LIMIT_BUCKETS,
    clear_rate_limit_buckets_for_testing,
    client_rate_limit_key,
    rate_limit_buckets_snapshot,
    restore_rate_limit_buckets_for_testing,
    app,
)
from app.services.config.runtime_settings import crawler_runtime_settings


@pytest.mark.asyncio
async def test_live_health_endpoint_is_lightweight() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


@pytest.mark.asyncio
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


def test_crawler_app_state_rejects_explicit_app_without_crawler_state() -> None:
    with pytest.raises(RuntimeError, match="state.crawler"):
        main_module._crawler_app_state(FastAPI())
