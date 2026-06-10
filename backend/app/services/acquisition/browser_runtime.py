from __future__ import annotations

import asyncio
import inspect
import logging
import time
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse
from weakref import WeakKeyDictionary

from app.services.acquisition.browser_capture import (
    BrowserNetworkCapture as _BrowserNetworkCapture,
    capture_browser_screenshot,
    classify_network_endpoint,
    read_network_payload_body,
    should_capture_network_payload,
)
from app.services.acquisition.browser_detail import (
    expand_all_interactive_elements,
    expand_interactive_elements_via_accessibility,
    accessibility_expand_candidates,  # noqa: F401  re-exported for callers/tests
    expand_detail_content_if_needed,
    detail_expansion_keywords,
    interactive_candidate_snapshot,
)
from app.services.acquisition.browser_diagnostics import (
    CHROMIUM_BROWSER_ENGINE as _CHROMIUM_BROWSER_ENGINE,
    REAL_CHROME_BROWSER_ENGINE as _REAL_CHROME_BROWSER_ENGINE,
    browser_launch_mode as _browser_launch_mode,
    browser_profile as _browser_profile,
    build_browser_diagnostics_contract,
    build_failed_browser_diagnostics,
    normalize_browser_engine as _normalize_browser_engine,
)
from app.services.acquisition.browser_storage_state import (
    mark_storage_state_persist_policy,
)
from app.services.acquisition.browser_page_flow import (
    append_readiness_probe,
    finalize_browser_fetch,
    navigate_browser_page_impl,
    remaining_timeout_factory,
    resolve_browser_fetch_policy as resolve_browser_fetch_policy_impl,
    serialize_browser_page_content_impl,
    settle_browser_page_impl,
)
from app.services.acquisition.browser_result_builder import BrowserFinalizeInput
from app.services.acquisition.browser_proxy_config import (
    display_proxy as _display_proxy,
)
from app.services.acquisition.browser_fetch_support import (
    attach_browser_fetch_exception_context,
    build_browser_fetch_diagnostics,
    build_browser_fetch_result,
    dismiss_browser_interstitial,
    emit_page_loaded_event,
)
from app.services.acquisition import browser_readiness as _browser_readiness
from app.services.acquisition.browser_readiness import (
    classify_browser_outcome,
    classify_low_content_reason,
    looks_like_low_content_shell,
    probe_browser_readiness,
    wait_for_listing_readiness,
)
from app.services.acquisition.browser_recovery import (
    emit_browser_behavior_activity,
    recover_browser_challenge,
)
from app.services.acquisition.browser_stage_runner import (
    run_browser_stage as _run_browser_stage,
)
from app.services.acquisition.browser_pool import (
    SharedBrowserRuntime,
    block_unneeded_route as _block_unneeded_route,
    browser_runtime_snapshot as _browser_runtime_snapshot_impl,
    get_browser_runtime as _get_browser_runtime_impl,
    patchright_browser_available,
    real_chrome_browser_available,
    real_chrome_candidate_paths as _real_chrome_candidate_paths,
    real_chrome_executable_path,
    register_popup_guard_task,
    shutdown_browser_runtime as _shutdown_browser_runtime_impl,
    shutdown_browser_runtime_sync as _shutdown_browser_runtime_sync_impl,
    temporary_browser_page,
)
from app.services.acquisition import cookie_store
from app.services.acquisition.dom_runtime import get_page_html
from app.services.acquisition.runtime import (
    NetworkPayloadReadResult,
    classify_blocked_page_async,
    PageFetchResult,
    is_blocked_html_async,
)
from app.services.acquisition.traversal import (
    execute_listing_traversal,
    should_run_traversal,
)
from app.services.acquisition.traversal_recovery import recover_listing_page_content
from app.services.config.browser_fingerprint_profiles import (
    BEHAVIOR_REALISM_ELIGIBLE_BROWSER_REASONS,
    WARMUP_ELIGIBLE_BROWSER_REASONS,
    WARMUP_VENDOR_BLOCK_PREFIX,
)
from app.services.config.runtime_settings import (
    # Public compatibility exports for callers that still import these via __all__.
    BROWSER_CAPTURE_MAX_NETWORK_PAYLOAD_BYTES,
    BROWSER_CAPTURE_MAX_NETWORK_PAYLOADS,
    BROWSER_CAPTURE_QUEUE_SIZE,
    BROWSER_CAPTURE_WORKERS,
    crawler_runtime_settings,
    proxy_rotation_mode,
)
from app.services.domain_utils import normalize_domain

logger = logging.getLogger(__name__)


_ORIGIN_WARMUP_STATE_LOCKS: WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Lock
] = WeakKeyDictionary()
_ORIGIN_WARMUP_IN_FLIGHT: set[tuple[str, str, str, str]] = set()
_ORIGIN_WARMUP_RECENT: dict[tuple[str, str, str, str], float] = {}
_ORIGIN_WARMUP_RECENT_MAX_ENTRIES = 512


def _origin_warmup_state_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _ORIGIN_WARMUP_STATE_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _ORIGIN_WARMUP_STATE_LOCKS[loop] = lock
    return lock


get_browser_runtime = _get_browser_runtime_impl
shutdown_browser_runtime = _shutdown_browser_runtime_impl
shutdown_browser_runtime_sync = _shutdown_browser_runtime_sync_impl
browser_runtime_snapshot = _browser_runtime_snapshot_impl


async def listing_card_signal_count(page: Any, *, surface: str) -> int:
    return await _browser_readiness.listing_card_signal_count(page, surface=surface)


block_unneeded_route = _block_unneeded_route
real_chrome_candidate_paths = _real_chrome_candidate_paths


def _should_run_behavior_realism(engine: str, *, browser_reason: str | None) -> bool:
    if not bool(crawler_runtime_settings.browser_behavior_realism_enabled):
        return False
    normalized_engine = _normalize_browser_engine(engine)
    if normalized_engine != _REAL_CHROME_BROWSER_ENGINE and bool(
        crawler_runtime_settings.browser_behavior_real_chrome_only
    ):
        return False
    reason = str(browser_reason or "").strip().lower()
    if not reason:
        return False
    return reason in BEHAVIOR_REALISM_ELIGIBLE_BROWSER_REASONS or reason.startswith(
        WARMUP_VENDOR_BLOCK_PREFIX
    )


async def _emit_browser_behavior_activity_bounded(page: Any) -> dict[str, object]:
    timeout_seconds = max(
        0.0,
        float(crawler_runtime_settings.browser_behavior_realism_timeout_seconds or 0),
    )
    if timeout_seconds <= 0:
        return await emit_browser_behavior_activity(page)
    try:
        return await asyncio.wait_for(
            emit_browser_behavior_activity(page),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        return {
            "enabled": True,
            "timed_out": True,
            "timeout_seconds": timeout_seconds,
        }


def _build_payload_capture(*, surface: str) -> _BrowserNetworkCapture:
    return _BrowserNetworkCapture(
        surface=surface,
        should_capture_payload=should_capture_network_payload,
        classify_endpoint=classify_network_endpoint,
        read_payload_body=read_network_payload_body,
    )


def _normalize_surface(surface: str | None) -> str:
    return str(surface or "").strip().lower()


def _mapping_value(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _proxy_requires_fresh_browser_state(
    proxy_profile: dict[str, object] | None,
) -> bool:
    return proxy_rotation_mode(proxy_profile) == "rotating"


def _surface_supports_origin_warmup(surface: str) -> bool:
    normalized_surface = _normalize_surface(surface)
    return "detail" in normalized_surface


def _browser_proxy_mode(
    *,
    proxy: str | None,
    proxied_page_factory,
) -> str:
    if not proxy:
        return "direct"
    if proxied_page_factory is temporary_browser_page:
        return "launch"
    return "page"


def _browser_storage_state_is_persistable(
    *,
    blocked: bool,
    finalized_diagnostics: dict[str, object] | None,
) -> bool:
    if blocked:
        return False
    diagnostics = dict(finalized_diagnostics or {})
    browser_outcome = str(diagnostics.get("browser_outcome") or "").strip().lower()
    if browser_outcome in {"challenge_page", "low_content_shell", "location_required"}:
        return False
    provider_hits = diagnostics.get("challenge_provider_hits")
    if not isinstance(provider_hits, list) or not provider_hits:
        return True
    readiness_probes = diagnostics.get("readiness_probes")
    if not isinstance(readiness_probes, list):
        return False
    return any(
        isinstance(probe, dict) and bool(probe.get("is_ready"))
        for probe in readiness_probes
    )


async def _resolve_runtime_provider(
    runtime_provider,
    *,
    browser_engine: str,
    proxy: str | None = None,
):
    if proxy is not None and _callable_accepts_keyword(runtime_provider, "proxy"):
        return await runtime_provider(proxy=proxy, browser_engine=browser_engine)
    return await runtime_provider(browser_engine=browser_engine)


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


def _resolve_proxied_page_factory(
    proxied_page_factory,
    *,
    proxy: str,
    run_id: int | None,
    domain: str | None,
    browser_engine: str,
    locality_profile: dict[str, object] | None,
    allow_storage_state: bool,
):
    return proxied_page_factory(
        proxy=proxy,
        run_id=run_id,
        domain=domain,
        browser_engine=browser_engine,
        locality_profile=locality_profile,
        allow_storage_state=allow_storage_state,
    )


async def browser_fetch(
    url: str,
    timeout_seconds: float,
    *,
    run_id: int | None = None,
    proxy: str | None = None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
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
    proxied_page_factory=temporary_browser_page,
    blocked_html_checker=is_blocked_html_async,
) -> PageFetchResult:
    normalized_domain = normalize_domain(url)
    normalized_engine = _normalize_browser_engine(browser_engine)
    resolved_proxy_rotation_mode = proxy_rotation_mode(proxy_profile)
    phase_timings_ms: dict[str, int] = {}
    runtime_engine = normalized_engine
    runtime_binary = normalized_engine
    # Rotating proxies must not reuse cookies/localStorage from a prior IP identity.
    allow_storage_state = not _proxy_requires_fresh_browser_state(proxy_profile)
    browser_proxy_mode = _browser_proxy_mode(
        proxy=proxy,
        proxied_page_factory=proxied_page_factory,
    )
    runtime_bridge_used = browser_proxy_mode == "page"
    skip_origin_warmup = False
    runtime: SharedBrowserRuntime | None = None
    payload_capture = None
    popup_guard_registrations: list[tuple[Any, str, Any]] = []
    try:
        # Time the launch/reuse window (runtime resolve + browser launch + semaphore
        # acquire + context open + storage-state load). This window precedes
        # `started_at` below, so without this probe it is invisible in
        # phase_timings_ms — which is exactly where a slow 2nd-acquisition launch hides.
        page_acquire_started_at = time.perf_counter()
        runtime, page_context = await _resolve_browser_fetch_page_context(
            proxy=proxy,
            proxied_page_factory=proxied_page_factory,
            runtime_provider=runtime_provider,
            normalized_engine=normalized_engine,
            normalized_domain=normalized_domain,
            run_id=run_id,
            locality_profile=locality_profile,
            allow_storage_state=allow_storage_state,
            phase_timings_ms=phase_timings_ms,
        )
        async with page_context as page:
            phase_timings_ms["page_acquire"] = _elapsed_ms(page_acquire_started_at)
            (
                runtime_engine,
                runtime_binary,
                launch_bridge_used,
                skip_origin_warmup,
            ) = await _prepare_browser_fetch_launch_context(
                runtime=runtime,
                normalized_engine=normalized_engine,
                normalized_domain=normalized_domain,
                allow_storage_state=allow_storage_state,
                proxy=proxy,
                resolved_proxy_rotation_mode=resolved_proxy_rotation_mode,
                on_event=on_event,
            )
            runtime_bridge_used = runtime_bridge_used or launch_bridge_used
            started_at = time.perf_counter()
            _remaining = remaining_timeout_factory(started_at + float(timeout_seconds))
            normalized_surface = _normalize_surface(surface)
            try:
                payload_capture = _build_payload_capture(surface=normalized_surface)
                payload_capture.attach(page)
                if not capture_screenshot:
                    # Request filtering is best-effort noise/bandwidth reduction, not an
                    # acquisition gate. A route-install hiccup must not abort the fetch.
                    with suppress(Exception):
                        await page.route("**/*", _block_unneeded_route)
                traversal_active, readiness_policy, readiness_override = (
                    resolve_browser_fetch_policy_impl(
                        url=url,
                        surface=normalized_surface,
                        traversal_mode=traversal_mode,
                        should_run_traversal=should_run_traversal,
                    )
                )
                pre_nav_pause_ms = max(
                    0, int(crawler_runtime_settings.browser_first_nav_pause_ms)
                )
                if pre_nav_pause_ms > 0 and normalized_surface.startswith("ecommerce_"):
                    await page.wait_for_timeout(pre_nav_pause_ms)
                await _maybe_warm_origin_before_navigation(
                    page,
                    url=url,
                    surface=normalized_surface,
                    browser_engine=runtime_engine,
                    browser_reason=browser_reason,
                    host_policy_snapshot=host_policy_snapshot,
                    proxy=proxy,
                    proxy_profile=proxy_profile,
                    skip_for_reusable_domain_state=skip_origin_warmup,
                    timeout_seconds=_remaining(),
                    phase_timings_ms=phase_timings_ms,
                )
                popup_guard_registrations = _install_popup_guard(
                    page, on_event=on_event
                )
                response, navigation_strategy = await _run_browser_stage(
                    stage="navigation",
                    page=page,
                    timeout_seconds=min(
                        _remaining(),
                        float(crawler_runtime_settings.browser_render_timeout_seconds),
                    ),
                    phase_timings_ms=phase_timings_ms,
                    operation=lambda: navigate_browser_page_impl(
                        page,
                        url=url,
                        browser_engine=runtime_engine,
                        timeout_seconds=_remaining(),
                        phase_timings_ms=phase_timings_ms,
                        readiness_policy=readiness_policy,
                        crawler_runtime_settings=crawler_runtime_settings,
                        elapsed_ms=_elapsed_ms,
                    ),
                )
                await emit_page_loaded_event(
                    page,
                    phase_timings_ms=phase_timings_ms,
                    on_event=on_event,
                    emit_browser_event=_emit_browser_event,
                )
                navigation_strategy = str(
                    getattr(response, "browser_navigation_strategy", None)
                    or navigation_strategy
                )
                interstitial_diagnostics = await dismiss_browser_interstitial(
                    page,
                    phase_timings_ms=phase_timings_ms,
                    on_event=on_event,
                    emit_browser_event=_emit_browser_event,
                    elapsed_ms=_elapsed_ms,
                )
                behavior_diagnostics: dict[str, object] = {}
                if _should_run_behavior_realism(
                    runtime_engine,
                    browser_reason=browser_reason,
                ):
                    behavior_started_at = time.perf_counter()
                    behavior_diagnostics = (
                        await _emit_browser_behavior_activity_bounded(page)
                    )
                    phase_timings_ms["behavior_realism"] = _elapsed_ms(
                        behavior_started_at
                    )
                (
                    current_probe,
                    readiness_probes,
                    networkidle_timed_out,
                    networkidle_skip_reason,
                    readiness_diagnostics,
                    expansion_diagnostics,
                    prefetched_html,
                    prefetched_analysis,
                ) = await _run_browser_stage(
                    stage="settle",
                    page=page,
                    timeout_seconds=_remaining(),
                    phase_timings_ms=phase_timings_ms,
                    operation=lambda: _settle_browser_page(
                        page,
                        url=url,
                        surface=normalized_surface,
                        requested_fields=requested_fields,
                        timeout_seconds=_remaining(),
                        readiness_override=readiness_override,
                        readiness_policy=readiness_policy,
                        phase_timings_ms=phase_timings_ms,
                    ),
                )
                (
                    html,
                    traversal_result,
                    rendered_html,
                    listing_recovery_diagnostics,
                ) = await _run_browser_stage(
                    stage="serialize",
                    page=page,
                    timeout_seconds=max(
                        _remaining(),
                        float(
                            crawler_runtime_settings.browser_capture_read_timeout_seconds
                        ),
                    ),
                    phase_timings_ms=phase_timings_ms,
                    operation=lambda: serialize_browser_page_content_impl(
                        page,
                        surface=normalized_surface,
                        traversal_mode=traversal_mode,
                        listing_recovery_mode=listing_recovery_mode,
                        traversal_active=traversal_active,
                        timeout_seconds=_remaining(),
                        max_pages=max_pages,
                        max_scrolls=max_scrolls,
                        max_records=max_records,
                        prefetched_html=prefetched_html,
                        prefetched_analysis=prefetched_analysis,
                        phase_timings_ms=phase_timings_ms,
                        execute_listing_traversal=execute_listing_traversal,
                        recover_listing_page_content=recover_listing_page_content,
                        elapsed_ms=_elapsed_ms,
                        on_event=on_event,
                    ),
                )
                finalized = await _run_browser_stage(
                    stage="finalize",
                    page=page,
                    timeout_seconds=max(
                        _remaining(),
                        float(
                            crawler_runtime_settings.browser_capture_read_timeout_seconds
                        ),
                    ),
                    phase_timings_ms=phase_timings_ms,
                    operation=lambda: finalize_browser_fetch(
                        BrowserFinalizeInput(
                            page=page,
                            url=url,
                            surface=normalized_surface,
                            browser_reason=browser_reason,
                            on_event=on_event,
                            response=response,
                            navigation_strategy=navigation_strategy,
                            readiness_probes=readiness_probes,
                            networkidle_timed_out=networkidle_timed_out,
                            networkidle_skip_reason=networkidle_skip_reason,
                            readiness_policy=readiness_policy,
                            readiness_diagnostics=readiness_diagnostics,
                            expansion_diagnostics=expansion_diagnostics,
                            listing_recovery_diagnostics=listing_recovery_diagnostics,
                            payload_capture=payload_capture,
                            html=html,
                            html_analysis=prefetched_analysis
                            if html == prefetched_html
                            else None,
                            traversal_result=traversal_result,
                            rendered_html=rendered_html,
                            interstitial_diagnostics=interstitial_diagnostics,
                            phase_timings_ms=phase_timings_ms,
                            started_at=started_at,
                            capture_screenshot=bool(capture_screenshot),
                        ),
                        blocked_html_checker=blocked_html_checker,
                        classify_blocked_page_async=classify_blocked_page_async,
                        classify_low_content_reason=classify_low_content_reason,
                        classify_browser_outcome=classify_browser_outcome,
                        capture_browser_screenshot=capture_browser_screenshot,
                        emit_browser_event=_emit_browser_event,
                        elapsed_ms=_elapsed_ms,
                    ),
                )
                finalized_status_code = finalized.get("status_code", 0)
                finalized_platform_family = (
                    str(finalized.get("platform_family") or "").strip() or None
                )
                finalized_diagnostics = _mapping_value(finalized.get("diagnostics"))
                diagnostics = build_browser_fetch_diagnostics(
                    finalized_diagnostics=finalized_diagnostics,
                    runtime_bridge_used=runtime_bridge_used,
                    browser_proxy_mode=browser_proxy_mode,
                    escalation_lane=escalation_lane,
                    host_policy_snapshot=host_policy_snapshot,
                    resolved_proxy_rotation_mode=resolved_proxy_rotation_mode,
                    allow_storage_state=allow_storage_state,
                    behavior_diagnostics=behavior_diagnostics,
                    browser_reason=browser_reason,
                    browser_engine=runtime_engine,
                    browser_binary=runtime_binary,
                )
                persist_storage_state = _browser_storage_state_is_persistable(
                    blocked=bool(finalized.get("blocked")),
                    finalized_diagnostics=finalized_diagnostics,
                )
                mark_storage_state_persist_policy(
                    page,
                    persist_run_storage_state=allow_storage_state
                    and persist_storage_state,
                    persist_domain_storage_state=allow_storage_state
                    and persist_storage_state,
                )
                return build_browser_fetch_result(
                    url=url,
                    final_url=page.url,
                    html=html,
                    finalized=finalized,
                    finalized_status_code=finalized_status_code,
                    finalized_platform_family=finalized_platform_family,
                    diagnostics=diagnostics,
                )
            finally:
                _remove_popup_guard(popup_guard_registrations)
                if payload_capture is not None:
                    await payload_capture.close(page)
    except Exception as exc:
        attach_browser_fetch_exception_context(
            exc,
            browser_proxy_mode=browser_proxy_mode,
            phase_timings_ms=phase_timings_ms,
            browser_reason=browser_reason,
            proxy=proxy,
            runtime_engine=runtime_engine,
            runtime_binary=runtime_binary,
            runtime_bridge_used=runtime_bridge_used,
            escalation_lane=escalation_lane,
            host_policy_snapshot=host_policy_snapshot,
        )
        raise


async def _resolve_browser_fetch_page_context(
    *,
    proxy: str | None,
    proxied_page_factory,
    runtime_provider,
    normalized_engine: str,
    normalized_domain: str | None,
    run_id: int | None,
    locality_profile: dict[str, object] | None,
    allow_storage_state: bool,
    phase_timings_ms: dict[str, int],
):
    if proxy and proxied_page_factory is not temporary_browser_page:
        page_context = _resolve_proxied_page_factory(
            proxied_page_factory,
            proxy=proxy,
            run_id=run_id,
            domain=normalized_domain,
            browser_engine=normalized_engine,
            locality_profile=locality_profile,
            allow_storage_state=allow_storage_state,
        )
        return None, page_context
    runtime_lookup_started_at = time.perf_counter()
    runtime = await _resolve_runtime_provider(
        runtime_provider,
        browser_engine=normalized_engine,
        proxy=proxy,
    )
    phase_timings_ms["runtime_lookup_ms"] = _elapsed_ms(runtime_lookup_started_at)
    return runtime, runtime.page(
        run_id=run_id,
        domain=normalized_domain,
        locality_profile=locality_profile,
        allow_storage_state=allow_storage_state,
        phase_timings_ms=phase_timings_ms,
    )


async def _prepare_browser_fetch_launch_context(
    *,
    runtime: SharedBrowserRuntime | None,
    normalized_engine: str,
    normalized_domain: str | None,
    allow_storage_state: bool,
    proxy: str | None,
    resolved_proxy_rotation_mode: str | None,
    on_event,
) -> tuple[str, str, bool, bool]:
    runtime_engine = (
        str(getattr(runtime, "browser_engine", "") or "").strip().lower()
        if runtime is not None
        else ""
    ) or normalized_engine
    runtime_binary = (
        str(getattr(runtime, "browser_binary", "") or "").strip()
        if runtime is not None
        else ""
    ) or runtime_engine
    bridge_flag = getattr(runtime, "bridge_used", None) if runtime is not None else None
    runtime_bridge_used = bool(bridge_flag()) if callable(bridge_flag) else False
    skip_origin_warmup = False
    if allow_storage_state and normalized_domain:
        # Same-domain repeat hits already load saved domain storage state into the
        # context, so re-running the multi-second origin warmup is redundant. This
        # skip is engine-agnostic: patchright (the default detail engine) gets the
        # same reuse benefit real_chrome already had, instead of paying ~7s warmup
        # on every sequential acquisition in a batch.
        skip_origin_warmup = bool(
            await cookie_store.load_storage_state_for_domain(
                normalized_domain,
                browser_engine=runtime_engine,
            )
        )
    await _emit_browser_event(
        on_event,
        "info",
        (
            f"Launched {_browser_launch_mode(runtime_engine)} browser "
            f"({runtime_engine}, profile: {_browser_profile(runtime_engine)}, "
            f"proxy: {_display_proxy(proxy)}, binary: {runtime_binary})"
        ),
    )
    if resolved_proxy_rotation_mode == "rotating":
        await _emit_browser_event(
            on_event,
            "info",
            "Rotating proxy profile detected; skipping origin warmup",
        )
    return runtime_engine, runtime_binary, runtime_bridge_used, skip_origin_warmup


async def _maybe_warm_origin_before_navigation(
    page: Any,
    *,
    url: str,
    surface: str,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
    browser_reason: str | None,
    host_policy_snapshot: dict[str, object] | None,
    proxy: str | None = None,
    proxy_profile: dict[str, object] | None,
    skip_for_reusable_domain_state: bool = False,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
) -> None:
    normalized_surface = str(surface or "").strip().lower()
    if not _surface_supports_origin_warmup(normalized_surface):
        return
    if _proxy_requires_fresh_browser_state(proxy_profile):
        return
    if skip_for_reusable_domain_state:
        return
    reason = str(browser_reason or "").strip().lower()
    if reason in {
        "detail-shell retry",
        "challenge-shell retry",
        "low-quality-extraction retry",
    }:
        return
    if not (
        reason in WARMUP_ELIGIBLE_BROWSER_REASONS
        or reason.startswith(WARMUP_VENDOR_BLOCK_PREFIX)
    ):
        return
    host_policy = dict(host_policy_snapshot or {})
    if (
        _normalize_browser_engine(browser_engine) != _REAL_CHROME_BROWSER_ENGINE
        and bool(host_policy.get("prefer_browser"))
        and str(host_policy.get("last_block_vendor") or "").strip()
    ):
        return
    warm_pause_ms = max(0, int(crawler_runtime_settings.origin_warm_pause_ms or 0))
    if warm_pause_ms <= 0:
        return
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return
    warm_url = f"{parsed.scheme}://{parsed.netloc}/"
    if warm_url.rstrip("/") == str(url or "").strip().rstrip("/"):
        return
    warmup_key = _origin_warmup_key(
        url=url,
        browser_engine=browser_engine,
        proxy=proxy,
        proxy_profile=proxy_profile,
    )
    should_run_warmup = await _begin_origin_warmup(warmup_key)
    if not should_run_warmup:
        phase_timings_ms["origin_warmup"] = 0
        return
    warm_budget_ratio = max(
        0.0, float(crawler_runtime_settings.origin_warmup_max_budget_ratio)
    )
    warm_budget_ms = min(
        max(750, int(max(0.1, float(timeout_seconds)) * 1000 * warm_budget_ratio)),
        int(crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms),
    )
    if warm_budget_ms < 750:
        await asyncio.shield(_finish_origin_warmup(warmup_key))
        return
    started_at = time.perf_counter()
    use_active_warmup_page = (
        _normalize_browser_engine(browser_engine) == _REAL_CHROME_BROWSER_ENGINE
    )
    open_warmup_page = None
    if not use_active_warmup_page:
        context = getattr(page, "context", None)
        if callable(context):
            with suppress(Exception):
                context = context()
        new_page = getattr(context, "new_page", None)
        if not callable(new_page):
            logger.debug(
                "Skipping origin warmup for %s because page context cannot spawn a sibling page",
                url,
            )
            await asyncio.shield(_finish_origin_warmup(warmup_key))
            return
        open_warmup_page = new_page
    warm_page = None
    warmup_succeeded = False
    try:
        if use_active_warmup_page:
            warm_page = page
        else:
            if not callable(open_warmup_page):
                logger.debug("Skipping origin warmup for %s because no opener is available", url)
                await asyncio.shield(_finish_origin_warmup(warmup_key))
                return
            warm_page = await open_warmup_page()
        warm_response = await warm_page.goto(
            warm_url,
            wait_until="domcontentloaded",
            timeout=warm_budget_ms,
        )
        elapsed_so_far_ms = _elapsed_ms(started_at)
        remaining_budget_ms = max(750, warm_budget_ms - elapsed_so_far_ms)
        warm_phase_timings_ms: dict[str, int] = {}
        # Origin warmup is best-effort and non-fatal (INVARIANTS Rule 6). It runs
        # the bounded challenge wait/retry loop to seed cookies, but a blocked or
        # challenge-shell origin must NOT abort the fetch: the main navigation runs
        # its own challenge loop and owns the blocked verdict for this URL.
        await recover_browser_challenge(
            warm_page,
            url=warm_url,
            response=warm_response,
            browser_engine=browser_engine,
            timeout_seconds=max(1.0, remaining_budget_ms / 1000),
            phase_timings_ms=warm_phase_timings_ms,
            challenge_wait_max_seconds=min(
                max(
                    0.0, float(crawler_runtime_settings.challenge_wait_max_seconds or 0)
                ),
                max(1.0, remaining_budget_ms / 1000),
            ),
            challenge_poll_interval_ms=int(
                crawler_runtime_settings.challenge_poll_interval_ms
            ),
            navigation_timeout_ms=remaining_budget_ms,
            elapsed_ms=_elapsed_ms,
            classify_blocked_page=classify_blocked_page_async,
            get_page_html=get_page_html,
            looks_like_low_content_shell=looks_like_low_content_shell,
        )
        phase_timings_ms["origin_warmup_behavior"] = 0
        remaining_budget_ms = max(0, warm_budget_ms - _elapsed_ms(started_at))
        await warm_page.wait_for_timeout(min(warm_pause_ms, remaining_budget_ms))
        warmup_succeeded = True
        if warm_phase_timings_ms.get("challenge_wait"):
            phase_timings_ms["origin_warmup_challenge_wait"] = int(
                warm_phase_timings_ms["challenge_wait"]
            )
        if warm_phase_timings_ms.get("challenge_retry"):
            phase_timings_ms["origin_warmup_challenge_retry"] = int(
                warm_phase_timings_ms["challenge_retry"]
            )
    except Exception:
        logger.debug("Origin warmup failed for %s", url, exc_info=True)
    finally:
        if warm_page is not None and not use_active_warmup_page:
            close_page = getattr(warm_page, "close", None)
            if callable(close_page):
                with suppress(Exception):
                    await close_page()
        phase_timings_ms["origin_warmup"] = _elapsed_ms(started_at)
        await asyncio.shield(
            _finish_origin_warmup(warmup_key, succeeded=warmup_succeeded)
        )


def _origin_warmup_key(
    *,
    url: str,
    browser_engine: str,
    proxy: str | None,
    proxy_profile: dict[str, object] | None,
) -> tuple[str, str, str, str]:
    parsed = urlparse(url)
    return (
        _normalize_browser_engine(browser_engine),
        str(parsed.scheme or "").lower(),
        str(parsed.netloc or "").lower(),
        str(proxy or proxy_rotation_mode(proxy_profile) or "direct").lower(),
    )


async def _begin_origin_warmup(key: tuple[str, str, str, str]) -> bool:
    now = time.monotonic()
    ttl_seconds = max(
        0.0, float(crawler_runtime_settings.origin_warmup_dedupe_ttl_seconds)
    )
    async with _origin_warmup_state_lock():
        if ttl_seconds > 0:
            stale_keys = [
                recent_key
                for recent_key, completed_at in _ORIGIN_WARMUP_RECENT.items()
                if now - completed_at >= ttl_seconds
            ]
            for stale_key in stale_keys:
                _ORIGIN_WARMUP_RECENT.pop(stale_key, None)
            if len(_ORIGIN_WARMUP_RECENT) > _ORIGIN_WARMUP_RECENT_MAX_ENTRIES:
                keep_count = _ORIGIN_WARMUP_RECENT_MAX_ENTRIES // 2
                excess = len(_ORIGIN_WARMUP_RECENT) - keep_count
                for evict_key in list(_ORIGIN_WARMUP_RECENT.keys())[:excess]:
                    _ORIGIN_WARMUP_RECENT.pop(evict_key, None)
        else:
            _ORIGIN_WARMUP_RECENT.clear()
        if key in _ORIGIN_WARMUP_IN_FLIGHT:
            return False
        completed_at = _ORIGIN_WARMUP_RECENT.get(key)
        if ttl_seconds > 0 and completed_at is not None:
            if now - completed_at < ttl_seconds:
                return False
        _ORIGIN_WARMUP_IN_FLIGHT.add(key)
        return True


async def _finish_origin_warmup(
    key: tuple[str, str, str, str],
    *,
    succeeded: bool = False,
) -> None:
    async with _origin_warmup_state_lock():
        _ORIGIN_WARMUP_IN_FLIGHT.discard(key)
        ttl_seconds = max(
            0.0, float(crawler_runtime_settings.origin_warmup_dedupe_ttl_seconds)
        )
        if succeeded and ttl_seconds > 0:
            _ORIGIN_WARMUP_RECENT[key] = time.monotonic()


async def _settle_browser_page(
    page: Any,
    *,
    url: str,
    surface: str,
    requested_fields: list[str] | None,
    timeout_seconds: float,
    readiness_override: dict[str, object] | None,
    readiness_policy: dict[str, object],
    phase_timings_ms: dict[str, int],
):
    return await settle_browser_page_impl(
        page,
        url=url,
        surface=surface,
        requested_fields=requested_fields,
        timeout_seconds=timeout_seconds,
        readiness_override=readiness_override,
        readiness_policy=readiness_policy,
        phase_timings_ms=phase_timings_ms,
        crawler_runtime_settings=crawler_runtime_settings,
        probe_browser_readiness=probe_browser_readiness,
        wait_for_listing_readiness=wait_for_listing_readiness,
        expand_detail_content_if_needed=expand_detail_content_if_needed,
        append_readiness_probe=append_readiness_probe,
        elapsed_ms=_elapsed_ms,
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


async def _emit_browser_event(on_event, level: str, message: str) -> None:
    if on_event is None:
        return
    try:
        await on_event(level, message)
    except Exception:
        logger.debug("Browser event callback failed", exc_info=True)


def _install_popup_guard(page: Any, *, on_event=None) -> list[tuple[Any, str, Any]]:
    context = getattr(page, "context", None)
    if callable(context):
        with suppress(Exception):
            context = context()
    if context is None:
        return []

    def _handle_context_page(candidate: Any) -> None:
        if candidate is page:
            return
        _schedule_popup_close(candidate, on_event=on_event)

    emitter_on = getattr(context, "on", None)
    if not callable(emitter_on):
        return []
    emitter_on("page", _handle_context_page)
    return [(context, "page", _handle_context_page)]


def _remove_popup_guard(registrations: list[tuple[Any, str, Any]]) -> None:
    for emitter, event_name, callback in registrations:
        remove_listener = getattr(emitter, "remove_listener", None)
        if callable(remove_listener):
            with suppress(Exception):
                remove_listener(event_name, callback)
                continue
        off = getattr(emitter, "off", None)
        if callable(off):
            with suppress(Exception):
                off(event_name, callback)


def _schedule_popup_close(page: Any, *, on_event=None) -> None:
    task = asyncio.create_task(_close_unexpected_popup(page, on_event=on_event))
    register_popup_guard_task(task)


async def _close_unexpected_popup(page: Any, *, on_event=None) -> None:
    popup_url = str(getattr(page, "url", "") or "").strip() or "about:blank"
    close_page = getattr(page, "close", None)
    if not callable(close_page):
        return
    with suppress(Exception):
        await close_page()
        await _emit_browser_event(
            on_event,
            "info",
            f"Closed unexpected popup page: {popup_url}",
        )


__all__ = [
    "SharedBrowserRuntime", "BROWSER_CAPTURE_MAX_NETWORK_PAYLOADS",
    "BROWSER_CAPTURE_MAX_NETWORK_PAYLOAD_BYTES", "BROWSER_CAPTURE_QUEUE_SIZE",
    "BROWSER_CAPTURE_WORKERS", "NetworkPayloadReadResult", "browser_fetch",
    "accessibility_expand_candidates", "build_browser_diagnostics_contract",
    "browser_runtime_snapshot", "block_unneeded_route",
    "build_failed_browser_diagnostics", "capture_browser_screenshot",
    "classify_network_endpoint", "classify_browser_outcome",
    "detail_expansion_keywords", "expand_all_interactive_elements",
    "expand_detail_content_if_needed", "expand_interactive_elements_via_accessibility",
    "interactive_candidate_snapshot", "get_browser_runtime",
    "listing_card_signal_count", "looks_like_low_content_shell",
    "patchright_browser_available", "read_network_payload_body",
    "real_chrome_browser_available", "real_chrome_candidate_paths",
    "real_chrome_executable_path", "should_capture_network_payload",
    "shutdown_browser_runtime", "shutdown_browser_runtime_sync",
    "temporary_browser_page",
]
