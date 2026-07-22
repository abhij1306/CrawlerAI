"""Gemini Interactions API adapter (Google Search grounding).

Each call is a fresh, stateless Interactions request:
  * ``store=false`` and no ``previous_interaction_id`` — no account/chat memory.
  * The tracked brand/competitor list is NEVER placed in the request; it is used
    only during scoring, after generation. The system instruction is fixed and
    neutral.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.ai_visibility._provider_http import (
    AiVisibilityProviderError,
    _execute_post,
    classify_provider_status,
)
from app.ai_visibility.contracts import AnswerEngineRequest, AnswerEngineResponse
from app.ai_visibility.gemini_parser import parse_interaction
from app.core.config.ai_visibility import (
    AI_VISIBILITY_ERROR_AUTH,
    AI_VISIBILITY_PROVIDER_GEMINI,
    AI_VISIBILITY_RETRYABLE_ERRORS,
    ai_visibility_settings,
)

# Re-exported: the neutral owner is ``_provider_http`` (audit 3.10), but the
# runner, the other adapters, and tests import these from here.
__all__ = ["AiVisibilityProviderError", "classify_provider_status"]

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_client_timeout: float | None = None
_client_lock = asyncio.Lock()


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header into seconds.

    Handles the numeric (delta-seconds) form that Gemini sends. The HTTP-date
    form is uncommon here and intentionally ignored (returns ``None``) so the
    caller falls back to exponential backoff rather than misparsing.
    """
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def safe_quota_detail(payload: dict[str, Any]) -> str:
    """Extract provider quota identifiers without retaining echoed request text."""
    error = payload.get("error") or {}
    parts = [str(error.get("status") or "").strip()]
    for detail in error.get("details") or []:
        if not isinstance(detail, dict):
            continue
        retry_delay = str(detail.get("retryDelay") or "").strip()
        if retry_delay:
            parts.append(f"retry={retry_delay}")
        for violation in detail.get("violations") or []:
            if not isinstance(violation, dict):
                continue
            metric = str(violation.get("quotaMetric") or "").strip()
            quota_id = str(violation.get("quotaId") or "").strip()
            if metric:
                parts.append(f"quota={metric}")
            if quota_id:
                parts.append(f"quota_id={quota_id}")
    return "; ".join(part for part in parts if part)


async def _shared_client(timeout: float) -> httpx.AsyncClient:
    global _client, _client_timeout
    async with _client_lock:
        if _client is None or _client.is_closed or _client_timeout != timeout:
            if _client is not None and not _client.is_closed:
                await _client.aclose()
            _client = httpx.AsyncClient(timeout=timeout)
            _client_timeout = timeout
        return _client


def _build_payload(request: AnswerEngineRequest) -> dict[str, Any]:
    return {
        "model": request.model,
        "input": request.prompt,
        "system_instruction": request.system_instruction,
        "tools": [{"type": "google_search"}],
        "store": False,
        # Global per-call output cap so one generation cannot run away.
        "max_output_tokens": ai_visibility_settings.max_output_tokens,
    }


def _error_status_diagnostics(
    response: httpx.Response, error_code: str
) -> tuple[str, float | None]:
    """Gemini retry-after/quota diagnostics for the shared POST skeleton."""
    retry_after = _parse_retry_after(response.headers.get("retry-after"))
    # Never log the response body verbatim (could echo the request),
    # only the status and a short reason token.
    logger.warning(
        "ai_visibility gemini call failed",
        extra={"status": response.status_code, "error_code": error_code},
    )
    try:
        safe_detail = safe_quota_detail(response.json())
    except ValueError:
        safe_detail = ""
    return (f" ({safe_detail})" if safe_detail else ""), retry_after


class GeminiAnswerEngineAdapter:
    provider_id = AI_VISIBILITY_PROVIDER_GEMINI

    def __init__(self, *, api_key: str) -> None:
        if not api_key:
            raise AiVisibilityProviderError(
                "Gemini API key is not configured",
                error_code=AI_VISIBILITY_ERROR_AUTH,
                retryable=False,
            )
        self._api_key = api_key
        self._url = ai_visibility_settings.interactions_url

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        client = await _shared_client(request.timeout_seconds)
        data, latency_ms = await _execute_post(
            provider_label="Gemini",
            url=self._url,
            payload=_build_payload(request),
            headers={
                "x-goog-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            timeout_seconds=request.timeout_seconds,
            client=client,
            on_error_status=_error_status_diagnostics,
        )
        return parse_interaction(
            data,
            provider=self.provider_id,
            model=request.model,
            latency_ms=latency_ms,
        )


def is_retryable(error_code: str) -> bool:
    return error_code in AI_VISIBILITY_RETRYABLE_ERRORS


async def resolve_redirect(url: str, *, timeout: float | None = None) -> str | None:
    """Best-effort resolution of a grounding-redirect URL to its final page URL.

    The resolved hostname is the strongest citation-classification evidence.
    Any failure returns ``None`` and falls back to direct URL/title evidence.
    """
    if not url or "grounding-api-redirect" not in url:
        return url or None
    resolve_timeout = (
        timeout
        if timeout is not None
        else ai_visibility_settings.resolve_timeout_seconds
    )
    try:
        async with httpx.AsyncClient(
            timeout=resolve_timeout, follow_redirects=True
        ) as client:
            response = await client.get(url)
            return str(response.url)
    except httpx.HTTPError:
        return None
