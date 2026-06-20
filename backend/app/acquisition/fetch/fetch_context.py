from __future__ import annotations

import asyncio
from functools import partial
import logging
import time
from typing import Any
import httpx

from app.acquisition.browser_runtime import (
    SharedBrowserRuntime,
    build_failed_browser_diagnostics,
    browser_fetch,
    browser_runtime_snapshot,
    get_browser_runtime,
    real_chrome_browser_available,
    shutdown_browser_runtime,
)
from app.acquisition.browser_proxy_config import display_proxy, proxy_scheme
from app.acquisition.host_protection_memory import (
    HostProtectionPolicy,
    load_host_protection_policy,
    note_host_hard_block,
    note_host_usable_fetch,
)
from app.acquisition.cookie_store import (
    clear_cookie_store_cache,
    export_cookie_header_for_domain,
)
from app.acquisition.http_client import (
    close_shared_http_client as close_adapter_shared_http_client,
)
from app.acquisition.pacing import (
    apply_protected_host_backoff,
    reset_pacing_state,
    wait_for_host_slot,
)
from app.acquisition.runtime import (
    PageFetchResult,
    close_shared_http_client,
    curl_fetch,
    get_shared_http_client,
    http_fetch,
    is_blocked_html,
    is_blocked_html_async,
    is_non_retryable_http_status,
    should_escalate_to_browser,
)
from app.acquisition.traversal import should_run_traversal
from app.core.config.runtime_settings import (
    crawler_runtime_settings,
    proxy_rotation_mode,
)
from app.core.config.pipeline_reasons import (
    BROWSER_ESCALATION_SKIPPED_INSUFFICIENT_BUDGET,
)
from app.acquisition.platform_policy import resolve_platform_runtime_policy
from app.acquisition.fetch.browser_policy import (
    browser_engine_attempts as _browser_engine_attempts_impl,
    browser_escalation_allowed as _browser_escalation_allowed,
    browser_escalation_lane as _browser_escalation_lane,
    browser_escalation_proxies as _browser_escalation_proxies,
    browser_first_decision as _browser_first_decision,
    browser_first_reason as _browser_first_reason,
    attach_browser_attempt_diagnostics as _attach_browser_attempt_diagnostics,
    attach_exception_browser_diagnostics as _attach_exception_browser_diagnostics,
    durable_vendor_block_engine_attempts as _durable_vendor_block_engine_attempts,
    extract_vendor_from_reason as _extract_vendor_from_reason,
    hard_browser_requirement as _hard_browser_requirement,
    host_policy_snapshot as _host_policy_snapshot,
    is_vendor_block_reason as _is_vendor_block_reason,
    normalize_fetch_mode as _normalize_fetch_mode,
    normalize_proxy_profile as _normalize_proxy_profile,
    resolve_browser_reason as _resolve_browser_reason,
    resolve_proxy_attempts as _resolve_proxy_attempts,
    vendor_confirmed_block as _vendor_confirmed_block,
)
from app.acquisition.fetch.browser_attempt import browser_fetch_kwargs, browser_fetch_with_wall_clock_timeout
from app.acquisition.fetch.browser_attempt_runner import (
    BrowserAttemptDependencies,
    BrowserAttemptRunner,
)
from app.acquisition.fetch.context_builder import (
    build_fetch_runtime_context as _build_fetch_runtime_context,
)
from app.acquisition.fetch.types import FetchPageCall, FetchRuntimeContext
from app.core.shared.url_utils import ensure_scheme
logger = logging.getLogger(__name__)

_FetchRuntimeContext = FetchRuntimeContext
_FetchPageCall = FetchPageCall

async def _emit_fetch_event(on_event: Any | None, level: str, message: str) -> None:
    if not callable(on_event):
        return
    try:
        await on_event(level, message)
    except Exception:
        logger.debug("Fetch event callback failed", exc_info=True)


def _should_retry_patchright_with_real_chrome(
    *,
    context: "_FetchRuntimeContext",
    exc: Exception,
    browser_engine: str,
    engine_attempts: list[str],
) -> bool:
    if str(context.forced_browser_engine or "").strip():
        return False
    if browser_engine != "patchright":
        return False
    if "real_chrome" in engine_attempts:
        return False
    if not bool(crawler_runtime_settings.browser_real_chrome_enabled):
        return False
    if not real_chrome_browser_available():
        return False
    return "ERR_HTTP2_PROTOCOL_ERROR" in str(exc or "").upper()


async def _get_shared_http_client(*, proxy: str | None = None):
    return await get_shared_http_client(proxy=proxy)


async def _http_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
) -> PageFetchResult:
    return await http_fetch(
        url,
        timeout_seconds,
        proxy=proxy,
        get_client=_get_shared_http_client,
        blocked_html_checker=is_blocked_html_async,
    )


async def _should_escalate_to_browser_async(
    result: PageFetchResult,
    *,
    surface: str | None = None,
    runtime_policy: dict[str, object] | None = None,
) -> bool:
    return await asyncio.to_thread(
        should_escalate_to_browser,
        result,
        surface=surface,
        runtime_policy=runtime_policy,
    )


_curl_fetch = curl_fetch
_browser_fetch = partial(
    browser_fetch,
    runtime_provider=get_browser_runtime,
    proxied_page_factory=None,
    blocked_html_checker=is_blocked_html_async,
)


async def reset_fetch_runtime_state() -> None:
    await shutdown_browser_runtime()
    await clear_cookie_store_cache()
    await reset_pacing_state()
    await close_shared_http_client()
    await close_adapter_shared_http_client()


def _remaining_browser_timeout_seconds(context: _FetchRuntimeContext) -> float:
    return context.deadline_monotonic - time.perf_counter()


def _browser_attempt_timeout_seconds(
    context: _FetchRuntimeContext,
    *,
    reason: str,
    browser_engine: str,
    engine_index: int,
    engine_attempts: list[str],
    host_policy: HostProtectionPolicy | None = None,
) -> float:
    remaining_timeout = _remaining_browser_timeout_seconds(context)
    if (
        browser_engine == "patchright"
        and _is_vendor_block_reason(reason)
        and not str(context.forced_browser_engine or "").strip()
        and _patchright_probe_cap_applies(
            host_policy=host_policy,
            reason=reason,
            engine_attempts=engine_attempts,
        )
    ):
        return min(
            remaining_timeout,
            float(crawler_runtime_settings.browser_vendor_block_probe_timeout_seconds),
        )
    return remaining_timeout


def _patchright_probe_cap_applies(
    *,
    host_policy: HostProtectionPolicy | None,
    reason: str,
    engine_attempts: list[str],
) -> bool:
    expected_vendor = _extract_vendor_from_reason(reason) or ""
    if not expected_vendor:
        return False
    if host_policy is None:
        return False
    if not bool(host_policy.patchright_blocked):
        return False
    if not bool(host_policy.prefer_browser):
        return False
    last_vendor = str(host_policy.last_block_vendor or "").strip().lower()
    return expected_vendor == last_vendor



async def fetch_page(
    url: str,
    *,
    run_id: int | None = None,
    timeout_seconds: float | None = None,
    proxy_list: list[str] | None = None,
    proxy_profile: dict[str, object] | None = None,
    locality_profile: dict[str, object] | None = None,
    fetch_mode: str = "auto",
    prefer_browser: bool = False,
    browser_reason: str | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    requested_fields: list[str] | None = None,
    listing_recovery_mode: str | None = None,
    capture_screenshot: bool = False,
    host_memory_ttl_seconds: int | None = None,
    prefer_curl_handoff: bool = False,
    handoff_cookie_engine: str | None = None,
    forced_browser_engine: str | None = None,
    max_pages: int = 1,
    max_scrolls: int = 1,
    max_records: int | None = None,
    on_event: Any | None = None,
) -> PageFetchResult:
    call = _FetchPageCall(
        url=ensure_scheme(url),
        run_id=run_id,
        timeout_seconds=timeout_seconds,
        proxy_list=proxy_list,
        proxy_profile=proxy_profile,
        locality_profile=locality_profile,
        fetch_mode=fetch_mode,
        prefer_browser=prefer_browser,
        browser_reason=browser_reason,
        surface=surface,
        traversal_mode=traversal_mode,
        requested_fields=requested_fields,
        listing_recovery_mode=listing_recovery_mode,
        capture_screenshot=capture_screenshot,
        host_memory_ttl_seconds=host_memory_ttl_seconds,
        prefer_curl_handoff=prefer_curl_handoff,
        handoff_cookie_engine=handoff_cookie_engine,
        forced_browser_engine=forced_browser_engine,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        max_records=max_records,
        on_event=on_event,
    )
    context = _build_fetch_runtime_context(call)
    context.host_policy = await load_host_protection_policy(
        call.url,
        ttl_seconds=context.host_memory_ttl_seconds,
    )
    host_preference_enabled = bool(context.host_policy.prefer_browser)
    browser_first = _browser_first_decision(
        context=context,
        prefer_browser=call.prefer_browser,
        host_preference_enabled=host_preference_enabled,
    )
    await _emit_fetch_event(
        context.on_event,
        "info",
        _acquisition_strategy_message(
            context=context,
            prefer_browser=call.prefer_browser,
            host_preference_enabled=host_preference_enabled,
            browser_first=browser_first,
        ),
    )
    if browser_first:
        browser_first_result = await _try_browser_first_acquisition(
            context,
            browser_reason=call.browser_reason,
            host_preference_enabled=host_preference_enabled,
        )
        if browser_first_result is not None:
            return browser_first_result

    if context.prefer_curl_handoff:
        handoff_result = await try_browser_http_handoff(context)
        if handoff_result is not None:
            await _update_host_result_memory(
                context,
                result=handoff_result,
            )
            return handoff_result

    http_result, vendor_block_confirmed = await _run_http_fetch_chain(context)
    if http_result is not None:
        return http_result
    if vendor_block_confirmed and context.last_error is not None:
        raise context.last_error
    if context.last_error is not None:
        return await _run_final_browser_fallback(context, browser_reason=call.browser_reason)
    raise RuntimeError(f"Failed to fetch {call.url}")


async def _try_browser_first_acquisition(
    context: _FetchRuntimeContext,
    *,
    browser_reason: str | None,
    host_preference_enabled: bool,
) -> PageFetchResult | None:
    handoff_result = await try_browser_http_handoff(context)
    if handoff_result is not None:
        await _update_host_result_memory(context, result=handoff_result)
        return handoff_result
    resolved_browser_reason = _resolve_browser_reason(
        browser_reason=browser_reason,
        requires_browser=bool(context.runtime_policy.get("requires_browser")),
        traversal_required=context.traversal_required,
        host_preference_enabled=host_preference_enabled,
    )
    try:
        browser_result = await run_browser_attempts(
            context,
            reason=resolved_browser_reason,
            requested_fields=context.requested_fields,
            listing_recovery_mode=context.listing_recovery_mode,
            capture_screenshot=context.capture_screenshot,
            proxies=context.proxies,
        )
        await _update_host_result_memory(context, result=browser_result)
        return browser_result
    except Exception as exc:
        await _record_browser_first_failure(
            context,
            exc=exc,
            resolved_browser_reason=resolved_browser_reason,
        )
        return None


async def _record_browser_first_failure(
    context: _FetchRuntimeContext,
    *,
    exc: Exception,
    resolved_browser_reason: str,
) -> None:
    context.last_error = exc
    context.browser_first_failed = True
    if not context.last_browser_attempt_diagnostics:
        context.last_browser_attempt_diagnostics = build_failed_browser_diagnostics(
            browser_reason=resolved_browser_reason,
            exc=exc,
        )
    _attach_exception_browser_diagnostics(exc, context.last_browser_attempt_diagnostics)
    if context.fetch_mode == "browser_only" or _hard_browser_requirement(context=context):
        raise exc
    await _emit_fetch_event(
        context.on_event,
        "warning",
        (
            "Browser-first acquisition failed; falling back to HTTP "
            f"({type(exc).__name__})"
        ),
    )


async def _run_final_browser_fallback(
    context: _FetchRuntimeContext,
    *,
    browser_reason: str | None,
) -> PageFetchResult:
    cause = context.last_error if isinstance(context.last_error, Exception) else None
    logger.info(
        "HTTP fetchers exhausted for %s (%s); attempting browser fallback",
        context.url,
        type(context.last_error).__name__,
    )
    try:
        return await run_browser_attempts(
            context,
            reason=browser_reason or "http-escalation",
            requested_fields=context.requested_fields,
            listing_recovery_mode=context.listing_recovery_mode,
            capture_screenshot=context.capture_screenshot,
            proxies=context.proxies,
        )
    except Exception as exc:
        _attach_exception_browser_diagnostics(
            exc,
            context.last_browser_attempt_diagnostics,
        )
        raise exc from cause


def _acquisition_strategy_message(
    *,
    context: _FetchRuntimeContext,
    prefer_browser: bool,
    host_preference_enabled: bool,
    browser_first: bool,
) -> str:
    if browser_first:
        return (
            "Acquisition strategy: browser-first "
            f"(reason={_browser_first_reason(context=context, prefer_browser=prefer_browser, host_preference_enabled=host_preference_enabled)}, "
            f"fetch_mode={context.fetch_mode})"
        )
    if not crawler_runtime_settings.force_httpx:
        return (
            "Acquisition strategy: http-first "
            f"(fetch_mode={context.fetch_mode}, timeout={_resolve_http_timeout(context):.1f}s, "
            "curl=primary, httpx_fallback=on_transport_failure)"
        )
    return (
        "Acquisition strategy: http-first "
        f"(fetch_mode={context.fetch_mode}, timeout={_resolve_http_timeout(context):.1f}s, "
        "httpx=primary)"
    )


def _attach_proxy_run_session(proxy_url: str, *, run_id: int | None) -> str:
    from app.acquisition.fetch.browser_policy import attach_proxy_run_session

    return attach_proxy_run_session(proxy_url, run_id=run_id)


def _browser_engine_attempts(
    *,
    context: _FetchRuntimeContext,
    host_policy: HostProtectionPolicy,
) -> list[str]:
    return _browser_engine_attempts_impl(
        context=context,
        host_policy=host_policy,
        real_chrome_available=real_chrome_browser_available(),
    )


def _extend_browser_engine_attempts_after_block(
    *,
    engine_attempts: list[str],
    attempted_engine: str,
    context: _FetchRuntimeContext,
    host_policy: HostProtectionPolicy,
) -> list[str]:
    refreshed_attempts = _browser_engine_attempts(
        context=context,
        host_policy=host_policy,
    )
    appended = list(engine_attempts)
    for engine in refreshed_attempts:
        if engine == attempted_engine or engine in appended:
            continue
        appended.append(engine)
    return appended


async def _run_browser_attempts(
    context: _FetchRuntimeContext,
    *,
    reason: str,
    requested_fields: list[str] | None = None,
    listing_recovery_mode: str | None = None,
    capture_screenshot: bool = False,
    proxies: list[str | None] | None = None,
    host_policy: HostProtectionPolicy | None = None,
) -> PageFetchResult:
    return await BrowserAttemptRunner(
        context=context,
        reason=reason,
        requested_fields=requested_fields,
        listing_recovery_mode=listing_recovery_mode,
        capture_screenshot=capture_screenshot,
        proxies=proxies,
        host_policy=host_policy,
        deps=BrowserAttemptDependencies(
            browser_fetch=_browser_fetch,
            browser_engine_attempts=_browser_engine_attempts,
            extend_engine_attempts_after_block=_extend_browser_engine_attempts_after_block,
            browser_attempt_timeout_seconds=_browser_attempt_timeout_seconds,
            should_retry_patchright_with_real_chrome=_should_retry_patchright_with_real_chrome,
            update_host_result_memory=_update_host_result_memory,
            emit_fetch_event=_emit_fetch_event,
            load_host_protection_policy=load_host_protection_policy,
            note_host_hard_block=note_host_hard_block,
            wait_for_host_slot=wait_for_host_slot,
        ),
    ).run()


run_browser_attempts = _run_browser_attempts


async def _run_http_fetch_chain(
    context: _FetchRuntimeContext,
) -> tuple[PageFetchResult | None, bool]:
    vendor_block_confirmed = False
    primary_fetcher = _select_http_fetcher(context)
    result, vendor_block_confirmed = await _run_http_fetch_chain_with_fetcher(
        context,
        fetcher=primary_fetcher,
    )
    if result is not None or vendor_block_confirmed:
        return result, vendor_block_confirmed
    if (
        primary_fetcher is _curl_fetch
        and not crawler_runtime_settings.force_httpx
        and context.last_error is not None
    ):
        await _emit_fetch_event(
            context.on_event,
            "info",
            (
                "HTTP transport fallback via _http_fetch after curl_fetch failed: "
                f"{type(context.last_error).__name__}"
            ),
        )
        logger.info(
            "curl_cffi transport failed for %s (%s); retrying via httpx",
            context.url,
            type(context.last_error).__name__,
        )
        return await _run_http_fetch_chain_with_fetcher(
            context,
            fetcher=_http_fetch,
        )
    return None, vendor_block_confirmed


async def _run_http_fetch_chain_with_fetcher(
    context: _FetchRuntimeContext,
    *,
    fetcher,
) -> tuple[PageFetchResult | None, bool]:
    vendor_block_confirmed = False
    for proxy in context.proxies:
        result, proxy_vendor_block_confirmed = await _run_http_fetcher_attempts(
            context,
            fetcher=fetcher,
            proxy=proxy,
        )
        vendor_block_confirmed = vendor_block_confirmed or proxy_vendor_block_confirmed
        if result is not None:
            return result, vendor_block_confirmed
    return None, vendor_block_confirmed


async def _try_browser_http_handoff(
    context: _FetchRuntimeContext,
) -> PageFetchResult | None:
    host_policy = context.host_policy
    if host_policy is None:
        return None
    if not bool(crawler_runtime_settings.browser_http_handoff_enabled):
        return None
    if _hard_browser_requirement(context=context):
        return None
    if context.fetch_mode == "browser_only":
        return None
    if context.prefer_browser and not context.prefer_curl_handoff:
        return None
    if not (host_policy.prefer_browser or context.prefer_curl_handoff):
        return None
    engines = _handoff_cookie_engines(
        host_policy,
        preferred_engine=context.handoff_cookie_engine,
    )
    for proxy in context.proxies:
        if proxy is not None:
            continue
        for engine in engines:
            try:
                cookie_header = await export_cookie_header_for_domain(
                    context.url,
                    browser_engine=engine,
                )
            except Exception:
                logger.warning(
                    "Cookie export failed for handoff engine=%s url=%s",
                    engine,
                    context.url,
                    exc_info=True,
                )
                cookie_header = None
            if not cookie_header:
                continue
            handoff_timeout = min(
                float(crawler_runtime_settings.browser_http_handoff_timeout_seconds),
                _resolve_http_timeout(context),
            )
            try:
                result = await _curl_fetch(
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
            if not bool(result.blocked) and not await _should_escalate_to_browser_async(
                result,
                surface=context.surface,
                runtime_policy=resolve_platform_runtime_policy(
                    result.final_url or result.url,
                    result.html,
                    surface=context.surface,
                ),
            ):
                return result
            await apply_protected_host_backoff(
                result.final_url or result.url or context.url,
                ttl_seconds=context.host_memory_ttl_seconds,
            )
            context.last_browser_attempt_diagnostics = dict(result.browser_diagnostics)
            return None
    return None


try_browser_http_handoff = _try_browser_http_handoff


def _handoff_cookie_engines(
    _host_policy: HostProtectionPolicy,
    *,
    preferred_engine: str | None = None,
) -> tuple[str, ...]:
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


def _select_http_fetcher(context: _FetchRuntimeContext):
    del context
    if crawler_runtime_settings.force_httpx:
        return _http_fetch
    return _curl_fetch


def _resolve_http_timeout(context: _FetchRuntimeContext) -> float:
    raw_timeout = crawler_runtime_settings.http_timeout_seconds
    if raw_timeout is None:
        return context.resolved_timeout
    try:
        return min(float(raw_timeout), context.resolved_timeout)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid http_timeout_seconds=%r; using resolved timeout",
            raw_timeout,
        )
        return context.resolved_timeout


async def _run_http_fetcher_attempts(
    context: _FetchRuntimeContext,
    *,
    fetcher,
    proxy: str | None,
) -> tuple[PageFetchResult | None, bool]:
    result = await _attempt_http_fetch(
        context,
        fetcher=fetcher,
        proxy=proxy,
    )
    if not isinstance(result, PageFetchResult):
        return None, False
    handled_result, vendor_block_confirmed = await _handle_http_result(
        context,
        result=result,
        proxy=proxy,
    )
    if isinstance(handled_result, PageFetchResult):
        return handled_result, vendor_block_confirmed
    return None, False


_http_attempt_failed = object()


async def _attempt_http_fetch(
    context: _FetchRuntimeContext,
    *,
    fetcher,
    proxy: str | None,
) -> PageFetchResult | object:
    http_timeout = _resolve_http_timeout(context)
    await _emit_fetch_event(
        context.on_event,
        "info",
        (
            f"HTTP fetch via {fetcher.__name__} "
            f"(timeout={http_timeout:.1f}s, proxy={display_proxy(proxy)})"
        ),
    )
    try:
        await wait_for_host_slot(
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
            proxy or "direct",
            exc_info=True,
        )
        await _emit_fetch_event(
            context.on_event,
            "warning",
            f"HTTP fetch failed via {fetcher.__name__}: {type(exc).__name__}",
        )
        return _http_attempt_failed
    except RuntimeError as exc:
        context.last_error = exc
        logger.debug(
            "Fetch failed for %s via %s (%s)",
            context.url,
            fetcher.__name__,
            proxy or "direct",
            exc_info=True,
        )
        await _emit_fetch_event(
            context.on_event,
            "warning",
            f"HTTP fetch failed via {fetcher.__name__}: {type(exc).__name__}",
        )
        return _http_attempt_failed


async def _handle_http_result(
    context: _FetchRuntimeContext,
    *,
    result: PageFetchResult,
    proxy: str | None,
) -> tuple[PageFetchResult | object | None, bool]:
    vendor = _vendor_confirmed_block(result)
    if vendor or bool(result.blocked):
        await apply_protected_host_backoff(
            result.final_url or result.url or context.url,
            ttl_seconds=context.host_memory_ttl_seconds,
        )
    result_runtime_policy = resolve_platform_runtime_policy(
        result.final_url or result.url,
        result.html,
        surface=context.surface,
    )
    should_browser_escalate = bool(vendor) or await _should_escalate_to_browser_async(
        result,
        surface=context.surface,
        runtime_policy=result_runtime_policy,
    )
    if should_browser_escalate and (vendor or bool(result.blocked)):
        await _record_http_block_memory(context, result=result, proxy=proxy, vendor=vendor)
    if _http_browser_escalation_allowed(
        context,
        should_browser_escalate=should_browser_escalate,
        runtime_policy=result_runtime_policy,
    ):
        if context.browser_first_failed and not (vendor or bool(result.blocked)):
            _attach_browser_attempt_diagnostics(
                result,
                diagnostics=context.last_browser_attempt_diagnostics,
            )
            return result, bool(vendor)
        if _remaining_browser_timeout_below_retry_floor(context):
            result.browser_diagnostics = {
                **dict(result.browser_diagnostics or {}),
                "browser_escalation_skipped": BROWSER_ESCALATION_SKIPPED_INSUFFICIENT_BUDGET,
            }
            return result, bool(vendor)
        return (
            await _escalate_http_result_to_browser(
                context,
                result=result,
                proxy=proxy,
                vendor=vendor,
            ),
            bool(vendor),
        )
    if is_non_retryable_http_status(result.status_code):
        logger.info(
            "Returning non-retryable HTTP status %s for %s without browser fallback",
            result.status_code,
            context.url,
        )
        await _update_host_result_memory(
            context,
            result=result,
        )
        return result, bool(vendor)
    _attach_browser_attempt_diagnostics(
        result,
        diagnostics=context.last_browser_attempt_diagnostics,
    )
    await _update_host_result_memory(
        context,
        result=result,
    )
    return result, bool(vendor)


async def _record_http_block_memory(
    context: _FetchRuntimeContext,
    *,
    result: PageFetchResult,
    proxy: str | None,
    vendor: str | None,
) -> None:
    target_url = result.final_url or result.url or context.url
    await note_host_hard_block(
        target_url,
        method=result.method,
        vendor=vendor,
        status_code=result.status_code,
        proxy_used=proxy is not None,
        ttl_seconds=context.host_memory_ttl_seconds,
    )
    context.host_policy = await load_host_protection_policy(
        target_url,
        ttl_seconds=context.host_memory_ttl_seconds,
    )


def _http_browser_escalation_allowed(
    context: _FetchRuntimeContext,
    *,
    should_browser_escalate: bool,
    runtime_policy: dict[str, object],
) -> bool:
    return bool(
        should_browser_escalate
        and _browser_escalation_allowed(
            context=context,
            runtime_policy=runtime_policy,
        )
    )


def _remaining_browser_timeout_below_retry_floor(context: _FetchRuntimeContext) -> bool:
    remaining_timeout = _remaining_browser_timeout_seconds(context)
    min_browser_budget = max(
        0.0,
        float(crawler_runtime_settings.browser_retry_min_remaining_seconds),
    )
    return remaining_timeout < min_browser_budget


async def _escalate_http_result_to_browser(
    context: _FetchRuntimeContext,
    *,
    result: PageFetchResult,
    proxy: str | None,
    vendor: str | None,
) -> PageFetchResult:
    browser_reason = context.browser_reason or (
        f"vendor-block:{vendor}" if vendor else "http-escalation"
    )
    await _emit_fetch_event(
        context.on_event,
        "info",
        (
            "Escalating to browser after HTTP result "
            f"(status={result.status_code}, method={result.method}, reason={browser_reason})"
        ),
    )
    browser_result = await run_browser_attempts(
        context,
        reason=browser_reason,
        requested_fields=context.requested_fields,
        listing_recovery_mode=context.listing_recovery_mode,
        capture_screenshot=context.capture_screenshot,
        proxies=_browser_escalation_proxies(
            context=context,
            current_proxy=proxy,
            vendor_blocked=bool(vendor),
        ),
    )
    await _update_host_result_memory(context, result=browser_result)
    return browser_result


async def _update_host_result_memory(
    context: _FetchRuntimeContext,
    *,
    result: PageFetchResult,
) -> None:
    target_url = result.final_url or result.url or context.url
    browser_diagnostics = dict(result.browser_diagnostics or {})
    browser_engine = (
        str(browser_diagnostics.get("browser_engine") or "").strip().lower()
    )
    method_label = str(result.method or "").strip().lower()
    if method_label == "browser" and browser_engine:
        method_label = f"browser:{browser_engine}"
    proxy_used = bool(browser_diagnostics.get("proxy_scheme"))
    if bool(result.blocked):
        browser_outcome = (
            str(browser_diagnostics.get("browser_outcome") or "").strip().lower()
        )
        if browser_outcome == "location_required":
            return
        ttl_seconds = context.host_memory_ttl_seconds
        await apply_protected_host_backoff(target_url, ttl_seconds=ttl_seconds)
        await note_host_hard_block(
            target_url,
            method=method_label or result.method,
            vendor=_vendor_confirmed_block(result),
            status_code=result.status_code,
            proxy_used=proxy_used,
            ttl_seconds=ttl_seconds,
        )
        return
    await note_host_usable_fetch(
        target_url,
        method=method_label or result.method,
        proxy_used=proxy_used,
        ttl_seconds=context.host_memory_ttl_seconds,
    )


__all__ = [
    "FetchPageCall",
    "FetchRuntimeContext",
    "PageFetchResult",
    "SharedBrowserRuntime",
    "browser_runtime_snapshot",
    "close_shared_http_client",
    "fetch_page",
    "is_blocked_html",
    "reset_fetch_runtime_state",
    "run_browser_attempts",
    "shutdown_browser_runtime",
    "try_browser_http_handoff",
]
