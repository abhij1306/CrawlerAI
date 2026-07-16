"""Global guardrails: per-call output cap, hard per-call timeout, run deadline.

These knobs are provider-agnostic (one set of settings for every provider) so a
stray or misused call cannot run away in tokens, time, or duration.
"""

from __future__ import annotations

import asyncio

import pytest

from app.ai_visibility.anthropic import _payload as anthropic_payload
from app.ai_visibility.contracts import AnswerEngineRequest
from app.ai_visibility.gemini import (
    AiVisibilityProviderError,
    _build_payload as gemini_payload,
)
from app.ai_visibility.openrouter import _payload as openrouter_payload
from app.ai_visibility.runner import _call_with_retries
from app.core.config.ai_visibility import (
    AI_VISIBILITY_ERROR_TIMEOUT,
    ai_visibility_settings,
)

pytestmark = pytest.mark.unit


def _request() -> AnswerEngineRequest:
    return AnswerEngineRequest(
        prompt="cheap baby clothes",
        system_instruction="Answer for Australia.",
        model="claude-sonnet-4-6",
        timeout_seconds=30,
    )


def test_every_provider_payload_caps_output_tokens() -> None:
    cap = ai_visibility_settings.max_output_tokens
    # One global cap; each provider expresses it in its own field name.
    assert anthropic_payload(_request(), country_code="AU")["max_tokens"] == cap
    assert openrouter_payload(_request(), country_code="AU")["max_tokens"] == cap
    assert gemini_payload(_request())["max_output_tokens"] == cap


class _StallingAdapter:
    """Adapter whose call never returns; the wait_for ceiling must cut it off."""

    provider_id = "gemini"

    async def execute(self, request: AnswerEngineRequest):  # pragma: no cover
        await asyncio.sleep(3600)


class _CountingStallAdapter(_StallingAdapter):
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: AnswerEngineRequest):  # pragma: no cover
        self.calls += 1
        await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_call_ceiling_cuts_off_a_stalled_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tiny ceiling + no retries + no pacing so the test is fast and deterministic.
    monkeypatch.setattr(ai_visibility_settings, "max_call_seconds", 0.01)
    monkeypatch.setattr(ai_visibility_settings, "max_retries", 0)
    monkeypatch.setattr(
        "app.ai_visibility.runner.pace_provider_request",
        lambda provider: asyncio.sleep(0),
    )

    response, error = await _call_with_retries(_StallingAdapter(), _request())

    assert response is None
    assert isinstance(error, AiVisibilityProviderError)
    # A stall surfaces as a retryable timeout, not a hang.
    assert error.error_code == AI_VISIBILITY_ERROR_TIMEOUT
    assert error.retryable is True


@pytest.mark.asyncio
async def test_call_ceiling_retries_then_gives_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai_visibility_settings, "max_call_seconds", 0.01)
    monkeypatch.setattr(ai_visibility_settings, "max_retries", 2)
    monkeypatch.setattr(
        "app.ai_visibility.runner.pace_provider_request",
        lambda provider: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        "app.ai_visibility.runner._retry_delay", lambda attempt, error: 0.0
    )
    adapter = _CountingStallAdapter()

    response, error = await _call_with_retries(adapter, _request())

    assert response is None
    # max_retries=2 -> 3 attempts total, each cut off by the ceiling.
    assert adapter.calls == 3
    assert error is not None and error.error_code == AI_VISIBILITY_ERROR_TIMEOUT
