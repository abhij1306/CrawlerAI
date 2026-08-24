from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any, Literal

import httpx

from app.acquisition.browser_proxy_config import display_proxy, proxy_scheme
from app.acquisition.fetch.browser_policy import (
    attach_browser_attempt_diagnostics,
    browser_escalation_allowed,
    browser_escalation_proxies,
    hard_browser_requirement,
    vendor_confirmed_block,
)

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
from app.acquisition.runtime import is_non_retryable_http_status
from app.acquisition.platform_policy import resolve_platform_runtime_policy
from app.core.config.pipeline_reasons import (
    BROWSER_ESCALATION_SKIPPED_INSUFFICIENT_BUDGET,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.proxy_secrets import redact_secret_text

AsyncDependency = Callable[..., Awaitable[Any]]
SyncDependency = Callable[..., Any]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HttpAttemptDependencies:
    curl_fetcher: AsyncDependency
    http_fetcher: AsyncDependency
    resolve_http_timeout: SyncDependency
    remaining_timeout_seconds: SyncDependency
    emit_fetch_event: AsyncDependency
    wait_for_host_slot: AsyncDependency
    should_escalate_to_browser: AsyncDependency
    run_browser_attempts: AsyncDependency
    update_host_result_memory: AsyncDependency
    apply_protected_host_backoff: AsyncDependency
    note_host_hard_block: AsyncDependency
    load_host_protection_policy: AsyncDependency
    export_cookie_header_for_domain: AsyncDependency


async def run_planned_http_only(
    context: Any,
    *,
    deps: HttpAttemptDependencies,
    force_httpx: bool,
) -> PageFetchResult:
    (
        result,
        _vendor_block_confirmed,
        diagnostics,
        attempt_results,
    ) = await run_planned_http_chain(
        context,
        deps=deps,
        force_httpx=force_httpx,
        allow_browser_escalation=False,
        exhaustion_reason="http_transports_exhausted",
    )
    if result is not None:
        return result
    raise _http_exhaustion_error(
        context,
        diagnostics=diagnostics,
        attempt_results=attempt_results,
    )


async def run_planned_http_chain(
    context: Any,
    *,
    deps: HttpAttemptDependencies,
    force_httpx: bool,
    allow_browser_escalation: bool,
    exhaustion_reason: str = "http_transports_exhausted",
) -> tuple[PageFetchResult | None, bool, dict[str, object], list[AttemptResult]]:
    remaining = max(0.001, float(deps.remaining_timeout_seconds(context)))
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
    page_results: dict[str, tuple[PageFetchResult, bool]] = {}

    async def execute_attempt(execution: AttemptExecution) -> AttemptResult:
        return await _execute_planned_http_attempt(
            context,
            execution=execution,
            page_results=page_results,
            deps=deps,
            allow_browser_escalation=allow_browser_escalation,
        )

    executor = AttemptExecutor({"curl": execute_attempt, "httpx": execute_attempt})
    attempt_results: list[AttemptResult] = []
    vendor_block_confirmed = False
    for spec in plan.attempts:
        attempt_result = await executor.execute(
            spec,
            url=context.url,
            deadline=plan.deadline,
        )
        attempt_results.append(attempt_result)
        if bool(attempt_result.diagnostics.get("browser_escalation_failed")):
            return None, True, {}, attempt_results
        selected = page_results.get(spec.attempt_id)
        if selected is None:
            continue
        page_result, attempt_vendor_block_confirmed = selected
        vendor_block_confirmed = (
            vendor_block_confirmed or attempt_vendor_block_confirmed
        )
        page_result.acquisition_diagnostics = _planned_acquisition_diagnostics(
            plan,
            attempt_results,
            selected_attempt_id=spec.attempt_id,
            outcome=_acquisition_outcome(attempt_result.outcome),
            termination_reason="attempt_selected",
        )
        return (
            page_result,
            vendor_block_confirmed,
            dict(page_result.acquisition_diagnostics),
            attempt_results,
        )

    diagnostics = _planned_acquisition_diagnostics(
        plan,
        attempt_results,
        selected_attempt_id=None,
        outcome="error",
        termination_reason=exhaustion_reason,
    )
    return None, vendor_block_confirmed, diagnostics, attempt_results


def _http_exhaustion_error(
    context: Any,
    *,
    diagnostics: dict[str, object],
    attempt_results: list[AttemptResult],
) -> Exception:
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
    return error


async def _execute_planned_http_attempt(
    context: Any,
    *,
    execution: AttemptExecution,
    page_results: dict[str, tuple[PageFetchResult, bool]],
    deps: HttpAttemptDependencies,
    allow_browser_escalation: bool,
) -> AttemptResult:
    started_at = datetime.now(UTC)
    fetcher = (
        deps.curl_fetcher if execution.spec.transport == "curl" else deps.http_fetcher
    )
    timeout_seconds = min(
        float(deps.resolve_http_timeout(context)),
        execution.timeout_seconds,
    )
    raw_result = await _attempt_http_fetch(
        context,
        fetcher=fetcher,
        proxy=execution.spec.proxy,
        timeout_seconds=timeout_seconds,
        deps=deps,
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
                redact_secret_text(f"{type(error).__name__}: {error}")
                if error is not None
                else "transport_attempt_failed"
            ),
        )

    try:
        handled_result, vendor_block_confirmed = await handle_planned_http_result(
            context,
            result=raw_result,
            proxy=execution.spec.proxy,
            allow_browser_escalation=allow_browser_escalation,
            deps=deps,
        )
    except Exception as exc:
        context.last_error = exc
        vendor = vendor_confirmed_block(raw_result)
        logger.debug(
            "Browser escalation after HTTP failure errored; returning the error "
            "outcome to the ladder: %s",
            type(exc).__name__,
            exc_info=True,
        )
        return AttemptResult(
            attempt_id=execution.spec.attempt_id,
            outcome="error",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            diagnostics={
                "transport": execution.spec.transport,
                "proxy": display_proxy(execution.spec.proxy),
                "vendor_block_confirmed": bool(vendor),
                "browser_escalation_failed": True,
            },
            error=redact_secret_text(f"{type(exc).__name__}: {exc}"),
        )
    if not isinstance(handled_result, PageFetchResult):
        return AttemptResult(
            attempt_id=execution.spec.attempt_id,
            outcome="error",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            error="http_result_not_selected",
        )

    page_results[execution.spec.attempt_id] = (
        handled_result,
        bool(vendor_block_confirmed),
    )
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


_http_attempt_failed = object()


async def _attempt_http_fetch(
    context: Any,
    *,
    fetcher: AsyncDependency,
    proxy: str | None,
    timeout_seconds: float | None = None,
    deps: HttpAttemptDependencies,
) -> PageFetchResult | object:
    http_timeout = (
        float(deps.resolve_http_timeout(context))
        if timeout_seconds is None
        else max(0.001, float(timeout_seconds))
    )
    await deps.emit_fetch_event(
        context.on_event,
        "info",
        (
            f"HTTP fetch via {fetcher.__name__} "
            f"(timeout={http_timeout:.1f}s, proxy={display_proxy(proxy)})"
        ),
    )
    try:
        await deps.wait_for_host_slot(
            context.url,
            ttl_seconds=context.host_memory_ttl_seconds,
        )
        if proxy is not None:
            return await fetcher(context.url, http_timeout, proxy=proxy)
        return await fetcher(context.url, http_timeout)
    except (httpx.HTTPError, OSError) as exc:
        context.last_error = exc
        logger.debug(
            "Fetch failure for %s via %s (%s)",
            context.url,
            fetcher.__name__,
            display_proxy(proxy),
            exc_info=True,
        )
        await deps.emit_fetch_event(
            context.on_event,
            "warning",
            f"HTTP fetch failed via {fetcher.__name__}: {type(exc).__name__}",
        )
        return _http_attempt_failed


async def handle_planned_http_result(
    context: Any,
    *,
    result: PageFetchResult,
    proxy: str | None,
    allow_browser_escalation: bool = True,
    deps: HttpAttemptDependencies,
) -> tuple[PageFetchResult | object | None, bool]:
    vendor = vendor_confirmed_block(result)
    if vendor or bool(result.blocked):
        await deps.apply_protected_host_backoff(
            result.final_url or result.url or context.url,
            ttl_seconds=context.host_memory_ttl_seconds,
        )
    result_runtime_policy = resolve_platform_runtime_policy(
        result.final_url or result.url,
        result.html,
        surface=context.surface,
    )
    should_browser_escalate = bool(vendor) or await deps.should_escalate_to_browser(
        result,
        surface=context.surface,
        runtime_policy=result_runtime_policy,
    )
    if should_browser_escalate and (vendor or bool(result.blocked)):
        await _record_http_block_memory(
            context, result=result, proxy=proxy, vendor=vendor, deps=deps
        )
    if allow_browser_escalation and _http_browser_escalation_allowed(
        context,
        should_browser_escalate=should_browser_escalate,
        runtime_policy=result_runtime_policy,
    ):
        return await _handle_browser_escalation(
            context, result=result, proxy=proxy, vendor=vendor, deps=deps
        )
    if is_non_retryable_http_status(result.status_code):
        logger.info(
            "Returning non-retryable HTTP status %s for %s without browser fallback",
            result.status_code,
            context.url,
        )
        await deps.update_host_result_memory(context, result=result)
        return result, bool(vendor)
    attach_browser_attempt_diagnostics(
        result,
        diagnostics=context.last_browser_attempt_diagnostics,
    )
    await deps.update_host_result_memory(context, result=result)
    return result, bool(vendor)


async def _handle_browser_escalation(
    context: Any,
    *,
    result: PageFetchResult,
    proxy: str | None,
    vendor: str | None,
    deps: HttpAttemptDependencies,
) -> tuple[PageFetchResult | object, bool]:
    if context.browser_first_failed and not (vendor or bool(result.blocked)):
        attach_browser_attempt_diagnostics(
            result, diagnostics=context.last_browser_attempt_diagnostics
        )
        return result, bool(vendor)
    if _remaining_browser_timeout_below_retry_floor(context, deps=deps):
        result.browser_diagnostics = {
            **dict(result.browser_diagnostics or {}),
            "browser_escalation_skipped": BROWSER_ESCALATION_SKIPPED_INSUFFICIENT_BUDGET,
        }
        return result, bool(vendor)
    browser_result = await _escalate_http_result_to_browser(
        context, result=result, proxy=proxy, vendor=vendor, deps=deps
    )
    unresolved = bool(vendor) and not _browser_result_is_ready(browser_result)
    if unresolved:
        browser_result.blocked = True
    return browser_result, unresolved


async def run_browser_http_handoff(
    context: Any,
    *,
    deps: HttpAttemptDependencies,
) -> PageFetchResult | None:
    if not _browser_http_handoff_allowed(context):
        return None
    engines = _handoff_cookie_engines(context.handoff_cookie_engine)
    for proxy in context.proxies:
        if proxy is not None:
            continue
        for engine in engines:
            cookie_header = await _handoff_cookie_header(
                context, deps=deps, engine=engine
            )
            if not cookie_header:
                continue
            result = await _run_handoff_curl(
                context,
                deps=deps,
                proxy=proxy,
                engine=engine,
                cookie_header=cookie_header,
            )
            if result is None:
                continue
            if not bool(result.blocked) and not await deps.should_escalate_to_browser(
                result,
                surface=context.surface,
                runtime_policy=resolve_platform_runtime_policy(
                    result.final_url or result.url,
                    result.html,
                    surface=context.surface,
                ),
            ):
                return result
            await deps.apply_protected_host_backoff(
                result.final_url or result.url or context.url,
                ttl_seconds=context.host_memory_ttl_seconds,
            )
            context.last_browser_attempt_diagnostics = dict(result.browser_diagnostics)
            return None
    return None


def _browser_http_handoff_allowed(context: Any) -> bool:
    host_policy = context.host_policy
    if host_policy is None or not crawler_runtime_settings.browser_http_handoff_enabled:
        return False
    if (
        hard_browser_requirement(context=context)
        or context.fetch_mode == "browser_only"
    ):
        return False
    if context.prefer_browser and not context.prefer_curl_handoff:
        return False
    return bool(host_policy.prefer_browser or context.prefer_curl_handoff)


async def _handoff_cookie_header(
    context: Any,
    *,
    deps: HttpAttemptDependencies,
    engine: str,
) -> str | None:
    try:
        return await deps.export_cookie_header_for_domain(
            context.url,
            browser_engine=engine,
            run_id=context.run_id,
        )
    except Exception:
        logger.warning(
            "Cookie export failed for handoff engine=%s url=%s",
            engine,
            context.url,
            exc_info=True,
        )
        return None


async def _run_handoff_curl(
    context: Any,
    *,
    deps: HttpAttemptDependencies,
    proxy: str | None,
    engine: str,
    cookie_header: str,
) -> PageFetchResult | None:
    handoff_timeout = min(
        float(crawler_runtime_settings.browser_http_handoff_timeout_seconds),
        deps.resolve_http_timeout(context),
    )
    try:
        result = await deps.curl_fetcher(
            context.url,
            handoff_timeout,
            proxy=proxy,
            cookie_header=cookie_header,
        )
    except (httpx.HTTPError, OSError):
        logger.debug(
            "Handoff curl_fetch failed for %s; skipping handoff",
            context.url,
            exc_info=True,
        )
        return None
    result.browser_diagnostics = {
        **dict(result.browser_diagnostics or {}),
        "browser_http_handoff": True,
        "handoff_cookie_engine": engine,
        "proxy_url_redacted": display_proxy(proxy),
        "proxy_scheme": proxy_scheme(proxy),
    }
    return result


def _handoff_cookie_engines(preferred_engine: str | None = None) -> tuple[str, ...]:
    configured = tuple(
        str(engine or "").strip().lower()
        for engine in tuple(
            crawler_runtime_settings.browser_http_handoff_cookie_engines or ()
        )
        if str(engine or "").strip()
    )
    preferred: list[str] = []
    normalized_preferred = str(preferred_engine or "").strip().lower()
    if normalized_preferred in {"real_chrome", "patchright"}:
        preferred.append(normalized_preferred)
    for engine in configured:
        if engine in {"real_chrome", "patchright"} and engine not in preferred:
            preferred.append(engine)
    return tuple(preferred)


async def _record_http_block_memory(
    context: Any,
    *,
    result: PageFetchResult,
    proxy: str | None,
    vendor: str | None,
    deps: HttpAttemptDependencies,
) -> None:
    target_url = result.final_url or result.url or context.url
    await deps.note_host_hard_block(
        target_url,
        method=result.method,
        vendor=vendor,
        status_code=result.status_code,
        proxy_used=proxy is not None,
        ttl_seconds=context.host_memory_ttl_seconds,
    )
    context.host_policy = await deps.load_host_protection_policy(
        target_url,
        ttl_seconds=context.host_memory_ttl_seconds,
    )


def _http_browser_escalation_allowed(
    context: Any,
    *,
    should_browser_escalate: bool,
    runtime_policy: dict[str, object],
) -> bool:
    return bool(
        should_browser_escalate
        and browser_escalation_allowed(
            context=context,
            runtime_policy=runtime_policy,
        )
    )


def _remaining_browser_timeout_below_retry_floor(
    context: Any,
    *,
    deps: HttpAttemptDependencies,
) -> bool:
    remaining_timeout = deps.remaining_timeout_seconds(context)
    min_browser_budget = max(
        0.0,
        float(crawler_runtime_settings.browser_retry_min_remaining_seconds),
    )
    return remaining_timeout < min_browser_budget


async def _escalate_http_result_to_browser(
    context: Any,
    *,
    result: PageFetchResult,
    proxy: str | None,
    vendor: str | None,
    deps: HttpAttemptDependencies,
) -> PageFetchResult:
    browser_reason = context.browser_reason or (
        f"vendor-block:{vendor}" if vendor else "http-escalation"
    )
    await deps.emit_fetch_event(
        context.on_event,
        "info",
        (
            "Escalating to browser after HTTP result "
            f"(status={result.status_code}, method={result.method}, reason={browser_reason})"
        ),
    )
    browser_result = await deps.run_browser_attempts(
        context,
        reason=browser_reason,
        requested_fields=context.requested_fields,
        listing_recovery_mode=context.listing_recovery_mode,
        capture_screenshot=context.capture_screenshot,
        proxies=browser_escalation_proxies(
            context=context,
            current_proxy=proxy,
            vendor_blocked=bool(vendor),
        ),
    )
    await deps.update_host_result_memory(context, result=browser_result)
    return browser_result


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


def _browser_result_is_ready(result: PageFetchResult) -> bool:
    diagnostics = dict(result.browser_diagnostics or {})
    outcome = str(diagnostics.get("browser_outcome") or "").strip().casefold()
    if result.blocked or outcome != "usable_content":
        return False
    # A usable_content verdict that ships readiness probes none of which are
    # ready means the browser never actually settled on extractable content
    # (e.g. a vendor challenge shell that scored as usable). Mirror the
    # has-ready-probe invariant the acquirer applies so an unresolved vendor
    # block stays blocked. Absent probes, trust the usable_content verdict.
    probes = diagnostics.get("readiness_probes")
    if isinstance(probes, list) and probes:
        return any(
            isinstance(probe, dict) and bool(probe.get("is_ready")) for probe in probes
        )
    return True


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
