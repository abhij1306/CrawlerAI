from __future__ import annotations

import asyncio
import json
import time
from string import Template
from typing import Any

from app.core.metrics import observe_llm_task_duration, record_llm_task_outcome
from app.core.config.llm_runtime import (
    PARSE_PROVIDER_JSON_ERROR,
    llm_runtime_settings,
)
from app.connectors.llm.budget import reserve_run_llm_call
from app.connectors.llm.cache import (
    build_llm_cache_key,
    load_cached_llm_result,
    store_cached_llm_result,
)
from app.connectors.llm.config_service import (
    get_prompt_task,
    load_prompt_file,
    resolve_provider_api_key,
    resolve_run_config,
)
from app.connectors.llm.cost_logging import record_llm_cost_log
from app.connectors.llm.errors import ERROR_PREFIX, LLMErrorCategory, classify_error
from app.connectors.llm.payloads import parse_payload, validate_task_payload
from app.connectors.llm.prompt_rendering import (
    enforce_token_limit,
    safe_truncate_for_prompt,
    stringify_prompt_value,
    truncate_html,
    truncate_json_literal,
)
from app.connectors.llm.provider_client import call_provider_with_retry
from app.connectors.llm.types import LLMTaskResult
from sqlalchemy.ext.asyncio import AsyncSession


async def run_prompt_task(
    session: AsyncSession,
    *,
    task_type: str,
    run_id: int | None,
    domain: str,
    variables: dict[str, Any],
    budget_scope: str | None = None,
    timeout_seconds: float | None = None,
    config_snapshot: dict[str, Any] | None = None,
) -> LLMTaskResult:
    started_at = time.monotonic()
    resolved = await _resolve_prompt_task(
        session,
        task_type=task_type,
        run_id=run_id,
        config_snapshot=config_snapshot,
        variables=variables,
    )
    if isinstance(resolved, LLMTaskResult):
        return _observe_prompt_task_result(
            resolved, task_type=task_type, started_at=started_at
        )
    config, task, system_prompt, safe_user_prompt = resolved
    provider = str(config.get("provider") or "")
    model = str(config.get("model") or "")
    response_type = str(task.get("response_type") or "object")
    cache_key = _prompt_cache_key(
        task_type, domain, config, task, system_prompt, safe_user_prompt, variables
    )
    cached_result = await load_cached_llm_result(cache_key)
    if cached_result is not None:
        return _observe_prompt_task_result(
            cached_result, task_type=task_type, started_at=started_at
        )
    if not await reserve_run_llm_call(run_id, budget_scope=budget_scope):
        return _observe_prompt_task_result(
            _budget_exceeded_result(
                provider=provider,
                model=model,
                run_id=run_id,
                budget_scope=budget_scope,
            ),
            task_type=task_type,
            started_at=started_at,
        )
    raw, input_tokens, output_tokens = await _call_provider(
        config=config,
        system_prompt=system_prompt,
        safe_user_prompt=safe_user_prompt,
        timeout_seconds=timeout_seconds,
    )
    if raw.startswith(ERROR_PREFIX):
        result = await _failure_result(
            session,
            run_id=run_id,
            task_type=task_type,
            domain=domain,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_message=raw,
            error_category=classify_error(raw),
        )
        return _observe_prompt_task_result(
            result, task_type=task_type, started_at=started_at
        )
    parsed = await _parse_and_validate_payload(
        session,
        raw=raw,
        task=task,
        task_type=task_type,
        domain=domain,
        provider=provider,
        model=model,
        run_id=run_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        response_type=response_type,
    )
    if isinstance(parsed, LLMTaskResult):
        return _observe_prompt_task_result(
            parsed, task_type=task_type, started_at=started_at
        )
    result = await _successful_prompt_result(
        session,
        parsed=parsed,
        cache_key=cache_key,
        run_id=run_id,
        task_type=task_type,
        domain=domain,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return _observe_prompt_task_result(
        result, task_type=task_type, started_at=started_at
    )


def _prompt_cache_key(
    task_type: str,
    domain: str,
    config: dict[str, Any],
    task: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    variables: dict[str, Any],
) -> str:
    return build_llm_cache_key(
        task_type=task_type,
        domain=domain,
        provider=str(config.get("provider") or ""),
        model=str(config.get("model") or ""),
        response_type=str(task.get("response_type") or "object"),
        data_key=str(task.get("data_key") or ""),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        variables=variables,
    )


def _observe_prompt_task_result(
    result: LLMTaskResult, *, task_type: str, started_at: float
) -> LLMTaskResult:
    provider = str(result.provider or "unknown")
    outcome = "success" if not result.error_message else "error"
    record_llm_task_outcome(
        task_type=task_type,
        provider=provider,
        outcome=outcome,
        error_category=str(result.error_category or LLMErrorCategory.NONE),
    )
    observe_llm_task_duration(
        task_type=task_type,
        provider=provider,
        outcome=outcome,
        seconds=time.monotonic() - started_at,
    )
    return result


def _budget_exceeded_result(
    *, provider: str, model: str, run_id: int | None, budget_scope: str | None
) -> LLMTaskResult:
    scope_label = budget_scope or f"crawl run {run_id}"
    return LLMTaskResult(
        payload=None,
        provider=provider,
        model=model,
        error_message=(
            "Error: LLM call budget exceeded for "
            f"{scope_label}; max={llm_runtime_settings.llm_max_calls_per_run}"
        ),
        error_category=LLMErrorCategory.BUDGET_EXCEEDED,
    )


async def _failure_result(
    session: AsyncSession,
    *,
    run_id: int | None,
    task_type: str,
    domain: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    error_message: str,
    error_category: LLMErrorCategory,
) -> LLMTaskResult:
    await record_llm_cost_log(
        session,
        run_id=run_id,
        task_type=task_type,
        domain=domain,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error_message=error_message,
        error_category=error_category,
    )
    return LLMTaskResult(
        payload=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=provider,
        model=model,
        error_message=error_message,
        error_category=error_category,
    )


async def _successful_prompt_result(
    session: AsyncSession,
    *,
    parsed: object,
    cache_key: str,
    run_id: int | None,
    task_type: str,
    domain: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> LLMTaskResult:
    await record_llm_cost_log(
        session,
        run_id=run_id,
        task_type=task_type,
        domain=domain,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    normalized_payload = parsed if isinstance(parsed, (dict, list)) else None
    result = LLMTaskResult(
        payload=normalized_payload,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=provider,
        model=model,
    )
    await store_cached_llm_result(cache_key, result)
    return result


async def _resolve_prompt_task(
    session: AsyncSession,
    *,
    task_type: str,
    run_id: int | None,
    config_snapshot: dict[str, Any] | None,
    variables: dict[str, Any],
) -> LLMTaskResult | tuple[dict[str, Any], dict[str, Any], str, str]:
    """Resolve config, task definition, and rendered prompts. Returns early LLMTaskResult on any failure."""
    config = await resolve_run_config(
        session,
        run_id=run_id,
        task_type=task_type,
        config_snapshot=config_snapshot,
    )
    task = get_prompt_task(task_type)
    if config is None:
        return LLMTaskResult(
            payload=None,
            error_message=f"No LLM config available for task {task_type}",
            error_category=LLMErrorCategory.MISSING_CONFIG,
        )
    if task is None:
        return LLMTaskResult(
            payload=None,
            error_message=f"No prompt registered for task {task_type}",
            error_category=LLMErrorCategory.MISSING_CONFIG,
        )
    system_prompt = load_prompt_file(str(task.get("system_file") or ""))
    user_template = load_prompt_file(str(task.get("user_file") or ""))
    if not system_prompt.strip() or not user_template.strip():
        return LLMTaskResult(
            payload=None,
            error_message=f"Prompt files missing for task {task_type}",
            error_category=LLMErrorCategory.MISSING_CONFIG,
        )
    rendered = Template(user_template).safe_substitute(
        {key: stringify_prompt_value(value) for key, value in variables.items()}
    )
    return config, task, system_prompt, enforce_token_limit(rendered)


async def _call_provider(
    *,
    config: dict[str, Any],
    system_prompt: str,
    safe_user_prompt: str,
    timeout_seconds: float | None,
) -> tuple[str, int, int]:
    """Call the provider with optional timeout; return (raw_text, input_tokens, output_tokens)."""
    provider = str(config.get("provider") or "")
    model = str(config.get("model") or "")
    provider_call = call_provider_with_retry(
        provider=provider,
        model=model,
        api_key=resolve_provider_api_key(
            provider=provider,
            encrypted_value=str(config.get("api_key_encrypted") or ""),
        ),
        system_prompt=system_prompt,
        user_prompt=safe_user_prompt,
    )
    try:
        if timeout_seconds and timeout_seconds > 0:
            return await asyncio.wait_for(provider_call, timeout=float(timeout_seconds))
        return await provider_call
    except TimeoutError:
        return "Error: LLM provider call timed out", 0, 0


async def _parse_and_validate_payload(
    session: AsyncSession,
    *,
    raw: str,
    task: dict[str, Any],
    task_type: str,
    domain: str,
    provider: str,
    model: str,
    run_id: int | None,
    input_tokens: int,
    output_tokens: int,
    response_type: str,
) -> LLMTaskResult | object:
    """Parse raw LLM text, unwrap data_key, validate schema. Returns error LLMTaskResult or payload."""
    payload: object = parse_payload(raw, response_type=response_type)
    if payload is None:
        return await _failure_result(
            session,
            run_id=run_id,
            task_type=task_type,
            domain=domain,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_message=PARSE_PROVIDER_JSON_ERROR,
            error_category=LLMErrorCategory.PARSE_FAILURE,
        )
    if isinstance(payload, dict) and task.get("data_key"):
        inner = payload.get(str(task["data_key"]))
        if isinstance(inner, (dict, list)):
            payload = inner
    payload, validation_error = validate_task_payload(task_type, payload)
    if validation_error is not None:
        return await _failure_result(
            session,
            run_id=run_id,
            task_type=task_type,
            domain=domain,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_message=f"Error: {validation_error}",
            error_category=LLMErrorCategory.VALIDATION_FAILURE,
        )
    return payload


async def extract_records_directly(
    session: AsyncSession,
    *,
    run_id: int,
    domain: str,
    url: str,
    surface: str,
    html_text: str,
    requested_fields: list[str] | None,
    existing_records: list[dict[str, object]] | None,
) -> tuple[list[dict[str, object]], str | None]:
    result = await run_prompt_task(
        session,
        task_type="direct_record_extraction",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "surface": surface,
            "requested_fields_json": json.dumps(list(requested_fields or [])),
            "existing_records_json": truncate_json_literal(
                safe_truncate_for_prompt(list(existing_records or [])),
                llm_runtime_settings.candidate_evidence_max_chars,
            ),
            "html_snippet": truncate_html(
                html_text,
                llm_runtime_settings.html_snippet_max_chars,
                anchors=list(requested_fields or []),
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, list) else []), (
        result.error_message or None
    )


async def extract_missing_fields(
    session: AsyncSession,
    *,
    run_id: int,
    domain: str,
    url: str,
    html_text: str,
    missing_fields: list[str],
    existing_values: dict[str, object],
) -> tuple[dict[str, object], str | None]:
    result = await run_prompt_task(
        session,
        task_type="missing_field_extraction",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "missing_fields_json": json.dumps(missing_fields),
            "existing_values_json": truncate_json_literal(
                existing_values,
                llm_runtime_settings.existing_values_max_chars,
            ),
            "html_snippet": truncate_html(
                html_text,
                llm_runtime_settings.html_snippet_max_chars,
                anchors=missing_fields,
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, dict) else {}), (
        result.error_message or None
    )


async def review_field_candidates(
    session: AsyncSession,
    *,
    run_id: int,
    domain: str,
    url: str,
    html_text: str,
    canonical_fields: list[str],
    target_fields: list[str],
    existing_values: dict[str, object],
    candidate_evidence: dict[str, list[dict]],
    discovered_sources: dict[str, object],
) -> tuple[dict[str, object], str | None]:
    result = await run_prompt_task(
        session,
        task_type="field_cleanup_review",
        run_id=run_id,
        domain=domain,
        variables={
            "url": url,
            "canonical_fields_json": json.dumps(canonical_fields),
            "target_fields_json": json.dumps(target_fields),
            "existing_values_json": truncate_json_literal(
                {field: existing_values.get(field) for field in target_fields},
                llm_runtime_settings.existing_values_max_chars,
            ),
            "candidate_evidence_json": truncate_json_literal(
                safe_truncate_for_prompt(candidate_evidence),
                llm_runtime_settings.candidate_evidence_max_chars,
            ),
            "discovered_sources_json": truncate_json_literal(
                discovered_sources,
                llm_runtime_settings.discovered_sources_max_chars,
            ),
            "html_snippet": truncate_html(
                html_text,
                llm_runtime_settings.html_snippet_max_chars,
                anchors=[
                    *target_fields,
                    *[str(existing_values.get(field) or "") for field in target_fields],
                ],
            ),
        },
    )
    payload = result.payload
    return (payload if isinstance(payload, dict) else {}), (
        result.error_message or None
    )
