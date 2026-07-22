"""OpenRouter adapter for OpenAI/Anthropic native provider web search."""

from __future__ import annotations

from typing import Any

from app.ai_visibility._provider_http import _execute_post
from app.ai_visibility.contracts import AnswerEngineRequest, AnswerEngineResponse
from app.ai_visibility.gemini import AiVisibilityProviderError
from app.ai_visibility.openrouter_parser import parse_openrouter_completion
from app.core.config.ai_visibility import (
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
        # Global per-call output cap so one generation cannot run away.
        "max_tokens": ai_visibility_settings.max_output_tokens,
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
        payload, latency_ms = await _execute_post(
            provider_label="OpenRouter",
            url=ai_visibility_settings.openrouter_chat_completions_url,
            payload=_payload(request, country_code=self._country_code),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "X-OpenRouter-Title": "CrawlerAI AI Visibility",
            },
            timeout_seconds=request.timeout_seconds,
        )
        return parse_openrouter_completion(
            payload,
            provider=self.provider_id,
            requested_model=request.model,
            latency_ms=latency_ms,
        )
