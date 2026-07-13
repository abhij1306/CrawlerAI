from __future__ import annotations

import asyncio
import inspect
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from app.acquisition.browser_capture import (
    BrowserNetworkCapture,
    classify_network_endpoint,
    read_network_payload_body,
    should_capture_network_payload,
)
from app.acquisition.browser_screenshot import capture_browser_screenshot
from app.acquisition.browser_detail import expand_detail_content_if_needed
from app.acquisition.browser_diagnostics import (
    CHROMIUM_BROWSER_ENGINE,
    REAL_CHROME_BROWSER_ENGINE,
    browser_launch_mode,
    browser_profile,
    normalize_browser_engine,
)
from app.acquisition.browser_fetch_support import (
    BrowserFetchRequest,
    BrowserFetchState,
    attach_browser_fetch_exception_context,
    browser_storage_state_is_persistable,
    build_browser_fetch_diagnostics,
    build_browser_fetch_result,
    dismiss_browser_interstitial,
    emit_page_loaded_event,
    install_popup_guard,
    new_browser_fetch_state,
    remove_popup_guard,
    suppress_new_context_openers,
)
from app.acquisition.browser_page_flow import (
    append_readiness_probe,
    navigate_browser_page,
    remaining_timeout_factory,
    resolve_browser_fetch_policy,
    serialize_browser_page_content,
)
from app.acquisition.browser_pool import SharedBrowserRuntime, get_browser_runtime
from app.acquisition.browser_proxy_config import display_proxy
from app.acquisition.browser_readiness import (
    classify_browser_outcome,
    classify_low_content_reason,
    probe_browser_readiness,
    wait_for_listing_readiness,
)
from app.acquisition.browser_recovery import emit_browser_behavior_activity
from app.acquisition.browser_result_builder import (
    BrowserFinalizeInput,
    finalize_browser_fetch,
)
from app.acquisition.browser_route_blocking import block_unneeded_route
from app.acquisition.browser_settle import settle_browser_page
from app.acquisition.browser_stage_runner import run_browser_stage
from app.acquisition.browser_storage_state import mark_storage_state_persist_policy
from app.acquisition.runtime import (
    PageFetchResult,
    classify_blocked_page_async,
)
from app.acquisition.traversal import execute_listing_traversal, should_run_traversal
from app.acquisition.traversal_recovery import recover_listing_page_content
from app.core.config.browser_fingerprint_profiles import (
    BEHAVIOR_REALISM_ELIGIBLE_BROWSER_REASONS,
    WARMUP_VENDOR_BLOCK_PREFIX,
)
from app.core.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PageLifecycleData:
    response: Any
    navigation_strategy: str
    readiness_policy: dict[str, object]
    readiness_probes: list[dict[str, object]]
    networkidle_timed_out: bool
    networkidle_skip_reason: str | None
    readiness_diagnostics: dict[str, object]
    expansion_diagnostics: dict[str, object]
    listing_recovery_diagnostics: dict[str, object]
    interstitial_diagnostics: dict[str, object]
    behavior_diagnostics: dict[str, object]
    html: str
    html_analysis: Any
    traversal_result: Any
    rendered_html: str | None


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _mapping_value(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _callable_accepts_keyword(candidate: Any, keyword: str) -> bool:
    try:
        parameters = inspect.signature(candidate).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or (
            parameter.kind
            in {inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
            and parameter.name == keyword
        )
        for parameter in parameters
    )


async def _resolve_runtime_provider(state: BrowserFetchState):
    request = state.request
    provider = request.runtime_provider
    if request.proxy is not None and _callable_accepts_keyword(provider, "proxy"):
        return await provider(
            proxy=request.proxy,
            browser_engine=state.normalized_engine,
        )
    return await provider(browser_engine=state.normalized_engine)


async def _resolve_page_context(
    state: BrowserFetchState,
) -> tuple[SharedBrowserRuntime | None, Any]:
    request = state.request
    if request.proxy and request.proxied_page_factory is not None:
        context = request.proxied_page_factory(
            proxy=request.proxy,
            run_id=request.run_id,
            domain=state.normalized_domain,
            browser_engine=state.normalized_engine,
            locality_profile=request.locality_profile,
            allow_storage_state=state.allow_storage_state,
        )
        return None, context
    started_at = time.perf_counter()
    runtime = await _resolve_runtime_provider(state)
    state.phase_timings_ms["runtime_lookup_ms"] = _elapsed_ms(started_at)
    return runtime, runtime.page(
        run_id=request.run_id,
        domain=state.normalized_domain,
        locality_profile=request.locality_profile,
        allow_storage_state=state.allow_storage_state,
        phase_timings_ms=state.phase_timings_ms,
    )


async def _emit_browser_event(on_event, level: str, message: str) -> None:
    if on_event is None:
        return
    try:
        await on_event(level, message)
    except Exception:
        logger.debug("Browser event callback failed", exc_info=True)


async def _prepare_launch_context(
    state: BrowserFetchState,
    runtime: SharedBrowserRuntime | None,
) -> None:
    request = state.request
    runtime_engine = (
        str(getattr(runtime, "browser_engine", "") or "").strip().lower()
        if runtime is not None
        else ""
    ) or state.normalized_engine
    state.runtime_engine = runtime_engine
    state.runtime_binary = (
        str(getattr(runtime, "browser_binary", "") or "").strip()
        if runtime is not None
        else ""
    ) or runtime_engine
    bridge_flag = getattr(runtime, "bridge_used", None) if runtime is not None else None
    state.runtime_bridge_used = state.runtime_bridge_used or bool(
        bridge_flag() if callable(bridge_flag) else False
    )
    await _emit_browser_event(
        request.on_event,
        "info",
        (
            f"Launched {browser_launch_mode(runtime_engine)} browser "
            f"({runtime_engine}, profile: {browser_profile(runtime_engine)}, "
            f"proxy: {display_proxy(request.proxy)}, binary: {state.runtime_binary})"
        ),
    )


def _build_payload_capture(surface: str) -> BrowserNetworkCapture:
    return BrowserNetworkCapture(
        surface=surface,
        should_capture_payload=should_capture_network_payload,
        classify_endpoint=classify_network_endpoint,
        read_payload_body=read_network_payload_body,
    )


def _should_run_behavior_realism(state: BrowserFetchState) -> bool:
    if not bool(crawler_runtime_settings.browser_behavior_realism_enabled):
        return False
    if normalize_browser_engine(
        state.runtime_engine
    ) != REAL_CHROME_BROWSER_ENGINE and bool(
        crawler_runtime_settings.browser_behavior_real_chrome_only
    ):
        return False
    reason = str(state.request.browser_reason or "").strip().lower()
    return bool(reason) and (
        reason in BEHAVIOR_REALISM_ELIGIBLE_BROWSER_REASONS
        or reason.startswith(WARMUP_VENDOR_BLOCK_PREFIX)
    )


async def _run_behavior_realism(
    page: Any, state: BrowserFetchState
) -> dict[str, object]:
    if not _should_run_behavior_realism(state):
        return {}
    timeout_seconds = max(
        0.0,
        float(crawler_runtime_settings.browser_behavior_realism_timeout_seconds or 0),
    )
    started_at = time.perf_counter()
    try:
        if timeout_seconds <= 0:
            diagnostics = await emit_browser_behavior_activity(page)
        else:
            diagnostics = await asyncio.wait_for(
                emit_browser_behavior_activity(page),
                timeout=timeout_seconds,
            )
    except asyncio.TimeoutError:
        diagnostics = {
            "enabled": True,
            "timed_out": True,
            "timeout_seconds": timeout_seconds,
        }
    state.phase_timings_ms["behavior_realism"] = _elapsed_ms(started_at)
    return diagnostics


async def _configure_page(
    page: Any,
    state: BrowserFetchState,
) -> tuple[BrowserNetworkCapture, bool, dict[str, object], dict[str, object] | None]:
    request = state.request
    payload_capture = _build_payload_capture(state.normalized_surface)
    payload_capture.attach(page)
    if not request.capture_screenshot:
        with suppress(Exception):
            await page.route("**/*", block_unneeded_route)
    traversal_active, readiness_policy, readiness_override = (
        resolve_browser_fetch_policy(
            url=request.url,
            surface=state.normalized_surface,
            traversal_mode=request.traversal_mode,
            should_run_traversal=should_run_traversal,
        )
    )
    pause_ms = max(0, int(crawler_runtime_settings.browser_first_nav_pause_ms))
    if pause_ms > 0 and state.normalized_surface.startswith("ecommerce_"):
        await page.wait_for_timeout(pause_ms)
    return payload_capture, traversal_active, readiness_policy, readiness_override


async def _run_navigation(
    page: Any,
    state: BrowserFetchState,
    *,
    remaining,
    readiness_policy: dict[str, object],
) -> tuple[Any, str, dict[str, object]]:
    request = state.request
    response, strategy = await run_browser_stage(
        stage="navigation",
        page=page,
        timeout_seconds=min(
            remaining(),
            float(crawler_runtime_settings.browser_render_timeout_seconds),
        ),
        phase_timings_ms=state.phase_timings_ms,
        operation=lambda: navigate_browser_page(
            page,
            url=request.url,
            browser_engine=state.runtime_engine,
            timeout_seconds=remaining(),
            phase_timings_ms=state.phase_timings_ms,
            readiness_policy=readiness_policy,
            crawler_runtime_settings=crawler_runtime_settings,
            elapsed_ms=_elapsed_ms,
        ),
    )
    await emit_page_loaded_event(
        page,
        phase_timings_ms=state.phase_timings_ms,
        on_event=request.on_event,
        emit_browser_event=_emit_browser_event,
    )
    strategy = str(getattr(response, "browser_navigation_strategy", None) or strategy)
    interstitial = await dismiss_browser_interstitial(
        page,
        phase_timings_ms=state.phase_timings_ms,
        on_event=request.on_event,
        emit_browser_event=_emit_browser_event,
        elapsed_ms=_elapsed_ms,
    )
    return response, strategy, interstitial


async def _run_settlement(
    page: Any,
    state: BrowserFetchState,
    *,
    remaining,
    readiness_policy: dict[str, object],
    readiness_override: dict[str, object] | None,
):
    request = state.request
    return await run_browser_stage(
        stage="settle",
        page=page,
        timeout_seconds=remaining(),
        phase_timings_ms=state.phase_timings_ms,
        operation=lambda: settle_browser_page(
            page,
            url=request.url,
            surface=state.normalized_surface,
            requested_fields=request.requested_fields,
            timeout_seconds=remaining(),
            readiness_override=readiness_override,
            readiness_policy=readiness_policy,
            phase_timings_ms=state.phase_timings_ms,
            crawler_runtime_settings=crawler_runtime_settings,
            probe_browser_readiness=probe_browser_readiness,
            wait_for_listing_readiness=wait_for_listing_readiness,
            expand_detail_content_if_needed=expand_detail_content_if_needed,
            append_readiness_probe=append_readiness_probe,
            elapsed_ms=_elapsed_ms,
        ),
    )


async def _run_serialization(
    page: Any,
    state: BrowserFetchState,
    *,
    remaining,
    traversal_active: bool,
    prefetched_html: str,
    prefetched_analysis: Any,
):
    request = state.request
    return await run_browser_stage(
        stage="serialize",
        page=page,
        timeout_seconds=max(
            remaining(),
            float(crawler_runtime_settings.browser_capture_read_timeout_seconds),
        ),
        phase_timings_ms=state.phase_timings_ms,
        operation=lambda: serialize_browser_page_content(
            page,
            surface=state.normalized_surface,
            traversal_mode=request.traversal_mode,
            listing_recovery_mode=request.listing_recovery_mode,
            traversal_active=traversal_active,
            timeout_seconds=remaining(),
            max_pages=request.max_pages,
            max_scrolls=request.max_scrolls,
            max_records=request.max_records,
            prefetched_html=prefetched_html,
            prefetched_analysis=prefetched_analysis,
            phase_timings_ms=state.phase_timings_ms,
            execute_listing_traversal=execute_listing_traversal,
            recover_listing_page_content=recover_listing_page_content,
            elapsed_ms=_elapsed_ms,
            on_event=request.on_event,
        ),
    )


async def _run_finalization(
    page: Any,
    state: BrowserFetchState,
    *,
    remaining,
    payload_capture: BrowserNetworkCapture,
    started_at: float,
    navigation_strategy: str,
    response: Any,
    lifecycle: PageLifecycleData,
):
    request = state.request
    return await run_browser_stage(
        stage="finalize",
        page=page,
        timeout_seconds=max(
            remaining(),
            float(crawler_runtime_settings.browser_capture_read_timeout_seconds),
        ),
        phase_timings_ms=state.phase_timings_ms,
        operation=lambda: finalize_browser_fetch(
            BrowserFinalizeInput(
                page=page,
                url=request.url,
                surface=state.normalized_surface,
                browser_reason=request.browser_reason,
                on_event=request.on_event,
                response=response,
                navigation_strategy=navigation_strategy,
                readiness_probes=lifecycle.readiness_probes,
                networkidle_timed_out=lifecycle.networkidle_timed_out,
                networkidle_skip_reason=lifecycle.networkidle_skip_reason,
                readiness_policy=lifecycle.readiness_policy,
                readiness_diagnostics=lifecycle.readiness_diagnostics,
                expansion_diagnostics=lifecycle.expansion_diagnostics,
                listing_recovery_diagnostics=lifecycle.listing_recovery_diagnostics,
                payload_capture=payload_capture,
                html=lifecycle.html,
                html_analysis=lifecycle.html_analysis,
                traversal_result=lifecycle.traversal_result,
                rendered_html=lifecycle.rendered_html,
                interstitial_diagnostics=lifecycle.interstitial_diagnostics,
                phase_timings_ms=state.phase_timings_ms,
                started_at=started_at,
                capture_screenshot=bool(request.capture_screenshot),
            ),
            classify_blocked_page_async=classify_blocked_page_async,
            classify_low_content_reason=classify_low_content_reason,
            classify_browser_outcome=classify_browser_outcome,
            capture_browser_screenshot=capture_browser_screenshot,
            emit_browser_event=_emit_browser_event,
            elapsed_ms=_elapsed_ms,
        ),
    )


def _build_result(
    page: Any,
    state: BrowserFetchState,
    *,
    lifecycle: PageLifecycleData,
    finalized: dict[str, object],
) -> PageFetchResult:
    request = state.request
    finalized_diagnostics = _mapping_value(finalized.get("diagnostics"))
    diagnostics = build_browser_fetch_diagnostics(
        finalized_diagnostics=finalized_diagnostics,
        runtime_bridge_used=state.runtime_bridge_used,
        browser_proxy_mode=state.browser_proxy_mode,
        escalation_lane=request.escalation_lane,
        host_policy_snapshot=request.host_policy_snapshot,
        resolved_proxy_rotation_mode=state.proxy_rotation,
        allow_storage_state=state.allow_storage_state,
        behavior_diagnostics=lifecycle.behavior_diagnostics,
        browser_reason=request.browser_reason,
        browser_engine=state.runtime_engine,
        browser_binary=state.runtime_binary,
    )
    persist = browser_storage_state_is_persistable(
        blocked=bool(finalized.get("blocked")),
        finalized_diagnostics=finalized_diagnostics,
    )
    mark_storage_state_persist_policy(
        page,
        persist_run_storage_state=state.allow_storage_state and persist,
        persist_domain_storage_state=state.allow_storage_state and persist,
    )
    return build_browser_fetch_result(
        url=request.url,
        final_url=page.url,
        html=lifecycle.html,
        finalized=finalized,
        finalized_status_code=finalized.get("status_code", 0),
        finalized_platform_family=str(finalized.get("platform_family") or "").strip()
        or None,
        diagnostics=diagnostics,
    )


async def _run_page_lifecycle(
    page: Any,
    state: BrowserFetchState,
    *,
    payload_capture: BrowserNetworkCapture,
    traversal_active: bool,
    readiness_policy: dict[str, object],
    readiness_override: dict[str, object] | None,
    remaining,
    started_at: float,
) -> PageFetchResult:
    response, strategy, interstitial = await _run_navigation(
        page,
        state,
        remaining=remaining,
        readiness_policy=readiness_policy,
    )
    behavior = await _run_behavior_realism(page, state)
    settled = await _run_settlement(
        page,
        state,
        remaining=remaining,
        readiness_policy=readiness_policy,
        readiness_override=readiness_override,
    )
    (
        current_probe,
        probes,
        timed_out,
        skip_reason,
        readiness_diag,
        expansion_diag,
        prefetched_html,
        prefetched_analysis,
    ) = settled
    del current_probe
    serialized = await _run_serialization(
        page,
        state,
        remaining=remaining,
        traversal_active=traversal_active,
        prefetched_html=prefetched_html,
        prefetched_analysis=prefetched_analysis,
    )
    html, traversal_result, rendered_html, recovery_diag, html_analysis = serialized
    lifecycle = PageLifecycleData(
        response=response,
        navigation_strategy=strategy,
        readiness_policy=readiness_policy,
        readiness_probes=probes,
        networkidle_timed_out=timed_out,
        networkidle_skip_reason=skip_reason,
        readiness_diagnostics=readiness_diag,
        expansion_diagnostics=expansion_diag,
        listing_recovery_diagnostics=recovery_diag,
        interstitial_diagnostics=interstitial,
        behavior_diagnostics=behavior,
        html=html,
        html_analysis=html_analysis,
        traversal_result=traversal_result,
        rendered_html=rendered_html,
    )
    finalized = await _run_finalization(
        page,
        state,
        remaining=remaining,
        payload_capture=payload_capture,
        started_at=started_at,
        navigation_strategy=strategy,
        response=response,
        lifecycle=lifecycle,
    )
    return _build_result(page, state, lifecycle=lifecycle, finalized=finalized)


async def _execute_browser_fetch(state: BrowserFetchState) -> PageFetchResult:
    request = state.request
    acquired_at = time.perf_counter()
    runtime, page_context = await _resolve_page_context(state)
    async with page_context as page:
        state.phase_timings_ms["page_acquire"] = _elapsed_ms(acquired_at)
        await _prepare_launch_context(state, runtime)
        started_at = time.perf_counter()
        remaining = remaining_timeout_factory(
            started_at + float(request.timeout_seconds)
        )
        payload_capture: BrowserNetworkCapture | None = None
        popup_registrations: list[tuple[Any, str, Any]] = []
        try:
            payload_capture, traversal_active, policy, override = await _configure_page(
                page,
                state,
            )
            popup_registrations = install_popup_guard(
                page,
                on_event=request.on_event,
            )
            await suppress_new_context_openers(page)
            return await _run_page_lifecycle(
                page,
                state,
                payload_capture=payload_capture,
                traversal_active=traversal_active,
                readiness_policy=policy,
                readiness_override=override,
                remaining=remaining,
                started_at=started_at,
            )
        finally:
            remove_popup_guard(popup_registrations)
            if payload_capture is not None:
                await payload_capture.close(page)


async def browser_fetch(
    url: str,
    timeout_seconds: float,
    *,
    run_id: int | None = None,
    proxy: str | None = None,
    browser_engine: str = CHROMIUM_BROWSER_ENGINE,
    browser_reason: str | None = None,
    escalation_lane: str | None = None,
    host_policy_snapshot: dict[str, object] | None = None,
    proxy_profile: dict[str, object] | None = None,
    locality_profile: dict[str, object] | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    requested_fields: list[str] | None = None,
    listing_recovery_mode: str | None = None,
    capture_screenshot: bool = False,
    max_pages: int = 1,
    max_scrolls: int = 1,
    max_records: int | None = None,
    on_event=None,
    runtime_provider=get_browser_runtime,
    proxied_page_factory=None,
) -> PageFetchResult:
    request = BrowserFetchRequest(
        url=url,
        timeout_seconds=timeout_seconds,
        run_id=run_id,
        proxy=proxy,
        browser_engine=browser_engine,
        browser_reason=browser_reason,
        escalation_lane=escalation_lane,
        host_policy_snapshot=host_policy_snapshot,
        proxy_profile=proxy_profile,
        locality_profile=locality_profile,
        surface=surface,
        traversal_mode=traversal_mode,
        requested_fields=requested_fields,
        listing_recovery_mode=listing_recovery_mode,
        capture_screenshot=capture_screenshot,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        max_records=max_records,
        on_event=on_event,
        runtime_provider=runtime_provider,
        proxied_page_factory=proxied_page_factory,
    )
    state = new_browser_fetch_state(request)
    try:
        return await _execute_browser_fetch(state)
    except Exception as exc:
        attach_browser_fetch_exception_context(
            exc,
            browser_proxy_mode=state.browser_proxy_mode,
            phase_timings_ms=state.phase_timings_ms,
            browser_reason=request.browser_reason,
            proxy=request.proxy,
            runtime_engine=state.runtime_engine,
            runtime_binary=state.runtime_binary,
            runtime_bridge_used=state.runtime_bridge_used,
            escalation_lane=request.escalation_lane,
            host_policy_snapshot=request.host_policy_snapshot,
        )
        raise


__all__ = [
    "browser_fetch",
    "browser_storage_state_is_persistable",
]
