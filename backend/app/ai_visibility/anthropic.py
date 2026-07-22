"""Native Anthropic Messages API adapter with server-side web search.

Calls the Anthropic Messages API directly (no OpenRouter hop) using Claude's
first-party ``web_search`` server tool for grounding. Mirrors the OpenRouter
adapter's shape: build payload -> POST -> map HTTP/transport errors to
``AiVisibilityProviderError`` -> hand the JSON to the parser.
"""

from __future__ import annotations

from typing import Any

from app.ai_visibility._provider_http import _execute_post
from app.ai_visibility.anthropic_parser import parse_anthropic_message
from app.ai_visibility.contracts import AnswerEngineRequest, AnswerEngineResponse
from app.ai_visibility.gemini import AiVisibilityProviderError
from app.core.config.ai_visibility import (
    AI_VISIBILITY_ERROR_RATE_LIMIT,
    AI_VISIBILITY_ERROR_SERVER,
    AI_VISIBILITY_PROVIDER_ANTHROPIC,
    ai_visibility_settings,
)

# Basic web search tool. Sufficient for a single grounded answer turn; dynamic
# filtering / code execution is unnecessary here.
_WEB_SEARCH_TOOL_TYPE = "web_search_20250305"

# In-body web_search_tool_result_error codes worth retrying. The Messages API
# returns HTTP 200 even when a search fails, embedding the error in the content.
_RETRYABLE_SEARCH_ERRORS = {
    "too_many_requests": AI_VISIBILITY_ERROR_RATE_LIMIT,
    "unavailable": AI_VISIBILITY_ERROR_SERVER,
}


def _payload(request: AnswerEngineRequest, *, country_code: str) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "type": _WEB_SEARCH_TOOL_TYPE,
        "name": "web_search",
        "max_uses": ai_visibility_settings.anthropic_max_uses,
    }
    if country_code:
        tool["user_location"] = {"type": "approximate", "country": country_code}
    payload: dict[str, Any] = {
        "model": request.model,
        "max_tokens": ai_visibility_settings.max_output_tokens,
        "messages": [{"role": "user", "content": request.prompt}],
        "tools": [tool],
    }
    # Anthropic takes the system prompt as a top-level field, not a message.
    if request.system_instruction:
        payload["system"] = request.system_instruction
    return payload


def _raise_for_search_error(payload: dict[str, Any]) -> None:
    """Surface retryable in-body web_search failures as provider errors.

    The Messages API embeds search failures in a ``web_search_tool_result`` block
    whose ``content`` is a single ``web_search_tool_result_error`` object (rather
    than a list of results). Rate-limit / unavailable errors should retry;
    ``max_uses_exceeded`` and the like are non-fatal (partial answer still parses).
    """
    for block in payload.get("content") or []:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") != "web_search_tool_result":
            continue
        content = block.get("content")
        if not isinstance(content, dict):
            continue
        if str(content.get("type") or "") != "web_search_tool_result_error":
            continue
        code = str(content.get("error_code") or "")
        mapped = _RETRYABLE_SEARCH_ERRORS.get(code)
        if mapped is not None:
            raise AiVisibilityProviderError(
                f"Anthropic web_search failed: {code}",
                error_code=mapped,
                retryable=True,
            )


class AnthropicAnswerEngineAdapter:
    provider_id = AI_VISIBILITY_PROVIDER_ANTHROPIC

    def __init__(self, *, api_key: str, country_code: str = "") -> None:
        if not api_key:
            raise AiVisibilityProviderError(
                "Anthropic API key is not configured",
                error_code="auth_failure",
                retryable=False,
            )
        self._api_key = api_key
        self._country_code = country_code

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        payload, latency_ms = await _execute_post(
            provider_label="Anthropic",
            url=ai_visibility_settings.anthropic_messages_url,
            payload=_payload(request, country_code=self._country_code),
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": ai_visibility_settings.anthropic_version,
                "content-type": "application/json",
            },
            timeout_seconds=request.timeout_seconds,
        )
        _raise_for_search_error(payload)
        return parse_anthropic_message(
            payload,
            provider=self.provider_id,
            requested_model=request.model,
            latency_ms=latency_ms,
        )
