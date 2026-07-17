from __future__ import annotations

import pytest

from app.connectors.llm import provider_client
from app.connectors.llm.errors import ERROR_PREFIX
from app.crawl.pipeline import learn_once

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_learn_once_client_makes_exactly_one_provider_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Finding 14: LEARN-ONCE is a single model call. Even when the provider keeps
    # returning a retryable error, the learn-once model client must issue exactly
    # ONE provider request (max_retries=0), never max_retries+1.
    calls = 0

    async def fake_call_provider(**_kwargs):
        nonlocal calls
        calls += 1
        # A rate-limit error is retryable in call_provider_with_retry, so any
        # remaining retry budget would trigger another request.
        return f"{ERROR_PREFIX} HTTP 429: rate limited", 0, 0

    async def fake_circuit_open(_provider: str) -> bool:
        return False

    async def fake_record_failure(_provider, _category):
        return None

    async def fake_record_success(_provider):
        return None

    async def fake_resolve_run_config(*_args, **_kwargs):
        return {
            "provider": "groq",
            "model": "test-model",
            "api_key_encrypted": "enc",
        }

    monkeypatch.setattr(provider_client, "call_provider", fake_call_provider)
    monkeypatch.setattr(provider_client, "circuit_is_open", fake_circuit_open)
    monkeypatch.setattr(provider_client, "record_failure", fake_record_failure)
    monkeypatch.setattr(provider_client, "record_success", fake_record_success)
    monkeypatch.setattr(learn_once, "resolve_run_config", fake_resolve_run_config)
    monkeypatch.setattr(learn_once, "resolve_provider_api_key", lambda **_kwargs: "key")

    client = learn_once._model_client_for_run(None, run_id=None)
    result = await client("system", "user")

    assert calls == 1
    assert result.startswith(ERROR_PREFIX)
