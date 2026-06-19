from __future__ import annotations

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
