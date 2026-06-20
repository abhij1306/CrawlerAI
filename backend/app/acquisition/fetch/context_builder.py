from __future__ import annotations

import time

from app.acquisition.fetch.browser_policy import (
    normalize_fetch_mode,
    normalize_proxy_profile,
    resolve_proxy_attempts,
)
from app.acquisition.fetch.types import FetchPageCall, FetchRuntimeContext
from app.acquisition.platform_policy import resolve_platform_runtime_policy
from app.acquisition.traversal import should_run_traversal
from app.core.config.runtime_settings import crawler_runtime_settings


def build_fetch_runtime_context(call: FetchPageCall) -> FetchRuntimeContext:
    resolved_timeout_source = call.timeout_seconds
    if resolved_timeout_source is None:
        resolved_timeout_source = (
            crawler_runtime_settings.acquisition_attempt_timeout_seconds
        )
    if resolved_timeout_source is None:
        raise ValueError(
            "fetch_page requires timeout_seconds or "
            "crawler_runtime_settings.acquisition_attempt_timeout_seconds"
        )
    return FetchRuntimeContext(
        url=call.url,
        resolved_timeout=float(resolved_timeout_source),
        deadline_monotonic=time.perf_counter() + float(resolved_timeout_source),
        run_id=call.run_id,
        surface=call.surface,
        traversal_mode=call.traversal_mode,
        max_pages=call.max_pages,
        max_scrolls=call.max_scrolls,
        max_records=call.max_records,
        on_event=call.on_event,
        browser_reason=call.browser_reason,
        requested_fields=list(call.requested_fields or []),
        listing_recovery_mode=str(call.listing_recovery_mode or "").strip() or None,
        capture_screenshot=bool(call.capture_screenshot),
        host_memory_ttl_seconds=crawler_runtime_settings.coerce_host_memory_ttl_seconds(
            call.host_memory_ttl_seconds
        ),
        prefer_browser=bool(call.prefer_browser),
        prefer_curl_handoff=bool(call.prefer_curl_handoff),
        handoff_cookie_engine=str(call.handoff_cookie_engine or "").strip().lower()
        or None,
        proxies=resolve_proxy_attempts(
            call.proxy_list,
            run_id=call.run_id,
            proxy_profile=call.proxy_profile,
        ),
        proxy_profile=normalize_proxy_profile(call.proxy_profile),
        locality_profile=dict(call.locality_profile or {})
        if isinstance(call.locality_profile, dict)
        else {},
        traversal_required=should_run_traversal(call.surface, call.traversal_mode),
        fetch_mode=normalize_fetch_mode(call.fetch_mode),
        runtime_policy=resolve_platform_runtime_policy(call.url, surface=call.surface),
        forced_browser_engine=str(call.forced_browser_engine or "").strip().lower()
        or None,
    )
