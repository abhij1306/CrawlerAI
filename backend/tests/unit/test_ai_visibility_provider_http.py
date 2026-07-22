"""Shared ai_visibility provider POST skeleton (audit 3.10).

Covers the timeout/transport/non-JSON/error-status mapping the Anthropic,
OpenRouter, and Gemini adapters now share via ``_provider_http._execute_post``,
plus the optional error-status hook Gemini uses for retry-after/quota detail.
"""

from __future__ import annotations

import httpx
import pytest

from app.ai_visibility import _provider_http
from app.ai_visibility._provider_http import (
    AiVisibilityProviderError,
    _execute_post,
)
from app.core.config.ai_visibility import (
    AI_VISIBILITY_ERROR_AUTH,
    AI_VISIBILITY_ERROR_CLIENT,
    AI_VISIBILITY_ERROR_CONNECTION,
    AI_VISIBILITY_ERROR_RATE_LIMIT,
    AI_VISIBILITY_ERROR_SERVER,
    AI_VISIBILITY_ERROR_TIMEOUT,
    AI_VISIBILITY_ERROR_UNKNOWN,
)

pytestmark = pytest.mark.unit

_URL = "https://provider.example/v1/generate"


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_success_returns_payload_and_latency() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == _URL
        assert request.headers["x-test"] == "yes"
        return httpx.Response(200, json={"answer": "ok"})

    async with _mock_client(handler) as client:
        payload, latency_ms = await _execute_post(
            provider_label="Gemini",
            url=_URL,
            payload={"input": "hi"},
            headers={"x-test": "yes"},
            timeout_seconds=5,
            client=client,
        )
    assert payload == {"answer": "ok"}
    assert latency_ms >= 0


async def test_timeout_maps_to_retryable_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with _mock_client(handler) as client:
        with pytest.raises(AiVisibilityProviderError) as excinfo:
            await _execute_post(
                provider_label="Anthropic",
                url=_URL,
                payload={},
                headers={},
                timeout_seconds=5,
                client=client,
            )
    assert excinfo.value.error_code == AI_VISIBILITY_ERROR_TIMEOUT
    assert excinfo.value.retryable is True
    assert "Anthropic request timed out" in str(excinfo.value)


async def test_transport_error_maps_to_retryable_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with _mock_client(handler) as client:
        with pytest.raises(AiVisibilityProviderError) as excinfo:
            await _execute_post(
                provider_label="OpenRouter",
                url=_URL,
                payload={},
                headers={},
                timeout_seconds=5,
                client=client,
            )
    assert excinfo.value.error_code == AI_VISIBILITY_ERROR_CONNECTION
    assert excinfo.value.retryable is True
    assert "OpenRouter connection error" in str(excinfo.value)


async def test_non_json_maps_to_non_retryable_unknown_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>oops</html>")

    async with _mock_client(handler) as client:
        with pytest.raises(AiVisibilityProviderError) as excinfo:
            await _execute_post(
                provider_label="Gemini",
                url=_URL,
                payload={},
                headers={},
                timeout_seconds=5,
                client=client,
            )
    assert excinfo.value.error_code == AI_VISIBILITY_ERROR_UNKNOWN
    assert excinfo.value.retryable is False
    assert "Gemini returned non-JSON response" in str(excinfo.value)


@pytest.mark.parametrize(
    ("status_code", "expected_code", "expected_retryable"),
    [
        (429, AI_VISIBILITY_ERROR_RATE_LIMIT, True),
        (503, AI_VISIBILITY_ERROR_SERVER, True),
        (403, AI_VISIBILITY_ERROR_AUTH, False),
        (400, AI_VISIBILITY_ERROR_CLIENT, False),
    ],
)
async def test_error_status_classification(
    status_code: int, expected_code: str, expected_retryable: bool
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "bad"})

    async with _mock_client(handler) as client:
        with pytest.raises(AiVisibilityProviderError) as excinfo:
            await _execute_post(
                provider_label="Anthropic",
                url=_URL,
                payload={},
                headers={},
                timeout_seconds=5,
                client=client,
            )
    assert excinfo.value.error_code == expected_code
    assert excinfo.value.retryable is expected_retryable
    assert excinfo.value.retry_after_seconds is None
    assert str(excinfo.value) == f"Anthropic returned HTTP {status_code}"


async def test_error_status_hook_appends_detail_and_retry_after() -> None:
    seen: list[tuple[int, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"status": "RESOURCE_EXHAUSTED"}},
            headers={"retry-after": "12.5"},
        )

    def hook(response: httpx.Response, error_code: str) -> tuple[str, float | None]:
        seen.append((response.status_code, error_code))
        return " (quota=x)", 12.5

    async with _mock_client(handler) as client:
        with pytest.raises(AiVisibilityProviderError) as excinfo:
            await _execute_post(
                provider_label="Gemini",
                url=_URL,
                payload={},
                headers={},
                timeout_seconds=5,
                client=client,
                on_error_status=hook,
            )
    assert seen == [(429, AI_VISIBILITY_ERROR_RATE_LIMIT)]
    assert excinfo.value.retry_after_seconds == 12.5
    assert str(excinfo.value) == "Gemini returned HTTP 429 (quota=x)"


async def test_per_call_client_created_with_timeout(monkeypatch) -> None:
    created: list[dict[str, object]] = []

    class _TrackingClient(httpx.AsyncClient):
        def __init__(self, **kwargs) -> None:
            created.append(kwargs)
            super().__init__(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"ok": True})
                )
            )

    monkeypatch.setattr(_provider_http.httpx, "AsyncClient", _TrackingClient)
    payload, _ = await _execute_post(
        provider_label="OpenRouter",
        url=_URL,
        payload={},
        headers={},
        timeout_seconds=7,
    )
    assert payload == {"ok": True}
    assert created == [{"timeout": 7}]


async def test_gemini_execute_maps_429_with_retry_after_and_quota_detail(
    monkeypatch, caplog
) -> None:
    """End-to-end through the Gemini adapter: hook keeps 429 diagnostics."""
    from app.ai_visibility import gemini
    from app.ai_visibility.contracts import AnswerEngineRequest

    quota_body = {
        "error": {
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "retryDelay": "12s",
                    "violations": [
                        {"quotaMetric": "generate_requests", "quotaId": "per-minute"}
                    ],
                }
            ],
        }
    }

    async def _shared_client_override(timeout: float) -> httpx.AsyncClient:
        return _mock_client(
            lambda request: httpx.Response(
                429, json=quota_body, headers={"retry-after": "12"}
            )
        )

    monkeypatch.setattr(gemini, "_shared_client", _shared_client_override)
    adapter = gemini.GeminiAnswerEngineAdapter(api_key="test-key")
    request = AnswerEngineRequest(
        prompt="best baby clothes",
        system_instruction="Answer.",
        model="gemini-3-flash",
        timeout_seconds=5,
    )
    with caplog.at_level("WARNING", logger="app.ai_visibility.gemini"):
        with pytest.raises(AiVisibilityProviderError) as excinfo:
            await adapter.execute(request)
    assert excinfo.value.error_code == AI_VISIBILITY_ERROR_RATE_LIMIT
    assert excinfo.value.retryable is True
    assert excinfo.value.retry_after_seconds == 12.0
    message = str(excinfo.value)
    assert message.startswith("Gemini returned HTTP 429 (")
    assert "quota=generate_requests" in message
    assert "quota_id=per-minute" in message
    assert any(
        record.status == 429 and record.error_code == AI_VISIBILITY_ERROR_RATE_LIMIT  # type: ignore[attr-defined]
        for record in caplog.records
    )
