from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.acquisition.browser_proxy_config import display_proxy
# Planned HTTP emits canonical attempt diagnostics. Runtime
# AcquisitionIntent/PageAcquisitionResult are different page-flow contracts.
from app.acquisition.contracts import (
    AcquisitionPlan,
    AcquisitionResult,
    AttemptResult,
)
from app.acquisition.executor import AttemptExecution, AttemptExecutor
from app.acquisition.planner import AcquisitionPlanner, PlanningRequest
from app.acquisition.runtime import PageFetchResult

AsyncDependency = Callable[..., Awaitable[Any]]
SyncDependency = Callable[..., Any]


async def run_planned_http_only(
    context: Any,
    *,
    curl_fetcher: AsyncDependency,
    http_fetcher: AsyncDependency,
    attempt_http_fetch: AsyncDependency,
    handle_http_result: AsyncDependency,
    resolve_http_timeout: SyncDependency,
    remaining_timeout_seconds: SyncDependency,
    force_httpx: bool,
) -> PageFetchResult:
    remaining = max(0.001, float(remaining_timeout_seconds(context)))
    deadline = datetime.now(UTC) + timedelta(seconds=remaining)
    plan = AcquisitionPlanner().plan(
        PlanningRequest(
            url=context.url,
            surface=context.surface or "unknown",
            mode="http_only",
            deadline=deadline,
            proxies=tuple(context.proxies),
            force_httpx=bool(force_httpx),
            traversal_mode=context.traversal_mode,
        )
    )
    page_results: dict[str, PageFetchResult] = {}

    async def execute_attempt(execution: AttemptExecution) -> AttemptResult:
        return await _execute_planned_http_attempt(
            context,
            execution=execution,
            page_results=page_results,
            curl_fetcher=curl_fetcher,
            http_fetcher=http_fetcher,
            attempt_http_fetch=attempt_http_fetch,
            handle_http_result=handle_http_result,
            resolve_http_timeout=resolve_http_timeout,
        )

    executor = AttemptExecutor({"curl": execute_attempt, "httpx": execute_attempt})
    attempt_results: list[AttemptResult] = []
    for spec in plan.attempts:
        attempt_result = await executor.execute(
            spec,
            url=context.url,
            deadline=plan.deadline,
        )
        attempt_results.append(attempt_result)
        page_result = page_results.get(spec.attempt_id)
        if page_result is None:
            continue
        page_result.acquisition_diagnostics = _planned_acquisition_diagnostics(
            plan,
            attempt_results,
            selected_attempt_id=spec.attempt_id,
            outcome=_acquisition_outcome(attempt_result.outcome),
            termination_reason="attempt_selected",
        )
        return page_result

    diagnostics = _planned_acquisition_diagnostics(
        plan,
        attempt_results,
        selected_attempt_id=None,
        outcome="error",
        termination_reason="http_transports_exhausted",
    )
    last_attempt = attempt_results[-1] if attempt_results else None
    if last_attempt is not None and last_attempt.error in {
        "attempt_deadline_exhausted",
        "global_deadline_exhausted",
    }:
        error: Exception = TimeoutError(
            f"Acquisition deadline exhausted for {context.url}"
        )
    elif context.last_error is not None:
        error = context.last_error
    else:
        error = RuntimeError(
            f"Failed to fetch {context.url} using planned HTTP attempts"
        )
    setattr(error, "acquisition_diagnostics", diagnostics)
    raise error


async def _execute_planned_http_attempt(
    context: Any,
    *,
    execution: AttemptExecution,
    page_results: dict[str, PageFetchResult],
    curl_fetcher: AsyncDependency,
    http_fetcher: AsyncDependency,
    attempt_http_fetch: AsyncDependency,
    handle_http_result: AsyncDependency,
    resolve_http_timeout: SyncDependency,
) -> AttemptResult:
    started_at = datetime.now(UTC)
    fetcher = curl_fetcher if execution.spec.transport == "curl" else http_fetcher
    timeout_seconds = min(
        float(resolve_http_timeout(context)),
        execution.timeout_seconds,
    )
    raw_result = await attempt_http_fetch(
        context,
        fetcher=fetcher,
        proxy=execution.spec.proxy,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(raw_result, PageFetchResult):
        error = context.last_error
        return AttemptResult(
            attempt_id=execution.spec.attempt_id,
            outcome="error",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            diagnostics={
                "transport": execution.spec.transport,
                "proxy": display_proxy(execution.spec.proxy),
                "timeout_seconds": timeout_seconds,
            },
            error=(
                f"{type(error).__name__}: {error}"
                if error is not None
                else "transport_attempt_failed"
            ),
        )

    handled_result, vendor_block_confirmed = await handle_http_result(
        context,
        result=raw_result,
        proxy=execution.spec.proxy,
        allow_browser_escalation=False,
    )
    if not isinstance(handled_result, PageFetchResult):
        return AttemptResult(
            attempt_id=execution.spec.attempt_id,
            outcome="error",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            error="http_result_not_selected",
        )

    page_results[execution.spec.attempt_id] = handled_result
    completed_at = datetime.now(UTC)
    return AttemptResult(
        attempt_id=execution.spec.attempt_id,
        outcome=_page_attempt_outcome(
            handled_result,
            vendor_block_confirmed=vendor_block_confirmed,
        ),
        final_url=handled_result.final_url,
        status_code=handled_result.status_code,
        started_at=started_at,
        completed_at=completed_at,
        diagnostics={
            "transport": execution.spec.transport,
            "method": handled_result.method,
            "proxy": display_proxy(execution.spec.proxy),
            "blocked": bool(handled_result.blocked),
            "vendor_block_confirmed": bool(vendor_block_confirmed),
            "timeout_seconds": timeout_seconds,
            "duration_ms": max(
                0,
                int((completed_at - started_at).total_seconds() * 1000),
            ),
        },
    )


def _page_attempt_outcome(
    result: PageFetchResult,
    *,
    vendor_block_confirmed: bool,
) -> Literal["success", "blocked", "empty", "error"]:
    if vendor_block_confirmed or bool(result.blocked):
        return "blocked"
    if int(result.status_code or 0) >= 500:
        return "error"
    if not str(result.html or "").strip() and not list(result.network_payloads or []):
        return "empty"
    return "success"


def _acquisition_outcome(
    attempt_outcome: str,
) -> Literal["success", "blocked", "empty", "error"]:
    if attempt_outcome == "success":
        return "success"
    if attempt_outcome == "blocked":
        return "blocked"
    if attempt_outcome == "empty":
        return "empty"
    return "error"


def _planned_acquisition_diagnostics(
    plan: AcquisitionPlan,
    attempts: list[AttemptResult],
    *,
    selected_attempt_id: str | None,
    outcome: Literal["success", "blocked", "empty", "error"],
    termination_reason: str,
) -> dict[str, object]:
    canonical_result = AcquisitionResult(
        plan_id=plan.plan_id,
        attempts=tuple(attempts),
        selected_attempt_id=selected_attempt_id,
        outcome=outcome,
    )
    plan_payload = plan.model_dump(mode="json")
    plan_attempts = plan_payload.get("attempts")
    if isinstance(plan_attempts, list):
        for attempt in plan_attempts:
            if isinstance(attempt, dict):
                attempt["proxy"] = display_proxy(attempt.get("proxy"))
    return {
        "plan": plan_payload,
        "result": canonical_result.model_dump(mode="json"),
        "termination_reason": termination_reason,
    }
