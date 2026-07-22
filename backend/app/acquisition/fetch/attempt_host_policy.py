from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.acquisition.fetch.browser_policy import (
    durable_vendor_block_engine_attempts,
    extract_vendor_from_reason,
    is_vendor_block_reason,
)
from app.acquisition.host_protection_memory import (
    HostProtectionPolicy,
)
from app.acquisition.runtime import PageFetchResult

if TYPE_CHECKING:
    from app.acquisition.fetch.browser_attempt_runner import BrowserAttemptRunner


async def load_active_host_policy(
    runner: BrowserAttemptRunner,
) -> HostProtectionPolicy:
    if runner.host_policy is not None:
        return runner.host_policy
    if runner.context.host_policy is not None:
        return runner.context.host_policy
    return await runner.deps.load_host_protection_policy(
        runner.context.url,
        ttl_seconds=runner.context.host_memory_ttl_seconds,
    )


def active_host_policy(runner: BrowserAttemptRunner) -> HostProtectionPolicy:
    if runner.active_host_policy is None:
        raise RuntimeError("active host policy not loaded")
    return runner.active_host_policy


def engine_attempts(runner: BrowserAttemptRunner, proxy: str | None) -> list[str]:
    attempts = runner.deps.browser_engine_attempts(
        context=runner.context,
        host_policy=active_host_policy(runner),
    )
    return durable_vendor_block_engine_attempts(
        engine_attempts=attempts,
        host_policy=active_host_policy(runner),
        forced_engine=runner.context.forced_browser_engine,
    )


def vendor_block_result_unready(
    runner: BrowserAttemptRunner, result: PageFetchResult
) -> bool:
    if not is_vendor_block_reason(runner.reason):
        return False
    diagnostics = dict(result.browser_diagnostics or {})
    outcome = str(diagnostics.get("browser_outcome") or "").strip().casefold()
    if not outcome:
        return bool(result.blocked)
    if bool(result.blocked) or outcome != "usable_content":
        return True
    probes = diagnostics.get("readiness_probes")
    if isinstance(probes, list) and probes:
        return not any(
            isinstance(probe, dict) and bool(probe.get("is_ready"))
            for probe in probes
        )
    return False


async def record_blocked_result(
    runner: BrowserAttemptRunner, result: PageFetchResult
) -> None:
    runner.outcome.last_blocked_result = result
    await runner.deps.update_host_result_memory(runner.context, result=result)
    runner.active_host_policy = await runner.deps.load_host_protection_policy(
        result.final_url or result.url or runner.context.url,
        ttl_seconds=runner.context.host_memory_ttl_seconds,
    )
    runner.context.host_policy = runner.active_host_policy


def should_mark_vendor_timeout(
    runner: BrowserAttemptRunner,
    exc: Exception,
    engine_index: int,
    engine_attempts: list[str],
) -> bool:
    return (
        isinstance(exc, (TimeoutError, asyncio.TimeoutError))
        and is_vendor_block_reason(runner.reason)
        and engine_index <= len(engine_attempts)
    )


async def mark_vendor_timeout(
    runner: BrowserAttemptRunner, engine: str, proxy: str | None
) -> None:
    await runner.deps.note_host_hard_block(
        runner.context.url,
        method=f"browser:{engine}",
        vendor=extract_vendor_from_reason(runner.reason),
        status_code=0,
        proxy_used=bool(proxy),
        ttl_seconds=runner.context.host_memory_ttl_seconds,
    )
    runner.active_host_policy = await runner.deps.load_host_protection_policy(
        runner.context.url,
        ttl_seconds=runner.context.host_memory_ttl_seconds,
    )
    runner.context.host_policy = runner.active_host_policy


def engine_attempts_after_failure_or_block(
    runner: BrowserAttemptRunner,
    engine_attempts: list[str],
    *,
    attempted_engine: str,
    engine_index: int,
) -> list[str]:
    refreshed = runner.deps.extend_engine_attempts_after_block(
        engine_attempts=engine_attempts,
        attempted_engine=attempted_engine,
        context=runner.context,
        host_policy=active_host_policy(runner),
    )
    if engine_index < len(refreshed):
        return refreshed
    return engine_attempts
