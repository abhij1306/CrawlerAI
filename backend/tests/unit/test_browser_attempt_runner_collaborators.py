from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.acquisition.fetch import (
    attempt_execution,
    attempt_host_policy,
    attempt_plan,
)
from app.acquisition.fetch.attempt_execution import AttemptOutcomeState
from app.acquisition.fetch.attempt_plan import AttemptPlanState
from app.acquisition.fetch.browser_attempt_runner import (
    BrowserAttemptDependencies,
    BrowserAttemptRunner,
)
from app.core.config.runtime_settings import crawler_runtime_settings

pytestmark = pytest.mark.unit


def _deps(**overrides) -> BrowserAttemptDependencies:
    values = {
        "browser_fetch": lambda *args, **kwargs: None,
        "browser_engine_attempts": lambda **kwargs: ["patchright"],
        "extend_engine_attempts_after_block": lambda **kwargs: list(
            kwargs["engine_attempts"]
        ),
        "browser_attempt_timeout_seconds": lambda *args, **kwargs: 5.0,
        "should_retry_patchright_with_real_chrome": lambda **kwargs: False,
        "update_host_result_memory": lambda **kwargs: None,
        "emit_fetch_event": lambda *args: None,
        "load_host_protection_policy": lambda *args, **kwargs: None,
        "note_host_hard_block": lambda *args, **kwargs: None,
        "wait_for_host_slot": lambda *args, **kwargs: None,
    }
    values.update(overrides)
    return BrowserAttemptDependencies(**values)


def _context(**overrides) -> SimpleNamespace:
    values = {
        "url": "https://shop.test/products/1",
        "deadline_monotonic": time.perf_counter() + 60.0,
        "proxies": [],
        "host_policy": None,
        "host_memory_ttl_seconds": 60,
        "requested_fields": [],
        "traversal_mode": None,
        "forced_browser_engine": None,
        "listing_recovery_mode": None,
        "proxy_profile": None,
        "on_event": None,
        "last_browser_attempt_diagnostics": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _runner(**overrides) -> BrowserAttemptRunner:
    values = {
        "context": _context(),
        "reason": "detail",
        "requested_fields": None,
        "listing_recovery_mode": None,
        "capture_screenshot": False,
        "proxies": [],
        "host_policy": None,
        "deps": _deps(),
    }
    values.update(overrides)
    return BrowserAttemptRunner(**values)


def test_runner_groups_mutable_state_into_plan_and_outcome() -> None:
    runner = _runner()
    assert isinstance(runner.plan, AttemptPlanState)
    assert isinstance(runner.outcome, AttemptOutcomeState)
    assert runner.plan.plan_id == ""
    assert runner.plan.attempt_specs == []
    assert runner.plan.attempt_results == []
    assert runner.plan.retry_budget_exhausted is False
    assert runner.outcome.latest_page_result is None
    assert runner.outcome.last_blocked_result is None
    assert runner.outcome.last_browser_error is None
    assert runner.active_host_policy is None


def test_start_plan_populates_plan_state() -> None:
    runner = _runner()
    attempt_plan.start_plan(runner)
    assert len(runner.plan.plan_id) == 20
    assert runner.plan.plan_started_at is not None
    assert runner.plan.plan_deadline is not None
    assert runner.plan.plan_deadline > runner.plan.plan_started_at


def test_plan_deadline_starts_plan_when_missing() -> None:
    runner = _runner()
    deadline = attempt_plan.plan_deadline(runner)
    assert runner.plan.plan_deadline is deadline
    assert runner.plan.plan_started_at is not None


def test_minimum_attempt_budget_clamps_negative_setting_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        crawler_runtime_settings, "browser_attempt_min_runtime_seconds", -5.0
    )
    assert attempt_plan.minimum_attempt_budget() == 0.0


def test_has_attempt_budget_uses_context_deadline() -> None:
    runner = _runner()
    assert attempt_plan.has_attempt_budget(runner) is True
    expired = _runner(
        context=_context(deadline_monotonic=time.perf_counter() - 1.0)
    )
    assert attempt_plan.has_attempt_budget(expired) is False


def test_attempt_consumed_remaining_budget_only_for_timeout_errors() -> None:
    spec = SimpleNamespace(timeout_seconds=10.0)
    timeout_result = SimpleNamespace(error="TimeoutError: Browser nav")
    other_result = SimpleNamespace(error="ValueError: boom")
    assert (
        attempt_plan.attempt_consumed_remaining_budget(
            timeout_result, spec=spec, remaining_before_spec=10.0
        )
        is True
    )
    assert (
        attempt_plan.attempt_consumed_remaining_budget(
            timeout_result, spec=spec, remaining_before_spec=60.0
        )
        is False
    )
    assert (
        attempt_plan.attempt_consumed_remaining_budget(
            other_result, spec=spec, remaining_before_spec=10.0
        )
        is False
    )


def test_attempt_spec_appends_to_plan_specs() -> None:
    runner = _runner()
    runner.active_host_policy = SimpleNamespace()
    attempt_plan.start_plan(runner)
    spec = attempt_plan.attempt_spec(
        runner,
        proxy=None,
        engine="patchright",
        engine_index=1,
        engine_attempts=["patchright"],
    )
    assert runner.plan.attempt_specs == [spec]
    assert spec.attempt_id.startswith(f"{runner.plan.plan_id}-1-patchright")
    assert spec.timeout_seconds == 5.0


def test_acquisition_diagnostics_payload_shape() -> None:
    runner = _runner()
    runner.active_host_policy = SimpleNamespace()
    attempt_plan.start_plan(runner)
    spec = attempt_plan.attempt_spec(
        runner,
        proxy=None,
        engine="patchright",
        engine_index=1,
        engine_attempts=["patchright"],
    )
    payload = attempt_plan.acquisition_diagnostics(
        runner,
        selected_attempt_id=None,
        outcome="error",
        termination_reason="browser_attempts_exhausted",
    )
    assert payload["termination_reason"] == "browser_attempts_exhausted"
    assert payload["plan"]["plan_id"] == runner.plan.plan_id
    assert payload["plan"]["attempts"][0]["attempt_id"] == spec.attempt_id
    assert payload["result"]["outcome"] == "error"


def test_active_host_policy_raises_when_not_loaded() -> None:
    runner = _runner()
    with pytest.raises(RuntimeError, match="active host policy not loaded"):
        attempt_host_policy.active_host_policy(runner)


def test_engine_attempts_after_failure_or_block_keeps_current_when_not_extended() -> None:
    runner = _runner()
    runner.active_host_policy = SimpleNamespace()
    current = ["patchright"]
    refreshed = attempt_host_policy.engine_attempts_after_failure_or_block(
        runner,
        current,
        attempted_engine="patchright",
        engine_index=1,
    )
    assert refreshed is current


def test_should_mark_vendor_timeout_only_for_vendor_reasons() -> None:
    runner = _runner(reason="vendor-block:datadome")
    assert (
        attempt_host_policy.should_mark_vendor_timeout(
            runner, TimeoutError(), 1, ["patchright"]
        )
        is True
    )
    assert (
        attempt_host_policy.should_mark_vendor_timeout(
            runner, ValueError(), 1, ["patchright"]
        )
        is False
    )
    non_vendor = _runner(reason="detail")
    assert (
        attempt_host_policy.should_mark_vendor_timeout(
            non_vendor, TimeoutError(), 1, ["patchright"]
        )
        is False
    )


def test_vendor_block_result_unready_requires_ready_probe() -> None:
    runner = _runner(reason="vendor-block:datadome")
    ready = SimpleNamespace(
        blocked=False,
        browser_diagnostics={
            "browser_outcome": "usable_content",
            "readiness_probes": [{"is_ready": True}],
        },
    )
    unready = SimpleNamespace(
        blocked=False,
        browser_diagnostics={
            "browser_outcome": "usable_content",
            "readiness_probes": [{"is_ready": False}],
        },
    )
    assert attempt_host_policy.vendor_block_result_unready(runner, ready) is False
    assert attempt_host_policy.vendor_block_result_unready(runner, unready) is True
    non_vendor = _runner(reason="detail")
    assert (
        attempt_host_policy.vendor_block_result_unready(non_vendor, unready) is False
    )


def test_browser_requested_fields_and_recovery_mode_fallbacks() -> None:
    runner = _runner(context=_context(requested_fields=["price"]))
    assert attempt_execution.browser_requested_fields(runner) == ["price"]
    override = _runner(requested_fields=["title"])
    assert attempt_execution.browser_requested_fields(override) == ["title"]
    assert attempt_execution.recovery_mode(runner) is None
    recovery = _runner(listing_recovery_mode="  anchor ")
    assert attempt_execution.recovery_mode(recovery) == "anchor"


async def test_run_orchestrates_collaborators_and_raises_when_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    policy = SimpleNamespace()

    def _fake_start_plan(runner: BrowserAttemptRunner) -> None:
        calls.append("start_plan")
        runner.plan.plan_deadline = runner.plan.plan_deadline or None

    async def _fake_load_policy(runner: BrowserAttemptRunner):
        calls.append("load_policy")
        return policy

    monkeypatch.setattr(attempt_plan, "start_plan", _fake_start_plan)
    monkeypatch.setattr(
        attempt_host_policy, "load_active_host_policy", _fake_load_policy
    )
    runner = _runner(proxies=[])
    with pytest.raises(RuntimeError, match="Failed to fetch"):
        await runner.run()
    assert calls == ["start_plan", "load_policy"]
    assert runner.active_host_policy is policy
    assert runner.context.host_policy is policy
