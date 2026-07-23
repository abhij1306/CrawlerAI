"""Shared provider HTTP POST skeleton for answer-engine adapters.

Owns the timeout/error-mapping/status-classify skeleton the Anthropic,
OpenRouter, and Gemini adapters previously triplicated (audit 3.10): monotonic
timing, the httpx POST, timeout/transport/non-JSON error mapping to
``AiVisibilityProviderError``, and error-status classification. Provider-
specific payload building, auth headers, response parsing, and diagnostics
stay in the adapters; provider-specific error-status diagnostics (Gemini's
retry-after/quota detail) attach via the optional ``on_error_status`` hook.

``AiVisibilityProviderError`` and ``classify_provider_status`` also live here
as the neutral owner — the adapters and this skeleton all need them, and
keeping them in ``gemini`` would make this module's import cyclic.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config.ai_visibility import (
    AI_VISIBILITY_ERROR_AUTH,
    AI_VISIBILITY_ERROR_CLIENT,
    AI_VISIBILITY_ERROR_CONNECTION,
    AI_VISIBILITY_ERROR_RATE_LIMIT,
    AI_VISIBILITY_ERROR_SERVER,
    AI_VISIBILITY_ERROR_TIMEOUT,
    AI_VISIBILITY_ERROR_UNKNOWN,
)


class AiVisibilityProviderError(RuntimeError):
    """Raised when a provider call fails. Carries a retry classification."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        retryable: bool,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
        # Provider-advised wait (from a Retry-After header), when present. The
        # runner prefers this over blind exponential backoff.
        self.retry_after_seconds = retry_after_seconds


def classify_provider_status(status_code: int) -> tuple[str, bool]:
    if status_code == 429:
        return AI_VISIBILITY_ERROR_RATE_LIMIT, True
    if status_code in (500, 502, 503, 504):
        return AI_VISIBILITY_ERROR_SERVER, True
    if status_code in (401, 403):
        return AI_VISIBILITY_ERROR_AUTH, False
    return AI_VISIBILITY_ERROR_CLIENT, False


async def _execute_post(
    *,
    provider_label: str,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
    on_error_status: Callable[[httpx.Response, str], tuple[str, float | None]]
    | None = None,
) -> tuple[Any, int]:
    """POST ``payload`` and return ``(decoded_json, latency_ms)``.

    Maps transport/timeout/decode failures and error statuses to
    ``AiVisibilityProviderError`` with the shared classification. ``client``
    injects a shared/long-lived client (Gemini); otherwise a per-call client
    bounded by ``timeout_seconds`` is created. ``on_error_status`` receives
    the error response plus its classified ``error_code`` and returns a
    ``(message_suffix, retry_after_seconds)`` pair for provider diagnostics.
    """
    started = time.monotonic()
    try:
        if client is not None:
            response = await client.post(url, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=timeout_seconds) as session:
                response = await session.post(url, json=payload, headers=headers)
    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
        raise AiVisibilityProviderError(
            f"{provider_label} request timed out: {exc}",
            error_code=AI_VISIBILITY_ERROR_TIMEOUT,
            retryable=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise AiVisibilityProviderError(
            f"{provider_label} connection error: {exc}",
            error_code=AI_VISIBILITY_ERROR_CONNECTION,
            retryable=True,
        ) from exc
    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code >= 400:
        error_code, retryable = classify_provider_status(response.status_code)
        message_suffix = ""
        retry_after_seconds = None
        if on_error_status is not None:
            message_suffix, retry_after_seconds = on_error_status(
                response, error_code
            )
        raise AiVisibilityProviderError(
            f"{provider_label} returned HTTP {response.status_code}{message_suffix}",
            error_code=error_code,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
        )
    try:
        return response.json(), latency_ms
    except ValueError as exc:
        raise AiVisibilityProviderError(
            f"{provider_label} returned non-JSON response: {exc}",
            error_code=AI_VISIBILITY_ERROR_UNKNOWN,
            retryable=False,
        ) from exc
