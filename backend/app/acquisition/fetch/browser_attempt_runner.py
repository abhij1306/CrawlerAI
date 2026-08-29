from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from app.acquisition.contracts import (
    AttemptResult,
)
from app.acquisition.events import AcquisitionEvent, AcquisitionEventHandler
from app.acquisition.executor import AttemptExecution, AttemptExecutor
from app.acquisition.fetch import (
    attempt_execution,
    attempt_host_policy,
    attempt_plan,
)
from app.acquisition.fetch.browser_policy import (
    attach_exception_browser_diagnostics,
    browser_escalation_lane,
)
from app.acquisition.fetch.types import (
    AttemptOutcomeState,
    AttemptPlanState,
    FetchRuntimeContext,
)
from app.acquisition.host_protection_memory import (
    HostProtectionPolicy,
)
from app.acquisition.runtime import PageFetchResult

logger = logging.getLogger(__name__)

BrowserFetch = Callable[..., Coroutine[Any, Any, PageFetchResult]]
BrowserEngineAttempts = Callable[
    ...,
    list[str],
]
ExtendEngineAttempts = Callable[
    ...,
    list[str],
]
AttemptTimeout = Callable[
    ...,
    float,
]
RetryPatchright = Callable[
    ...,
    bool,
]
UpdateHostMemory = Callable[
    [FetchRuntimeContext],
    Awaitable[None],
]
EmitFetchEvent = Callable[
    [AcquisitionEventHandler | None, AcquisitionEvent], Awaitable[None]
]


@dataclass(slots=True)
class BrowserAttemptDependencies:
    browser_fetch: BrowserFetch
    browser_engine_attempts: BrowserEngineAttempts
    extend_engine_attempts_after_block: ExtendEngineAttempts
    browser_attempt_timeout_seconds: AttemptTimeout
    should_retry_patchright_with_real_chrome: RetryPatchright
    update_host_result_memory: Callable[..., Awaitable[None]]
    emit_fetch_event: EmitFetchEvent
    load_host_protection_policy: Callable[..., Awaitable[HostProtectionPolicy]]
    note_host_hard_block: Callable[..., Awaitable[object]]
    wait_for_host_slot: Callable[..., Awaitable[None]]


@dataclass(slots=True)
class BrowserAttemptRunner:
    context: FetchRuntimeContext
    reason: str
    requested_fields: list[str] | None
    listing_recovery_mode: str | None
    capture_screenshot: bool
    proxies: list[str | None] | None
    host_policy: HostProtectionPolicy | None
    deps: BrowserAttemptDependencies

    plan: AttemptPlanState = field(default_factory=AttemptPlanState)
    outcome: AttemptOutcomeState = field(default_factory=AttemptOutcomeState)
    active_host_policy: HostProtectionPolicy | None = None

    async def run(self) -> PageFetchResult:
        attempt_plan.start_plan(self)
        self.active_host_policy = await attempt_host_policy.load_active_host_policy(
            self
        )
        self.context.host_policy = self.active_host_policy
        for proxy_index, proxy in enumerate(
            list(self.proxies or self.context.proxies), start=1
        ):
            if self.plan.retry_budget_exhausted:
                break
            result = await self._run_proxy_attempt(proxy_index, proxy)
            if result is not None:
                return result
        return self._final_result_or_error()

    async def _run_proxy_attempt(
        self,
        proxy_index: int,
        proxy: str | None,
    ) -> PageFetchResult | None:
        if self.plan.retry_budget_exhausted:
            return None
        engine_attempts = attempt_host_policy.engine_attempts(self)
        escalation_lane = browser_escalation_lane(
            context=self.context,
            reason=self.reason,
            host_policy=attempt_host_policy.active_host_policy(self),
            proxy=proxy,
        )
        engine_index = 0
        while engine_index < len(engine_attempts):
            engine = engine_attempts[engine_index]
            engine_index += 1
            result = await self._run_engine_attempt(
                proxy_index,
                proxy,
                engine,
                engine_index,
                engine_attempts,
                escalation_lane,
            )
            if result is not None:
                return result
            if self.plan.retry_budget_exhausted or not attempt_plan.has_attempt_budget(
                self
            ):
                break
            engine_attempts = (
                attempt_host_policy.engine_attempts_after_failure_or_block(
                    self,
                    engine_attempts,
                    attempted_engine=engine,
                    engine_index=engine_index,
                )
            )
        return None

    async def _run_engine_attempt(
        self,
        proxy_index: int,
        proxy: str | None,
        engine: str,
        engine_index: int,
        engine_attempts: list[str],
        escalation_lane: str,
    ) -> PageFetchResult | None:
        remaining_before_spec = max(
            0.0,
            self.context.deadline_monotonic - time.perf_counter(),
        )
        spec = attempt_plan.attempt_spec(
            self,
            proxy=proxy,
            engine=engine,
            engine_index=engine_index,
            engine_attempts=engine_attempts,
        )

        async def _adapter(execution: AttemptExecution) -> AttemptResult:
            return await attempt_execution.execute_browser_attempt(
                self,
                execution,
                proxy_index=proxy_index,
                proxy=proxy,
                engine=engine,
                engine_index=engine_index,
                engine_attempts=engine_attempts,
                escalation_lane=escalation_lane,
            )

        attempt_result = await AttemptExecutor({engine: _adapter}).execute(
            spec,
            url=self.context.url,
            deadline=attempt_plan.plan_deadline(self),
        )
        self.plan.attempt_results.append(attempt_result)
        if attempt_plan.attempt_consumed_remaining_budget(
            attempt_result,
            spec=spec,
            remaining_before_spec=remaining_before_spec,
        ):
            self.plan.retry_budget_exhausted = True
        if (
            attempt_result.outcome == "success"
            and self.outcome.latest_page_result is not None
        ):
            attempt_plan.attach_acquisition_diagnostics(
                self,
                self.outcome.latest_page_result,
                selected_attempt_id=attempt_result.attempt_id,
                outcome="success",
                termination_reason="attempt_selected",
            )
            return self.outcome.latest_page_result
        if (
            attempt_result.outcome == "blocked"
            and self.outcome.latest_page_result is not None
        ):
            attempt_plan.attach_acquisition_diagnostics(
                self,
                self.outcome.latest_page_result,
                selected_attempt_id=attempt_result.attempt_id,
                outcome="blocked",
                termination_reason="attempt_blocked",
            )
        if (
            attempt_result.outcome == "error"
            and self.outcome.last_browser_error is None
        ):
            attempt_execution.record_executor_attempt_error(
                self,
                attempt_result,
                proxy=proxy,
                proxy_index=proxy_index,
                engine=engine,
                escalation_lane=escalation_lane,
            )
        return None

    def _final_result_or_error(self) -> PageFetchResult:
        if self.outcome.last_blocked_result is not None:
            attempt_plan.attach_acquisition_diagnostics(
                self,
                self.outcome.last_blocked_result,
                selected_attempt_id=(
                    self.plan.attempt_results[-1].attempt_id
                    if self.plan.attempt_results
                    else None
                ),
                outcome="blocked",
                termination_reason="browser_attempts_blocked",
            )
            return self.outcome.last_blocked_result
        if self.outcome.last_browser_error is not None:
            attach_exception_browser_diagnostics(
                self.outcome.last_browser_error,
                self.context.last_browser_attempt_diagnostics,
            )
            setattr(
                self.outcome.last_browser_error,
                "acquisition_diagnostics",
                attempt_plan.acquisition_diagnostics(
                    self,
                    selected_attempt_id=None,
                    outcome="error",
                    termination_reason="browser_attempts_exhausted",
                ),
            )
            raise self.outcome.last_browser_error
        raise RuntimeError(f"Failed to fetch {self.context.url} in browser")
