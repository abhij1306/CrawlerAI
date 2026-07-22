from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING

from app.acquisition.browser_proxy_config import display_proxy
from app.acquisition.contracts import (
    AcquisitionPlan,
    AcquisitionResult,
    AttemptResult,
    AttemptSpec,
)
from app.acquisition.fetch import attempt_host_policy
from app.acquisition.runtime import PageFetchResult
from app.core.config.runtime_settings import crawler_runtime_settings

if TYPE_CHECKING:
    from app.acquisition.fetch.browser_attempt_runner import BrowserAttemptRunner


@dataclass(slots=True)
class AttemptPlanState:
    plan_id: str = ""
    plan_started_at: datetime | None = None
    plan_deadline: datetime | None = None
    attempt_specs: list[AttemptSpec] = field(default_factory=list)
    attempt_results: list[AttemptResult] = field(default_factory=list)
    retry_budget_exhausted: bool = False


def start_plan(runner: BrowserAttemptRunner) -> None:
    runner.plan.plan_started_at = datetime.now(UTC)
    remaining = max(
        0.001,
        float(runner.context.deadline_monotonic - time.perf_counter()),
    )
    runner.plan.plan_deadline = runner.plan.plan_started_at + timedelta(
        seconds=remaining
    )
    plan_key = (
        f"{runner.context.url}|browser|{runner.plan.plan_started_at.isoformat()}"
    )
    runner.plan.plan_id = sha256(plan_key.encode("utf-8")).hexdigest()[:20]


def attempt_consumed_remaining_budget(
    result: AttemptResult,
    *,
    spec: AttemptSpec,
    remaining_before_spec: float,
) -> bool:
    error = str(result.error or "")
    timed_out = error == "attempt_deadline_exhausted" or error.startswith(
        "TimeoutError: Browser "
    )
    return timed_out and (
        spec.timeout_seconds + minimum_attempt_budget() >= remaining_before_spec
    )


def attempt_spec(
    runner: BrowserAttemptRunner,
    *,
    proxy: str | None,
    engine: str,
    engine_index: int,
    engine_attempts: list[str],
) -> AttemptSpec:
    timeout = runner.deps.browser_attempt_timeout_seconds(
        runner.context,
        reason=runner.reason,
        browser_engine=engine,
        engine_index=engine_index,
        engine_attempts=engine_attempts,
        host_policy=attempt_host_policy.active_host_policy(runner),
    )
    spec = AttemptSpec(
        attempt_id=(
            f"{runner.plan.plan_id}-{len(runner.plan.attempt_specs) + 1}-{engine}"
        ),
        transport=engine,  # type: ignore[arg-type]
        proxy=proxy,
        interaction=bool(runner.requested_fields or runner.context.requested_fields),
        traversal_mode=runner.context.traversal_mode,
        required_artifacts=("html",),
        timeout_seconds=max(0.001, float(timeout)),
        reason=runner.reason,
    )
    runner.plan.attempt_specs.append(spec)
    return spec


def plan_deadline(runner: BrowserAttemptRunner) -> datetime:
    if runner.plan.plan_deadline is None:
        start_plan(runner)
    assert runner.plan.plan_deadline is not None
    return runner.plan.plan_deadline


async def raise_if_no_budget(
    runner: BrowserAttemptRunner,
    engine: str,
    engine_index: int,
    engine_attempts: list[str],
    phase: str,
) -> None:
    remaining = runner.deps.browser_attempt_timeout_seconds(
        runner.context,
        reason=runner.reason,
        browser_engine=engine,
        engine_index=engine_index,
        engine_attempts=engine_attempts,
        host_policy=attempt_host_policy.active_host_policy(runner),
    )
    if remaining < minimum_attempt_budget():
        raise TimeoutError(
            "Acquisition browser retry budget exhausted before "
            f"{engine} could {phase}"
        )


def has_attempt_budget(runner: BrowserAttemptRunner) -> bool:
    remaining = runner.context.deadline_monotonic - time.perf_counter()
    return remaining >= minimum_attempt_budget()


def minimum_attempt_budget() -> float:
    return max(
        0.0,
        float(crawler_runtime_settings.browser_attempt_min_runtime_seconds),
    )


def attach_acquisition_diagnostics(
    runner: BrowserAttemptRunner,
    result: PageFetchResult,
    *,
    selected_attempt_id: str | None,
    outcome: str,
    termination_reason: str,
) -> None:
    result.acquisition_diagnostics = acquisition_diagnostics(
        runner,
        selected_attempt_id=selected_attempt_id,
        outcome=outcome,
        termination_reason=termination_reason,
    )


def acquisition_diagnostics(
    runner: BrowserAttemptRunner,
    *,
    selected_attempt_id: str | None,
    outcome: str,
    termination_reason: str,
) -> dict[str, object]:
    plan = AcquisitionPlan(
        plan_id=runner.plan.plan_id or "browser-plan",
        attempts=tuple(runner.plan.attempt_specs),
        created_at=runner.plan.plan_started_at or datetime.now(UTC),
        deadline=plan_deadline(runner),
    )
    canonical_result = AcquisitionResult(
        plan_id=plan.plan_id,
        attempts=tuple(runner.plan.attempt_results),
        selected_attempt_id=selected_attempt_id,
        outcome=outcome,  # type: ignore[arg-type]
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
