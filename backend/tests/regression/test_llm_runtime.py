from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.services.llm import tasks as llm_tasks
from app.services.llm import budget as llm_budget
from app.services.llm.config_service import load_prompt_file
from app.models.llm import LLMCostLog
from app.services.llm import runtime as llm_runtime
from app.services.llm import prompt_rendering as llm_prompt_rendering
from app.services.llm import provider_client
from app.services.llm.provider_client import estimate_cost_usd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MODEL_GROQ = "llama-3.3-70b-versatile"
MODEL_MISTRAL = "mistral-small-latest"


@pytest.mark.regression
def test_load_prompt_file_reads_canonical_prompt_directory() -> None:
    assert "You enrich ecommerce product records." in load_prompt_file(
        "data_enrichment_semantic.system.txt"
    )


@pytest.mark.regression
def test_estimate_cost_usd_uses_configured_groq_rates() -> None:
    assert estimate_cost_usd("groq", MODEL_GROQ, 1000, 1000) == Decimal("0.0014")
    assert estimate_cost_usd("groq", MODEL_GROQ, 0, 0) == Decimal("0.0000")
    assert estimate_cost_usd("groq", MODEL_GROQ, None, None) == Decimal("0.0000")


@pytest.mark.regression
def test_estimate_cost_usd_uses_configured_mistral_rates() -> None:
    assert estimate_cost_usd("mistral", MODEL_MISTRAL, 1000, 1000) == Decimal("0.0008")


@pytest.mark.asyncio
@pytest.mark.regression
async def test_provider_retry_retries_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_call_provider(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "Error: HTTP 429: rate limited", 0, 0
        return '{"ok": true}', 1, 1

    async def fake_circuit_open(_provider: str) -> bool:
        return False

    async def fake_record_failure(_provider, _category):
        return None

    async def fake_record_success(_provider):
        return None

    monkeypatch.setattr(provider_client, "call_provider", fake_call_provider)
    monkeypatch.setattr(provider_client, "circuit_is_open", fake_circuit_open)
    monkeypatch.setattr(provider_client, "record_failure", fake_record_failure)
    monkeypatch.setattr(provider_client, "record_success", fake_record_success)

    result, input_tokens, output_tokens = await provider_client.call_provider_with_retry(
        provider="groq",
        model=MODEL_GROQ,
        api_key="key",
        system_prompt="system",
        user_prompt="user",
        max_retries=1,
        base_delay_s=0,
    )

    assert calls == 2
    assert result == '{"ok": true}'
    assert input_tokens == 1
    assert output_tokens == 1


@pytest.mark.asyncio
@pytest.mark.regression
async def test_llm_budget_allows_calls_when_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_redis_fail_open(operation, *, default, operation_name):
        del operation, operation_name
        return default

    monkeypatch.setattr(llm_budget, "redis_fail_open", fake_redis_fail_open)

    assert await llm_budget.reserve_run_llm_call(1, budget_scope="data_enrichment:1")


@pytest.mark.regression
def test_render_html_text_preserves_br_newlines_and_uses_configured_block_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_prompt_rendering.llm_runtime_settings, "html_render_block_tags", "p"
    )
    assert (
        llm_prompt_rendering.render_html_text(
            "<div><p>Line 1<br>Line 2</p><h1>Ignored</h1></div>"
        )
        == "Line 1\nLine 2"
    )


@pytest.mark.asyncio
@pytest.mark.regression
async def test_run_prompt_task_returns_validated_payload(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_run_config(
        session, *, run_id, task_type, config_snapshot=None
    ):
        del session, run_id, task_type, config_snapshot
        return {"provider": "groq", "model": "llama", "api_key_encrypted": ""}

    def fake_get_prompt_task(task_type: str):
        assert task_type == "missing_field_extraction"
        return {
            "system_file": "system.txt",
            "user_file": "user.txt",
            "response_type": "object",
        }

    def fake_load_prompt_file(_path: str) -> str:
        return "Return JSON."

    async def fake_call_provider_with_retry(**_kwargs):
        return '{"materials":"Cotton blend"}', 12, 8

    async def fake_load_cached_llm_result(_cache_key: str):
        return None

    stored_keys: list[str] = []

    async def fake_store_cached_llm_result(cache_key: str, result) -> None:
        stored_keys.append(cache_key)
        assert result.payload == {"materials": "Cotton blend"}

    monkeypatch.setattr(
        "app.services.llm.tasks.resolve_run_config", fake_resolve_run_config
    )
    monkeypatch.setattr("app.services.llm.tasks.get_prompt_task", fake_get_prompt_task)
    monkeypatch.setattr(
        "app.services.llm.tasks.load_prompt_file", fake_load_prompt_file
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.call_provider_with_retry",
        fake_call_provider_with_retry,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.load_cached_llm_result",
        fake_load_cached_llm_result,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.store_cached_llm_result",
        fake_store_cached_llm_result,
    )

    result = await llm_runtime.run_prompt_task(
        db_session,
        task_type="missing_field_extraction",
        run_id=None,
        domain="example.com",
        variables={"missing_fields_json": "[]"},
    )

    cost_logs = list(
        (
            await db_session.execute(select(LLMCostLog).order_by(LLMCostLog.id.asc()))
        ).scalars()
    )

    assert result.payload == {"materials": "Cotton blend"}
    assert result.error_message == ""
    assert len(cost_logs) == 1
    assert cost_logs[0].task_type == "missing_field_extraction"
    assert stored_keys


@pytest.mark.asyncio
@pytest.mark.regression
async def test_run_prompt_task_returns_typed_provider_failure(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_run_config(
        session, *, run_id, task_type, config_snapshot=None
    ):
        del session, run_id, task_type, config_snapshot
        return {"provider": "groq", "model": "llama", "api_key_encrypted": ""}

    def fake_get_prompt_task(task_type: str):
        assert task_type == "missing_field_extraction"
        return {
            "system_file": "system.txt",
            "user_file": "user.txt",
            "response_type": "object",
        }

    def fake_load_prompt_file(_path: str) -> str:
        return "Return JSON."

    async def fake_call_provider_with_retry(**_kwargs):
        return "Error: HTTP 429: rate limited", 0, 0

    async def fake_load_cached_llm_result(_cache_key: str):
        return None

    async def fake_store_cached_llm_result(_cache_key: str, _result) -> None:
        raise AssertionError("provider failures must not be cached as success")

    monkeypatch.setattr(
        "app.services.llm.tasks.resolve_run_config", fake_resolve_run_config
    )
    monkeypatch.setattr("app.services.llm.tasks.get_prompt_task", fake_get_prompt_task)
    monkeypatch.setattr(
        "app.services.llm.tasks.load_prompt_file", fake_load_prompt_file
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.call_provider_with_retry",
        fake_call_provider_with_retry,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.load_cached_llm_result",
        fake_load_cached_llm_result,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.store_cached_llm_result",
        fake_store_cached_llm_result,
    )

    result = await llm_runtime.run_prompt_task(
        db_session,
        task_type="missing_field_extraction",
        run_id=None,
        domain="example.com",
        variables={"missing_fields_json": "[]"},
    )

    cost_logs = list(
        (
            await db_session.execute(select(LLMCostLog).order_by(LLMCostLog.id.asc()))
        ).scalars()
    )

    assert result.payload is None
    assert result.error_category == llm_runtime.LLMErrorCategory.RATE_LIMITED
    assert "rate limited" in result.error_message.lower()
    assert len(cost_logs) == 1
    assert cost_logs[0].outcome == "error"
    assert cost_logs[0].error_category == str(llm_runtime.LLMErrorCategory.RATE_LIMITED)
    assert "rate limited" in cost_logs[0].error_message.lower()


@pytest.mark.asyncio
@pytest.mark.regression
async def test_run_prompt_task_blocks_uncached_provider_calls_over_run_cap(
    db_session: AsyncSession,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    async def fake_resolve_run_config(
        session, *, run_id, task_type, config_snapshot=None
    ):
        del session, run_id, task_type, config_snapshot
        return {"provider": "groq", "model": "llama", "api_key_encrypted": ""}

    def fake_get_prompt_task(_task_type: str):
        return {
            "system_file": "system.txt",
            "user_file": "user.txt",
            "response_type": "object",
        }

    calls = 0

    async def fake_call_provider_with_retry(**_kwargs):
        nonlocal calls
        calls += 1
        return '{"materials":"Cotton"}', 1, 1

    async def fake_load_cached_llm_result(_cache_key: str):
        return None

    async def fake_store_cached_llm_result(_cache_key: str, _result) -> None:
        return None

    monkeypatch.setattr(llm_tasks.llm_runtime_settings, "llm_max_calls_per_run", 1)
    monkeypatch.setattr(
        "app.services.llm.tasks.resolve_run_config", fake_resolve_run_config
    )
    monkeypatch.setattr("app.services.llm.tasks.get_prompt_task", fake_get_prompt_task)
    monkeypatch.setattr(
        "app.services.llm.tasks.load_prompt_file", lambda _path: "Return JSON."
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.call_provider_with_retry",
        fake_call_provider_with_retry,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.load_cached_llm_result",
        fake_load_cached_llm_result,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.store_cached_llm_result",
        fake_store_cached_llm_result,
    )

    first = await llm_runtime.run_prompt_task(
        db_session,
        task_type="missing_field_extraction",
        run_id=run.id,
        domain="example.com",
        variables={"field": "materials"},
    )
    second = await llm_runtime.run_prompt_task(
        db_session,
        task_type="missing_field_extraction",
        run_id=run.id,
        domain="example.com",
        variables={"field": "care"},
    )

    assert first.payload == {"materials": "Cotton"}
    assert second.payload is None
    assert second.error_category == llm_runtime.LLMErrorCategory.BUDGET_EXCEEDED
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.regression
async def test_run_prompt_task_budget_scope_is_independent_from_run_cap(
    db_session: AsyncSession,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    async def fake_resolve_run_config(
        session, *, run_id, task_type, config_snapshot=None
    ):
        del session, run_id, task_type, config_snapshot
        return {"provider": "groq", "model": "llama", "api_key_encrypted": ""}

    def fake_get_prompt_task(_task_type: str):
        return {
            "system_file": "system.txt",
            "user_file": "user.txt",
            "response_type": "object",
        }

    calls = 0

    async def fake_call_provider_with_retry(**_kwargs):
        nonlocal calls
        calls += 1
        return '{"materials":"Cotton"}', 1, 1

    async def fake_load_cached_llm_result(_cache_key: str):
        return None

    async def fake_store_cached_llm_result(_cache_key: str, _result) -> None:
        return None

    monkeypatch.setattr(llm_tasks.llm_runtime_settings, "llm_max_calls_per_run", 1)
    monkeypatch.setattr(
        "app.services.llm.tasks.resolve_run_config", fake_resolve_run_config
    )
    monkeypatch.setattr("app.services.llm.tasks.get_prompt_task", fake_get_prompt_task)
    monkeypatch.setattr(
        "app.services.llm.tasks.load_prompt_file", lambda _path: "Return JSON."
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.call_provider_with_retry",
        fake_call_provider_with_retry,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.load_cached_llm_result",
        fake_load_cached_llm_result,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.store_cached_llm_result",
        fake_store_cached_llm_result,
    )

    first = await llm_runtime.run_prompt_task(
        db_session,
        task_type="missing_field_extraction",
        run_id=run.id,
        domain="example.com",
        budget_scope="data_enrichment:1",
        variables={"field": "materials"},
    )
    second = await llm_runtime.run_prompt_task(
        db_session,
        task_type="missing_field_extraction",
        run_id=run.id,
        domain="example.com",
        budget_scope="data_enrichment:2",
        variables={"field": "care"},
    )
    third = await llm_runtime.run_prompt_task(
        db_session,
        task_type="missing_field_extraction",
        run_id=run.id,
        domain="example.com",
        budget_scope="data_enrichment:1",
        variables={"field": "fit"},
    )

    assert first.payload == {"materials": "Cotton"}
    assert second.payload == {"materials": "Cotton"}
    assert third.payload is None
    assert third.error_category == llm_runtime.LLMErrorCategory.BUDGET_EXCEEDED
    assert calls == 2


@pytest.mark.asyncio
@pytest.mark.regression
async def test_run_prompt_task_returns_timeout_when_provider_exceeds_call_timeout(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_run_config(
        session, *, run_id, task_type, config_snapshot=None
    ):
        del session, run_id, task_type, config_snapshot
        return {"provider": "groq", "model": "llama", "api_key_encrypted": ""}

    def fake_get_prompt_task(_task_type: str):
        return {
            "system_file": "system.txt",
            "user_file": "user.txt",
            "response_type": "object",
        }

    async def slow_call_provider_with_retry(**_kwargs):
        await asyncio.sleep(1)
        return '{"materials":"Cotton"}', 1, 1

    async def fake_load_cached_llm_result(_cache_key: str):
        return None

    monkeypatch.setattr(
        "app.services.llm.tasks.resolve_run_config", fake_resolve_run_config
    )
    monkeypatch.setattr("app.services.llm.tasks.get_prompt_task", fake_get_prompt_task)
    monkeypatch.setattr(
        "app.services.llm.tasks.load_prompt_file", lambda _path: "Return JSON."
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.call_provider_with_retry",
        slow_call_provider_with_retry,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.load_cached_llm_result",
        fake_load_cached_llm_result,
    )

    result = await llm_runtime.run_prompt_task(
        db_session,
        task_type="missing_field_extraction",
        run_id=None,
        domain="example.com",
        variables={"field": "materials"},
        timeout_seconds=0.1,
    )
    cost_logs = list(
        (
            await db_session.execute(select(LLMCostLog).order_by(LLMCostLog.id.asc()))
        ).scalars()
    )

    assert result.payload is None
    assert result.error_category == llm_runtime.LLMErrorCategory.TIMEOUT
    assert any(
        log.outcome == "error"
        and log.error_category == str(llm_runtime.LLMErrorCategory.TIMEOUT)
        for log in cost_logs
    )


@pytest.mark.asyncio
@pytest.mark.regression
async def test_run_prompt_task_validates_direct_record_extraction_array_payload(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_run_config(
        session, *, run_id, task_type, config_snapshot=None
    ):
        del session, run_id, task_type, config_snapshot
        return {"provider": "groq", "model": "llama", "api_key_encrypted": ""}

    def fake_get_prompt_task(task_type: str):
        assert task_type == "direct_record_extraction"
        return {
            "system_file": "system.txt",
            "user_file": "user.txt",
            "response_type": "array",
        }

    def fake_load_prompt_file(_path: str) -> str:
        return "Return JSON."

    async def fake_call_provider_with_retry(**_kwargs):
        return (
            '[{"title":"Widget Prime","url":"https://example.com/products/widget"}]',
            12,
            8,
        )

    async def fake_load_cached_llm_result(_cache_key: str):
        return None

    async def fake_store_cached_llm_result(_cache_key: str, _result) -> None:
        return None

    monkeypatch.setattr(
        "app.services.llm.tasks.resolve_run_config", fake_resolve_run_config
    )
    monkeypatch.setattr("app.services.llm.tasks.get_prompt_task", fake_get_prompt_task)
    monkeypatch.setattr(
        "app.services.llm.tasks.load_prompt_file", fake_load_prompt_file
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.call_provider_with_retry",
        fake_call_provider_with_retry,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.load_cached_llm_result",
        fake_load_cached_llm_result,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.store_cached_llm_result",
        fake_store_cached_llm_result,
    )

    result = await llm_runtime.run_prompt_task(
        db_session,
        task_type="direct_record_extraction",
        run_id=None,
        domain="example.com",
        variables={"html_snippet": "Widget Prime"},
    )

    assert result.payload == [
        {"title": "Widget Prime", "url": "https://example.com/products/widget"}
    ]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_run_prompt_task_rejects_invalid_product_intelligence_enrichment(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_run_config(
        session, *, run_id, task_type, config_snapshot=None
    ):
        del session, run_id, task_type, config_snapshot
        return {"provider": "groq", "model": "llama", "api_key_encrypted": ""}

    def fake_get_prompt_task(task_type: str):
        assert task_type == "product_intelligence_enrichment"
        return {
            "system_file": "system.txt",
            "user_file": "user.txt",
            "response_type": "object",
        }

    def fake_load_prompt_file(_path: str) -> str:
        return "Return JSON."

    async def fake_call_provider_with_retry(**_kwargs):
        return '{"normalized_title":"Widget","suggested_score":1.4}', 12, 8

    async def fake_load_cached_llm_result(_cache_key: str):
        return None

    async def fake_store_cached_llm_result(_cache_key: str, _result) -> None:
        raise AssertionError("invalid payloads must not be cached")

    monkeypatch.setattr(
        "app.services.llm.tasks.resolve_run_config", fake_resolve_run_config
    )
    monkeypatch.setattr("app.services.llm.tasks.get_prompt_task", fake_get_prompt_task)
    monkeypatch.setattr(
        "app.services.llm.tasks.load_prompt_file", fake_load_prompt_file
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.call_provider_with_retry",
        fake_call_provider_with_retry,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.load_cached_llm_result",
        fake_load_cached_llm_result,
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.store_cached_llm_result",
        fake_store_cached_llm_result,
    )

    result = await llm_runtime.run_prompt_task(
        db_session,
        task_type="product_intelligence_enrichment",
        run_id=None,
        domain="example.com",
        variables={},
    )

    assert result.payload is None
    assert result.error_category == llm_runtime.LLMErrorCategory.VALIDATION_FAILURE
    assert (
        "product_intelligence_enrichment payload validation failed"
        in result.error_message
    )


@pytest.mark.asyncio
@pytest.mark.regression
async def test_run_prompt_task_rejects_unknown_product_intelligence_reason_keys(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_run_config(
        session, *, run_id, task_type, config_snapshot=None
    ):
        del session, run_id, task_type, config_snapshot
        return {"provider": "groq", "model": "llama", "api_key_encrypted": ""}

    def fake_get_prompt_task(_task_type: str):
        return {
            "system_file": "system.txt",
            "user_file": "user.txt",
            "response_type": "object",
        }

    async def fake_call_provider_with_retry(**_kwargs):
        return '{"normalized_title":"Widget","reason_updates":[{"unknown":"x"}]}', 1, 1

    async def fake_load_cached_llm_result(_cache_key: str):
        return None

    async def fake_store_cached_llm_result(_cache_key: str, _result) -> None:
        raise AssertionError("invalid payloads must not be cached")

    monkeypatch.setattr(
        "app.services.llm.tasks.resolve_run_config", fake_resolve_run_config
    )
    monkeypatch.setattr("app.services.llm.tasks.get_prompt_task", fake_get_prompt_task)
    monkeypatch.setattr(
        "app.services.llm.tasks.load_prompt_file", lambda _path: "Return JSON."
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.call_provider_with_retry", fake_call_provider_with_retry
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.load_cached_llm_result", fake_load_cached_llm_result
    )
    monkeypatch.setattr(
        "app.services.llm.tasks.store_cached_llm_result", fake_store_cached_llm_result
    )

    result = await llm_runtime.run_prompt_task(
        db_session,
        task_type="product_intelligence_enrichment",
        run_id=None,
        domain="example.com",
        variables={},
    )

    assert result.payload is None
    assert result.error_category == llm_runtime.LLMErrorCategory.VALIDATION_FAILURE


@pytest.mark.regression
def test_trim_prompt_section_body_skips_expensive_large_json_reparse() -> None:
    large_json = '{"items":[' + ",".join('"value"' for _ in range(5000)) + "]}"

    trimmed = llm_prompt_rendering.trim_prompt_section_body(
        large_json,
        120,
        "[TRUNCATED]",
    )

    assert trimmed.endswith("[TRUNCATED]}")
    assert len(trimmed) <= 120


@pytest.mark.regression
def test_truncate_html_prefers_dense_anchor_context() -> None:
    html = """
    <html><body>
    <h1>Senior Python Engineer</h1>
    <p>General intro that does not matter.</p>
    <h2>Compensation</h2>
    <p>Salary: $120k - $150k base plus bonus.</p>
    <ul><li>Remote within the US</li></ul>
    </body></html>
    """

    rendered = llm_prompt_rendering.truncate_html(html, 80, anchors=["salary"])

    assert "<h1>" not in rendered
    assert "Compensation" in rendered
    assert "Salary: $120k - $150k base plus bonus." in rendered
    assert len(rendered) <= 80


@pytest.mark.regression
def test_truncate_html_renders_plain_text_blocks() -> None:
    html = (
        "<h1>Product Title</h1><p>Short description.</p><ul><li>Free shipping</li></ul>"
    )

    rendered = llm_prompt_rendering.truncate_html(html, 200)

    assert rendered == "Product Title\nShort description.\nFree shipping"
