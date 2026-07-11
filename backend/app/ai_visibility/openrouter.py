"""OpenRouter adapter for OpenAI/Anthropic native provider web search."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.ai_visibility.contracts import AnswerEngineRequest, AnswerEngineResponse
from app.ai_visibility.gemini import AiVisibilityProviderError, classify_provider_status
from app.ai_visibility.openrouter_parser import parse_openrouter_completion
from app.core.config.ai_visibility import (
    AI_VISIBILITY_ERROR_CONNECTION,
    AI_VISIBILITY_ERROR_TIMEOUT,
    AI_VISIBILITY_ERROR_UNKNOWN,
    AI_VISIBILITY_ERROR_INVALID_SURFACE,
    AI_VISIBILITY_PROVIDER_OPENROUTER_ANTHROPIC,
    AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI,
    ai_visibility_settings,
)

_OPENROUTER_PROVIDERS = frozenset(
    {
        AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI,
        AI_VISIBILITY_PROVIDER_OPENROUTER_ANTHROPIC,
    }
)


def _payload(request: AnswerEngineRequest, *, country_code: str) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if request.system_instruction:
        messages.append({"role": "system", "content": request.system_instruction})
    messages.append({"role": "user", "content": request.prompt})
    location: dict[str, str] = {"type": "approximate"}
    if country_code:
        location["country"] = country_code
    return {
        "model": request.model,
        "messages": messages,
        "tools": [
            {
                "type": "openrouter:web_search",
                "parameters": {
                    "engine": "native",
                    "user_location": location,
                },
            }
        ],
        "stream": False,
    }


def _native_model_matches_surface(provider_id: str, model: str) -> bool:
    normalized = model.lower()
    if provider_id == AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI:
        return normalized.startswith(
            ("openai/gpt-5", "openai/gpt-4.1", "openai/o3", "openai/o4")
        )
    return normalized.startswith("anthropic/claude-") and any(
        token in normalized
        for token in ("3.5-haiku", "3.7-sonnet", "sonnet-4", "opus-4")
    )


class OpenRouterAnswerEngineAdapter:
    def __init__(
        self, *, api_key: str, provider_id: str, country_code: str = ""
    ) -> None:
        if provider_id not in _OPENROUTER_PROVIDERS:
            raise ValueError(f"Unsupported OpenRouter provider: {provider_id}")
        if not api_key:
            raise AiVisibilityProviderError(
                "OpenRouter API key is not configured",
                error_code="auth_failure",
                retryable=False,
            )
        self.provider_id = provider_id
        self._api_key = api_key
        self._country_code = country_code

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        if not _native_model_matches_surface(self.provider_id, request.model):
            raise AiVisibilityProviderError(
                f"Model is not approved for native search: {request.model}",
                error_code=AI_VISIBILITY_ERROR_INVALID_SURFACE,
                retryable=False,
            )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": "CrawlerAI AI Visibility",
        }
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    ai_visibility_settings.openrouter_chat_completions_url,
                    json=_payload(request, country_code=self._country_code),
                    headers=headers,
                )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
            raise AiVisibilityProviderError(
                f"OpenRouter request timed out: {exc}",
                error_code=AI_VISIBILITY_ERROR_TIMEOUT,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise AiVisibilityProviderError(
                f"OpenRouter connection error: {exc}",
                error_code=AI_VISIBILITY_ERROR_CONNECTION,
                retryable=True,
            ) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            error_code, retryable = classify_provider_status(response.status_code)
            raise AiVisibilityProviderError(
                f"OpenRouter returned HTTP {response.status_code}",
                error_code=error_code,
                retryable=retryable,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AiVisibilityProviderError(
                f"OpenRouter returned non-JSON response: {exc}",
                error_code=AI_VISIBILITY_ERROR_UNKNOWN,
                retryable=False,
            ) from exc
        return parse_openrouter_completion(
            payload,
            provider=self.provider_id,
            requested_model=request.model,
            latency_ms=latency_ms,
        )
