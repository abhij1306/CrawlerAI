from __future__ import annotations

# ruff: noqa: F403, F405
from .public_api_test_support import *
from .public_api_test_support import _crawler_app_state


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
                "Origin": "http://127.0.0.1:3001",
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
