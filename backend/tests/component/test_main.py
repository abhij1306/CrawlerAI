from __future__ import annotations

import pytest

from fastapi import Request
from fastapi.responses import Response

from app.core.telemetry import install_asyncio_exception_filter
from app.main import (
    sanitize_header_name,
    sanitize_header_value,
    correlation_middleware,
    lifespan,
)


@pytest.mark.component
async def test_correlation_middleware_strips_crlf_from_request_id_header(
    monkeypatch,
) -> None:
    async def _call_next(request: Request) -> Response:
        assert request is not None
        return Response(status_code=204)

    monkeypatch.setattr("app.main.settings.request_id_header", "X-Request-ID")

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-request-id", b"abc\r\nx-injected: 1")],
        }
    )

    response = await correlation_middleware(request, _call_next)

    assert response.headers["X-Request-ID"] == "abcx-injected: 1"


@pytest.mark.component
async def test_correlation_middleware_strips_crlf_from_configured_header_name(
    monkeypatch,
) -> None:
    async def _call_next(request: Request) -> Response:
        assert request is not None
        return Response(status_code=204)

    monkeypatch.setattr(
        "app.main.settings.request_id_header", "X-Request-ID\r\nSet-Cookie"
    )

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-request-idset-cookie", b"req-123")],
        }
    )

    response = await correlation_middleware(request, _call_next)

    assert response.headers["X-Request-ID"] != ""


@pytest.mark.component
async def test_correlation_middleware_falls_back_for_invalid_configured_header_name(
    monkeypatch,
) -> None:
    async def _call_next(request: Request) -> Response:
        assert request is not None
        return Response(status_code=204)

    monkeypatch.setattr("app.main.settings.request_id_header", "X-Request-ID:Bad")

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-request-id", b"req-123")],
        }
    )

    response = await correlation_middleware(request, _call_next)

    assert response.headers["X-Request-ID"] == "req-123"


@pytest.mark.component
def test_sanitize_header_value_removes_crlf_characters() -> None:
    assert sanitize_header_value("abc\r\ndef\nxyz") == "abcdefxyz"


@pytest.mark.component
def test_sanitize_header_value_preserves_safe_content() -> None:
    assert sanitize_header_value("req-123_ABC") == "req-123_ABC"


@pytest.mark.component
def test_sanitize_header_name_rejects_invalid_tokens() -> None:
    assert sanitize_header_name("X-Request-ID:Bad") == "X-Request-ID"


@pytest.mark.component
def test_install_asyncio_exception_filter_suppresses_known_pipe_reset() -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self.handler = None
            self.default_calls: list[object] = []

        def get_exception_handler(self):
            return None

        def set_exception_handler(self, handler) -> None:
            self.handler = handler

        def default_exception_handler(self, context) -> None:
            self.default_calls.append(context)

    loop = FakeLoop()
    install_asyncio_exception_filter(loop)  # type: ignore[arg-type]

    assert loop.handler is not None

    loop.handler(
        loop,
        {
            "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
            "exception": ConnectionResetError(
                10054,
                "An existing connection was forcibly closed by the remote host",
            ),
        },
    )

    assert loop.default_calls == []


@pytest.mark.component
def test_install_asyncio_exception_filter_delegates_unknown_errors() -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self.handler = None
            self.default_calls: list[object] = []

        def get_exception_handler(self):
            return None

        def set_exception_handler(self, handler) -> None:
            self.handler = handler

        def default_exception_handler(self, context) -> None:
            self.default_calls.append(context)

    loop = FakeLoop()
    install_asyncio_exception_filter(loop)  # type: ignore[arg-type]

    context = {
        "message": "Exception in callback something_else()",
        "exception": RuntimeError("boom"),
    }
    loop.handler(loop, context)

    assert loop.default_calls == [context]


@pytest.mark.component
def test_install_asyncio_exception_filter_preserves_original_context_for_previous_handler() -> (
    None
):
    previous_calls: list[object] = []

    class FakeLoop:
        def __init__(self) -> None:
            self.handler = None

        def get_exception_handler(self):
            return lambda inner_loop, context: previous_calls.append(
                (inner_loop, context)
            )

        def set_exception_handler(self, handler) -> None:
            self.handler = handler

        def default_exception_handler(self, context) -> None:
            raise AssertionError("default handler should not run")

    loop = FakeLoop()
    install_asyncio_exception_filter(loop)  # type: ignore[arg-type]

    context = {
        "message": "Exception in callback something_else()",
        "exception": RuntimeError("boom"),
    }
    loop.handler(loop, context)

    assert previous_calls == [(loop, context)]


@pytest.mark.component
async def test_lifespan_creates_schema_before_bootstrap(monkeypatch) -> None:
    calls: list[str] = []

    class SessionContext:
        async def __aenter__(self):
            calls.append("session")
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def _schema() -> None:
        calls.append("schema")

    async def _bootstrap(_session) -> None:
        calls.append("bootstrap")

    async def _recover(_session) -> int:
        calls.append("recover")
        return 0

    async def _noop_async() -> None:
        return None

    monkeypatch.setattr("app.main.ensure_database_schema", _schema)
    monkeypatch.setattr("app.main.SessionLocal", lambda: SessionContext())
    monkeypatch.setattr("app.main.bootstrap_admin_user", _bootstrap)
    monkeypatch.setattr("app.main.recover_stale_local_runs", _recover)
    monkeypatch.setattr(
        "app.main.ensure_run_audit_registered", lambda: calls.append("audit")
    )
    monkeypatch.setattr("app.main.shutdown_run_dispatchers", _noop_async)
    monkeypatch.setattr("app.main.shutdown_browser_runtime", _noop_async)
    monkeypatch.setattr("app.main.close_runtime_http_client", _noop_async)
    monkeypatch.setattr("app.main.close_llm_provider_clients", _noop_async)
    monkeypatch.setattr("app.main.close_redis", _noop_async)
    monkeypatch.setattr("app.main.dispose_engine", _noop_async)

    async with lifespan(None):
        calls.append("yield")

    assert calls[:5] == ["schema", "session", "bootstrap", "recover", "audit"]
    assert "yield" in calls
