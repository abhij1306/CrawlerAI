from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from dataclasses import dataclass, field

from app.acquisition.browser_proxy_config import display_proxy, proxy_scheme
from app.acquisition.browser_runtime import build_failed_browser_diagnostics
from app.acquisition.contracts import (
    AcquisitionPlan,
    AcquisitionResult,
    AttemptResult,
    AttemptSpec,
)
from app.acquisition.executor import AttemptExecution, AttemptExecutor
from app.acquisition.fetch.browser_attempt import (
    browser_fetch_kwargs,
    browser_fetch_with_wall_clock_timeout,
)
from app.acquisition.fetch.types import FetchRuntimeContext
from app.acquisition.fetch.browser_policy import (
    attach_exception_browser_diagnostics,
    browser_escalation_lane,
    durable_vendor_block_engine_attempts,
    extract_vendor_from_reason,
    host_policy_snapshot,
    is_vendor_block_reason,
)
from app.acquisition.host_protection_memory import (
    HostProtectionPolicy,
)
from app.acquisition.runtime import PageFetchResult
from app.core.config.runtime_settings import (
    proxy_rotation_mode,
)

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
EmitFetchEvent = Callable[[object, str, str], Awaitable[None]]


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

    last_browser_error: Exception | None = None
    last_blocked_result: PageFetchResult | None = None
    active_host_policy: HostProtectionPolicy | None = None
    plan_id: str = ""
    plan_started_at: datetime | None = None
    plan_deadline: datetime | None = None
    attempt_specs: list[AttemptSpec] = field(default_factory=list)
    attempt_results: list[AttemptResult] = field(default_factory=list)
    latest_page_result: PageFetchResult | None = None

    async def run(self) -> PageFetchResult:
        self._start_plan()
        self.active_host_policy = await self._load_active_host_policy()
        self.context.host_policy = self.active_host_policy
        for proxy_index, proxy in enumerate(list(self.proxies or self.context.proxies), start=1):
            result = await self._run_proxy_attempt(proxy_index, proxy)
            if result is not None:
                return result
        return self._final_result_or_error()

    async def _load_active_host_policy(self) -> HostProtectionPolicy:
        if self.host_policy is not None:
            return self.host_policy
        if self.context.host_policy is not None:
            return self.context.host_policy
        return await self.deps.load_host_protection_policy(
            self.context.url,
            ttl_seconds=self.context.host_memory_ttl_seconds,
        )

    def _active_host_policy(self) -> HostProtectionPolicy:
        if self.active_host_policy is None:
            raise RuntimeError("active host policy not loaded")
        return self.active_host_policy

    async def _run_proxy_attempt(
        self,
        proxy_index: int,
        proxy: str | None,
    ) -> PageFetchResult | None:
        engine_attempts = self._engine_attempts(proxy)
        escalation_lane = browser_escalation_lane(
            context=self.context,
            reason=self.reason,
            host_policy=self._active_host_policy(),
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
            engine_attempts = self._engine_attempts_after_failure_or_block(
                engine_attempts,
                attempted_engine=engine,
                engine_index=engine_index,
            )
        return None

    def _start_plan(self) -> None:
        self.plan_started_at = datetime.now(UTC)
        remaining = max(0.001, float(self.context.deadline_monotonic - asyncio.get_running_loop().time()))
        self.plan_deadline = self.plan_started_at + timedelta(seconds=remaining)
        plan_key = f"{self.context.url}|browser|{self.plan_started_at.isoformat()}"
        self.plan_id = sha256(plan_key.encode("utf-8")).hexdigest()[:20]

    def _engine_attempts(self, proxy: str | None) -> list[str]:
        attempts = self.deps.browser_engine_attempts(
            context=self.context,
            host_policy=self._active_host_policy(),
        )
        return durable_vendor_block_engine_attempts(
            engine_attempts=attempts,
            host_policy=self._active_host_policy(),
            forced_engine=self.context.forced_browser_engine,
        )

    async def _run_engine_attempt(
        self,
        proxy_index: int,
        proxy: str | None,
        engine: str,
        engine_index: int,
        engine_attempts: list[str],
        escalation_lane: str,
    ) -> PageFetchResult | None:
        spec = self._attempt_spec(
            proxy=proxy,
            engine=engine,
            engine_index=engine_index,
            engine_attempts=engine_attempts,
        )

        async def _adapter(execution: AttemptExecution) -> AttemptResult:
            return await self._execute_browser_attempt(
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
            deadline=self._plan_deadline(),
        )
        self.attempt_results.append(attempt_result)
        if attempt_result.outcome == "success" and self.latest_page_result is not None:
            self._attach_acquisition_diagnostics(
                self.latest_page_result,
                selected_attempt_id=attempt_result.attempt_id,
                outcome="success",
                termination_reason="attempt_selected",
            )
            return self.latest_page_result
        if attempt_result.outcome == "blocked" and self.latest_page_result is not None:
            self._attach_acquisition_diagnostics(
                self.latest_page_result,
                selected_attempt_id=attempt_result.attempt_id,
                outcome="blocked",
                termination_reason="attempt_blocked",
            )
        if attempt_result.outcome == "error" and self.last_browser_error is None:
            self._record_executor_attempt_error(
                attempt_result,
                proxy=proxy,
                proxy_index=proxy_index,
                engine=engine,
                escalation_lane=escalation_lane,
            )
        return None

    def _record_executor_attempt_error(
        self,
        attempt_result: AttemptResult,
        *,
        proxy: str | None,
        proxy_index: int,
        engine: str,
        escalation_lane: str,
    ) -> None:
        exc = TimeoutError(attempt_result.error or "browser attempt failed")
        setattr(exc, "browser_failure_stage", "attempt")
        self.last_browser_error = exc
        self.context.last_browser_attempt_diagnostics = build_failed_browser_diagnostics(
            browser_reason=self.reason,
            exc=exc,
            proxy=proxy,
            proxy_attempt_index=proxy_index,
            browser_engine=engine,
            browser_binary=engine,
            bridge_used=proxy_scheme(proxy) in {"socks5", "socks5h"},
            escalation_lane=escalation_lane,
            host_policy_snapshot=host_policy_snapshot(self._active_host_policy()),
        )
        attach_exception_browser_diagnostics(
            self.last_browser_error,
            self.context.last_browser_attempt_diagnostics,
        )

    def _attempt_spec(
        self,
        *,
        proxy: str | None,
        engine: str,
        engine_index: int,
        engine_attempts: list[str],
    ) -> AttemptSpec:
        timeout = self.deps.browser_attempt_timeout_seconds(
            self.context,
            reason=self.reason,
            browser_engine=engine,
            engine_index=engine_index,
            engine_attempts=engine_attempts,
            host_policy=self._active_host_policy(),
        )
        spec = AttemptSpec(
            attempt_id=f"{self.plan_id}-{len(self.attempt_specs) + 1}-{engine}",
            transport=engine,  # type: ignore[arg-type]
            proxy=proxy,
            warmup=True,
            interaction=bool(self.requested_fields or self.context.requested_fields),
            traversal_mode=self.context.traversal_mode,
            required_artifacts=("html",),
            timeout_seconds=max(0.001, float(timeout)),
            reason=self.reason,
        )
        self.attempt_specs.append(spec)
        return spec

    def _plan_deadline(self) -> datetime:
        if self.plan_deadline is None:
            self._start_plan()
        assert self.plan_deadline is not None
        return self.plan_deadline

    async def _execute_browser_attempt(
        self,
        execution: AttemptExecution,
        *,
        proxy_index: int,
        proxy: str | None,
        engine: str,
        engine_index: int,
        engine_attempts: list[str],
        escalation_lane: str,
    ) -> AttemptResult:
        started_at = datetime.now(UTC)
        policy_snapshot = host_policy_snapshot(self._active_host_policy())
        try:
            await self._raise_if_no_budget(engine, engine_index, engine_attempts, "start")
            await self.deps.wait_for_host_slot(
                self.context.url,
                ttl_seconds=self.context.host_memory_ttl_seconds,
            )
            await self._raise_if_no_budget(engine, engine_index, engine_attempts, "run")
            result = await self._browser_fetch_result(
                proxy=proxy,
                engine=engine,
                engine_index=engine_index,
                engine_attempts=engine_attempts,
                escalation_lane=escalation_lane,
                policy_snapshot=policy_snapshot,
            )
            self._stamp_attempt_diagnostics(result, proxy, proxy_index, engine_index)
            self.latest_page_result = result
            if bool(result.blocked):
                await self._record_blocked_result(result)
                return self._attempt_result(
                    execution,
                    started_at=started_at,
                    outcome="blocked",
                    result=result,
                )
            return self._attempt_result(
                execution,
                started_at=started_at,
                outcome="success",
                result=result,
            )
        except Exception as exc:
            await self._record_attempt_exception(
                exc,
                proxy=proxy,
                proxy_index=proxy_index,
                engine=engine,
                engine_index=engine_index,
                engine_attempts=engine_attempts,
                escalation_lane=escalation_lane,
                policy_snapshot=policy_snapshot,
            )
            return self._attempt_result(
                execution,
                started_at=started_at,
                outcome="error",
                error=f"{type(exc).__name__}: {exc}",
                diagnostics=self.context.last_browser_attempt_diagnostics,
            )

    @staticmethod
    def _attempt_result(
        execution: AttemptExecution,
        *,
        started_at: datetime,
        outcome: str,
        result: PageFetchResult | None = None,
        error: str | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> AttemptResult:
        return AttemptResult(
            attempt_id=execution.spec.attempt_id,
            outcome=outcome,  # type: ignore[arg-type]
            final_url=str(getattr(result, "final_url", "") or ""),
            status_code=getattr(result, "status_code", None),
            started_at=started_at,
            completed_at=datetime.now(UTC),
            diagnostics=dict(diagnostics or getattr(result, "browser_diagnostics", {}) or {}),
            error=error,
        )

    async def _raise_if_no_budget(
        self,
        engine: str,
        engine_index: int,
        engine_attempts: list[str],
        phase: str,
    ) -> None:
        remaining = self.deps.browser_attempt_timeout_seconds(
            self.context,
            reason=self.reason,
            browser_engine=engine,
            engine_index=engine_index,
            engine_attempts=engine_attempts,
            host_policy=self._active_host_policy(),
        )
        if remaining <= 0:
            raise TimeoutError(
                "Acquisition browser retry budget exhausted before "
                f"{engine} could {phase}"
            )

    async def _browser_fetch_result(
        self,
        *,
        proxy: str | None,
        engine: str,
        engine_index: int,
        engine_attempts: list[str],
        escalation_lane: str,
        policy_snapshot: dict[str, object],
    ) -> PageFetchResult:
        timeout = self.deps.browser_attempt_timeout_seconds(
            self.context,
            reason=self.reason,
            browser_engine=engine,
            engine_index=engine_index,
            engine_attempts=engine_attempts,
            host_policy=self._active_host_policy(),
        )
        return await browser_fetch_with_wall_clock_timeout(
            self.deps.browser_fetch,
            self.context.url,
            timeout,
            browser_engine=engine,
            fetch_kwargs=browser_fetch_kwargs(
                self.context,
                proxy=proxy,
                browser_engine=engine,
                reason=self.reason,
                escalation_lane=escalation_lane,
                host_policy_snapshot=policy_snapshot,
                requested_fields=self._browser_requested_fields(),
                recovery_mode=self._recovery_mode(),
                capture_screenshot=self.capture_screenshot,
            ),
        )

    def _stamp_attempt_diagnostics(
        self,
        result: PageFetchResult,
        proxy: str | None,
        proxy_index: int,
        engine_index: int,
    ) -> None:
        result.browser_diagnostics = {
            **dict(result.browser_diagnostics or {}),
            "proxy_url_redacted": display_proxy(proxy),
            "proxy_scheme": proxy_scheme(proxy),
            "browser_proxy_mode": "launch" if proxy else "direct",
            "proxy_attempt_index": proxy_index,
            "engine_attempt_index": engine_index,
            "proxy_rotation_mode": proxy_rotation_mode(self.context.proxy_profile),
        }

    async def _record_blocked_result(self, result: PageFetchResult) -> None:
        self.last_blocked_result = result
        await self.deps.update_host_result_memory(self.context, result=result)
        self.active_host_policy = await self.deps.load_host_protection_policy(
            result.final_url or result.url or self.context.url,
            ttl_seconds=self.context.host_memory_ttl_seconds,
        )
        self.context.host_policy = self.active_host_policy

    async def _record_attempt_exception(
        self,
        exc: Exception,
        *,
        proxy: str | None,
        proxy_index: int,
        engine: str,
        engine_index: int,
        engine_attempts: list[str],
        escalation_lane: str,
        policy_snapshot: dict[str, object],
    ) -> None:
        self.last_browser_error = exc
        self.context.last_browser_attempt_diagnostics = build_failed_browser_diagnostics(
            browser_reason=self.reason,
            exc=exc,
            proxy=proxy,
            proxy_attempt_index=proxy_index,
            browser_engine=engine,
            browser_binary=engine,
            bridge_used=proxy_scheme(proxy) in {"socks5", "socks5h"},
            escalation_lane=escalation_lane,
            host_policy_snapshot=policy_snapshot,
        )
        attach_exception_browser_diagnostics(exc, self.context.last_browser_attempt_diagnostics)
        logger.debug(
            "Browser fetch failed for %s via %s engine=%s",
            self.context.url,
            proxy or "direct",
            engine,
            exc_info=True,
        )
        if self.deps.should_retry_patchright_with_real_chrome(
            context=self.context,
            exc=exc,
            browser_engine=engine,
            engine_attempts=engine_attempts,
        ):
            engine_attempts.append("real_chrome")
            await self.deps.emit_fetch_event(
                self.context.on_event,
                "info",
                (
                    "Patchright navigation failed for "
                    f"{self.context.url} with ERR_HTTP2_PROTOCOL_ERROR; retrying real Chrome"
                ),
            )
        if self._should_mark_vendor_timeout(exc, engine_index, engine_attempts):
            await self._mark_vendor_timeout(engine, proxy)

    def _should_mark_vendor_timeout(
        self,
        exc: Exception,
        engine_index: int,
        engine_attempts: list[str],
    ) -> bool:
        return (
            isinstance(exc, (TimeoutError, asyncio.TimeoutError))
            and is_vendor_block_reason(self.reason)
            and engine_index <= len(engine_attempts)
        )

    async def _mark_vendor_timeout(self, engine: str, proxy: str | None) -> None:
        await self.deps.note_host_hard_block(
            self.context.url,
            method=f"browser:{engine}",
            vendor=extract_vendor_from_reason(self.reason),
            status_code=0,
            proxy_used=bool(proxy),
            ttl_seconds=self.context.host_memory_ttl_seconds,
        )
        self.active_host_policy = await self.deps.load_host_protection_policy(
            self.context.url,
            ttl_seconds=self.context.host_memory_ttl_seconds,
        )
        self.context.host_policy = self.active_host_policy

    def _engine_attempts_after_failure_or_block(
        self,
        engine_attempts: list[str],
        *,
        attempted_engine: str,
        engine_index: int,
    ) -> list[str]:
        refreshed = self.deps.extend_engine_attempts_after_block(
            engine_attempts=engine_attempts,
            attempted_engine=attempted_engine,
            context=self.context,
            host_policy=self._active_host_policy(),
        )
        if engine_index < len(refreshed):
            return refreshed
        return engine_attempts

    def _browser_requested_fields(self) -> list[str]:
        if self.requested_fields is None:
            return list(self.context.requested_fields)
        return list(self.requested_fields)

    def _recovery_mode(self) -> str | None:
        source = (
            self.listing_recovery_mode
            if self.listing_recovery_mode is not None
            else self.context.listing_recovery_mode
        )
        return str(source or "").strip() or None

    def _final_result_or_error(self) -> PageFetchResult:
        if self.last_blocked_result is not None:
            self._attach_acquisition_diagnostics(
                self.last_blocked_result,
                selected_attempt_id=(
                    self.attempt_results[-1].attempt_id
                    if self.attempt_results
                    else None
                ),
                outcome="blocked",
                termination_reason="browser_attempts_blocked",
            )
            return self.last_blocked_result
        if self.last_browser_error is not None:
            attach_exception_browser_diagnostics(
                self.last_browser_error,
                self.context.last_browser_attempt_diagnostics,
            )
            setattr(
                self.last_browser_error,
                "acquisition_diagnostics",
                self._acquisition_diagnostics(
                    selected_attempt_id=None,
                    outcome="error",
                    termination_reason="browser_attempts_exhausted",
                ),
            )
            raise self.last_browser_error
        raise RuntimeError(f"Failed to fetch {self.context.url} in browser")

    def _attach_acquisition_diagnostics(
        self,
        result: PageFetchResult,
        *,
        selected_attempt_id: str | None,
        outcome: str,
        termination_reason: str,
    ) -> None:
        result.acquisition_diagnostics = self._acquisition_diagnostics(
            selected_attempt_id=selected_attempt_id,
            outcome=outcome,
            termination_reason=termination_reason,
        )

    def _acquisition_diagnostics(
        self,
        *,
        selected_attempt_id: str | None,
        outcome: str,
        termination_reason: str,
    ) -> dict[str, object]:
        plan = AcquisitionPlan(
            plan_id=self.plan_id or "browser-plan",
            attempts=tuple(self.attempt_specs),
            created_at=self.plan_started_at or datetime.now(UTC),
            deadline=self._plan_deadline(),
        )
        canonical_result = AcquisitionResult(
            plan_id=plan.plan_id,
            attempts=tuple(self.attempt_results),
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
