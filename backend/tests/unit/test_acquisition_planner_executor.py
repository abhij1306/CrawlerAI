from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.acquisition.contracts import AttemptResult
from app.acquisition.executor import AttemptExecutor, AttemptExecution
from app.acquisition.planner import AcquisitionPlanner, PlanningRequest

pytestmark = pytest.mark.unit


def test_http_only_plan_contains_no_browser_attempts() -> None:
    plan = AcquisitionPlanner().plan(
        PlanningRequest(
            url="https://shop.test/p/1",
            surface="ecommerce_detail",
            mode="http_only",
            deadline=datetime.now(UTC) + timedelta(seconds=20),
        )
    )
    assert [attempt.transport for attempt in plan.attempts] == ["curl", "httpx"]
    assert len({attempt.attempt_id for attempt in plan.attempts}) == 2


def test_browser_only_plan_preserves_both_engines() -> None:
    plan = AcquisitionPlanner().plan(
        PlanningRequest(
            url="https://shop.test/p/1",
            surface="ecommerce_detail",
            mode="browser_only",
            deadline=datetime.now(UTC) + timedelta(seconds=30),
        )
    )
    assert [attempt.transport for attempt in plan.attempts] == [
        "patchright",
        "real_chrome",
    ]


def test_http_only_plan_expands_proxies_in_transport_major_order() -> None:
    plan = AcquisitionPlanner().plan(
        PlanningRequest(
            url="https://shop.test/p/1",
            surface="ecommerce_detail",
            mode="http_only",
            proxies=(None, "http://proxy.test:8080"),
            deadline=datetime.now(UTC) + timedelta(seconds=20),
        )
    )

    assert [(attempt.transport, attempt.proxy) for attempt in plan.attempts] == [
        ("curl", None),
        ("curl", "http://proxy.test:8080"),
        ("httpx", None),
        ("httpx", "http://proxy.test:8080"),
    ]


def test_force_httpx_removes_curl_attempts_from_http_only_plan() -> None:
    plan = AcquisitionPlanner().plan(
        PlanningRequest(
            url="https://shop.test/p/1",
            surface="ecommerce_detail",
            mode="http_only",
            force_httpx=True,
            deadline=datetime.now(UTC) + timedelta(seconds=20),
        )
    )

    assert [attempt.transport for attempt in plan.attempts] == ["httpx"]


async def test_executor_converts_transport_errors_to_attempt_results() -> None:
    async def fail(_execution: AttemptExecution) -> AttemptResult:
        raise OSError("transport failed")

    plan = AcquisitionPlanner().plan(
        PlanningRequest(
            url="https://shop.test/p/1",
            surface="ecommerce_detail",
            mode="http_only",
            deadline=datetime.now(UTC) + timedelta(seconds=20),
        )
    )
    result = await AttemptExecutor({"curl": fail}).execute(
        plan.attempts[0],
        url="https://shop.test/p/1",
        deadline=plan.deadline,
    )
    assert result.outcome == "error"
    assert result.attempt_id == plan.attempts[0].attempt_id
    assert result.error == "OSError: transport failed"


async def test_executor_skips_attempt_after_global_deadline() -> None:
    called = False

    async def transport(_execution: AttemptExecution) -> AttemptResult:
        nonlocal called
        called = True
        raise AssertionError("must not run")

    plan = AcquisitionPlanner().plan(
        PlanningRequest(
            url="https://shop.test/p/1",
            surface="ecommerce_detail",
            mode="http_only",
            deadline=datetime.now(UTC) + timedelta(seconds=1),
        )
    )
    result = await AttemptExecutor({"curl": transport}).execute(
        plan.attempts[0],
        url="https://shop.test/p/1",
        deadline=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert result.outcome == "skipped"
    assert result.error == "global_deadline_exhausted"
    assert called is False


def test_attempt_execution_clips_timeout_to_global_deadline() -> None:
    plan = AcquisitionPlanner().plan(
        PlanningRequest(
            url="https://shop.test/p/1",
            surface="ecommerce_detail",
            mode="http_only",
            deadline=datetime.now(UTC) + timedelta(seconds=20),
        )
    )
    execution = AttemptExecution(
        spec=plan.attempts[0],
        url="https://shop.test/p/1",
        deadline=datetime.now(UTC) + timedelta(seconds=1),
    )

    assert 0 < execution.timeout_seconds <= 1


async def test_executor_bounds_running_attempt_by_global_deadline() -> None:
    async def slow_transport(_execution: AttemptExecution) -> AttemptResult:
        await asyncio.sleep(1)
        raise AssertionError("attempt should be cancelled by the executor deadline")

    plan = AcquisitionPlanner().plan(
        PlanningRequest(
            url="https://shop.test/p/1",
            surface="ecommerce_detail",
            mode="http_only",
            deadline=datetime.now(UTC) + timedelta(milliseconds=100),
        )
    )
    executor = AttemptExecutor({"curl": slow_transport})

    result = await executor.execute(
        plan.attempts[0],
        url="https://shop.test/p/1",
        deadline=plan.deadline,
    )

    assert result.outcome == "error"
    assert result.error == "attempt_deadline_exhausted"
