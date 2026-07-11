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
import time
from typing import Any

import httpx

from app.ai_visibility.contracts import AnswerEngineRequest, AnswerEngineResponse
from app.ai_visibility.gemini_parser import parse_interaction
from app.core.config.ai_visibility import (
    AI_VISIBILITY_ERROR_AUTH,
    AI_VISIBILITY_ERROR_CLIENT,
    AI_VISIBILITY_ERROR_CONNECTION,
    AI_VISIBILITY_ERROR_RATE_LIMIT,
    AI_VISIBILITY_ERROR_SERVER,
    AI_VISIBILITY_ERROR_TIMEOUT,
    AI_VISIBILITY_ERROR_UNKNOWN,
    AI_VISIBILITY_PROVIDER_GEMINI,
    AI_VISIBILITY_RETRYABLE_ERRORS,
    ai_visibility_settings,
)

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_client_timeout: float | None = None
_client_lock = asyncio.Lock()


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


def classify_provider_status(status_code: int) -> tuple[str, bool]:
    if status_code == 429:
        return AI_VISIBILITY_ERROR_RATE_LIMIT, True
    if status_code in (500, 502, 503, 504):
        return AI_VISIBILITY_ERROR_SERVER, True
    if status_code in (401, 403):
        return AI_VISIBILITY_ERROR_AUTH, False
    return AI_VISIBILITY_ERROR_CLIENT, False


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


async def close_ai_visibility_client() -> None:
    global _client, _client_timeout
    async with _client_lock:
        if _client is not None and not _client.is_closed:
            await _client.aclose()
        _client = None
        _client_timeout = None


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
        payload = _build_payload(request)
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        started = time.monotonic()
        try:
            response = await client.post(self._url, json=payload, headers=headers)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
            raise AiVisibilityProviderError(
                f"Gemini request timed out: {exc}",
                error_code=AI_VISIBILITY_ERROR_TIMEOUT,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise AiVisibilityProviderError(
                f"Gemini connection error: {exc}",
                error_code=AI_VISIBILITY_ERROR_CONNECTION,
                retryable=True,
            ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            error_code, retryable = classify_provider_status(response.status_code)
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
            suffix = f" ({safe_detail})" if safe_detail else ""
            raise AiVisibilityProviderError(
                f"Gemini returned HTTP {response.status_code}{suffix}",
                error_code=error_code,
                retryable=retryable,
                retry_after_seconds=retry_after,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AiVisibilityProviderError(
                f"Gemini returned non-JSON response: {exc}",
                error_code=AI_VISIBILITY_ERROR_UNKNOWN,
                retryable=False,
            ) from exc

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
