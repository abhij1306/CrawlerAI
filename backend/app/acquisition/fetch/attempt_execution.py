from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.acquisition.browser_proxy_config import display_proxy, proxy_scheme
from app.acquisition.browser_runtime import build_failed_browser_diagnostics
from app.acquisition.contracts import AttemptResult
from app.acquisition.executor import AttemptExecution
from app.acquisition.fetch import attempt_host_policy, attempt_plan
from app.acquisition.fetch.browser_attempt import (
    browser_fetch_kwargs,
    browser_fetch_with_wall_clock_timeout,
)
from app.acquisition.fetch.browser_policy import (
    attach_exception_browser_diagnostics,
    host_policy_snapshot,
)
from app.acquisition.fetch.types import AttemptOutcomeState as AttemptOutcomeState
from app.acquisition.fetch.types import AttemptRunner
from app.acquisition.runtime import PageFetchResult
from app.core.config.runtime_settings import proxy_rotation_mode

logger = logging.getLogger(__name__)


def record_executor_attempt_error(
    runner: AttemptRunner,
    attempt_result: AttemptResult,
    *,
    proxy: str | None,
    proxy_index: int,
    engine: str,
    escalation_lane: str,
) -> None:
    exc = TimeoutError(attempt_result.error or "browser attempt failed")
    setattr(exc, "browser_failure_stage", "attempt")
    runner.outcome.last_browser_error = exc
    runner.context.last_browser_attempt_diagnostics = (
        build_failed_browser_diagnostics(
            browser_reason=runner.reason,
            exc=exc,
            proxy=proxy,
            proxy_attempt_index=proxy_index,
            browser_engine=engine,
            browser_binary=engine,
            bridge_used=proxy_scheme(proxy) in {"socks5", "socks5h"},
            escalation_lane=escalation_lane,
            host_policy_snapshot=host_policy_snapshot(
                attempt_host_policy.active_host_policy(runner)
            ),
        )
    )
    attach_exception_browser_diagnostics(
        runner.outcome.last_browser_error,
        runner.context.last_browser_attempt_diagnostics,
    )


async def execute_browser_attempt(
    runner: AttemptRunner,
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
    policy_snapshot = host_policy_snapshot(
        attempt_host_policy.active_host_policy(runner)
    )
    try:
        await attempt_plan.raise_if_no_budget(
            runner, engine, engine_index, engine_attempts, "start"
        )
        await runner.deps.wait_for_host_slot(
            runner.context.url,
            ttl_seconds=runner.context.host_memory_ttl_seconds,
        )
        await attempt_plan.raise_if_no_budget(
            runner, engine, engine_index, engine_attempts, "run"
        )
        result = await browser_fetch_result(
            runner,
            proxy=proxy,
            engine=engine,
            engine_index=engine_index,
            engine_attempts=engine_attempts,
            escalation_lane=escalation_lane,
            policy_snapshot=policy_snapshot,
        )
        stamp_attempt_diagnostics(runner, result, proxy, proxy_index, engine_index)
        runner.outcome.latest_page_result = result
        if attempt_host_policy.vendor_block_result_unready(runner, result):
            result.blocked = True
        if bool(result.blocked):
            await attempt_host_policy.record_blocked_result(runner, result)
            return attempt_result(
                execution,
                started_at=started_at,
                outcome="blocked",
                result=result,
            )
        return attempt_result(
            execution,
            started_at=started_at,
            outcome="success",
            result=result,
        )
    except Exception as exc:
        await record_attempt_exception(
            runner,
            exc,
            proxy=proxy,
            proxy_index=proxy_index,
            engine=engine,
            engine_index=engine_index,
            engine_attempts=engine_attempts,
            escalation_lane=escalation_lane,
            policy_snapshot=policy_snapshot,
        )
        return attempt_result(
            execution,
            started_at=started_at,
            outcome="error",
            error=f"{type(exc).__name__}: {exc}",
            diagnostics=runner.context.last_browser_attempt_diagnostics,
        )


def attempt_result(
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
        diagnostics=dict(
            diagnostics or getattr(result, "browser_diagnostics", {}) or {}
        ),
        error=error,
    )


async def browser_fetch_result(
    runner: AttemptRunner,
    *,
    proxy: str | None,
    engine: str,
    engine_index: int,
    engine_attempts: list[str],
    escalation_lane: str,
    policy_snapshot: dict[str, object],
) -> PageFetchResult:
    timeout = runner.deps.browser_attempt_timeout_seconds(
        runner.context,
        reason=runner.reason,
        browser_engine=engine,
        engine_index=engine_index,
        engine_attempts=engine_attempts,
        host_policy=attempt_host_policy.active_host_policy(runner),
    )
    return await browser_fetch_with_wall_clock_timeout(
        runner.deps.browser_fetch,
        runner.context.url,
        timeout,
        browser_engine=engine,
        fetch_kwargs=browser_fetch_kwargs(
            runner.context,
            proxy=proxy,
            browser_engine=engine,
            reason=runner.reason,
            escalation_lane=escalation_lane,
            host_policy_snapshot=policy_snapshot,
            requested_fields=browser_requested_fields(runner),
            recovery_mode=recovery_mode(runner),
            capture_screenshot=runner.capture_screenshot,
        ),
    )


def stamp_attempt_diagnostics(
    runner: AttemptRunner,
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
        "proxy_rotation_mode": proxy_rotation_mode(runner.context.proxy_profile),
    }


async def record_attempt_exception(
    runner: AttemptRunner,
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
    runner.outcome.last_browser_error = exc
    runner.context.last_browser_attempt_diagnostics = (
        build_failed_browser_diagnostics(
            browser_reason=runner.reason,
            exc=exc,
            proxy=proxy,
            proxy_attempt_index=proxy_index,
            browser_engine=engine,
            browser_binary=engine,
            bridge_used=proxy_scheme(proxy) in {"socks5", "socks5h"},
            escalation_lane=escalation_lane,
            host_policy_snapshot=policy_snapshot,
        )
    )
    attach_exception_browser_diagnostics(
        exc, runner.context.last_browser_attempt_diagnostics
    )
    logger.debug(
        "Browser fetch failed for %s via %s engine=%s",
        runner.context.url,
        proxy or "direct",
        engine,
        exc_info=True,
    )
    if runner.deps.should_retry_patchright_with_real_chrome(
        context=runner.context,
        exc=exc,
        browser_engine=engine,
        engine_attempts=engine_attempts,
    ):
        engine_attempts.append("real_chrome")
        await runner.deps.emit_fetch_event(
            runner.context.on_event,
            "info",
            (
                "Patchright navigation failed for "
                f"{runner.context.url} with ERR_HTTP2_PROTOCOL_ERROR; retrying real Chrome"
            ),
        )
    if attempt_host_policy.should_mark_vendor_timeout(
        runner, exc, engine_index, engine_attempts
    ):
        await attempt_host_policy.mark_vendor_timeout(runner, engine, proxy)


def browser_requested_fields(runner: AttemptRunner) -> list[str]:
    if runner.requested_fields is None:
        return list(runner.context.requested_fields)
    return list(runner.requested_fields)


def recovery_mode(runner: AttemptRunner) -> str | None:
    source = (
        runner.listing_recovery_mode
        if runner.listing_recovery_mode is not None
        else runner.context.listing_recovery_mode
    )
    return str(source or "").strip() or None
