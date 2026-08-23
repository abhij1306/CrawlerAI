from __future__ import annotations
import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlsplit
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from app.acquisition.browser_readiness import looks_like_low_content_shell
from app.acquisition.browser_page_helpers import (
    normalize_listing_recovery_mode as _normalize_listing_recovery_mode,
    resolve_rendered_snapshot as _resolve_rendered_snapshot,
    select_traversal_snapshot as _select_traversal_snapshot,
)
from app.acquisition.dom_runtime import get_page_html
from app.acquisition.browser_recovery import (
    recover_browser_challenge,
)
from app.acquisition.runtime import classify_blocked_page_async
from app.acquisition.platform_policy import (
    resolve_browser_readiness_policy,
)
from app.core.url_safety import validate_public_target
from app.extraction.documents import HtmlAnalysis

logger = logging.getLogger(__name__)


async def _ensure_public_landed_url(page: Any, response: Any) -> None:
    """SSRF guard for browser navigation: Chromium follows redirect chains
    natively, so the final landed URL is validated (scheme + blocked hosts +
    DNS-resolved public IPs) after goto/challenge recovery and the navigation
    fails with SecurityError when it landed on a non-public target. Literal
    non-public IP hops are additionally aborted mid-chain by the route
    interceptor (browser_route_blocking)."""
    landed_url = str(getattr(response, "url", "") or "") if response is not None else ""
    if not landed_url:
        landed_url = str(getattr(page, "url", "") or "")
    if not landed_url.lower().startswith(("http://", "https://")):
        return
    await validate_public_target(landed_url)


def remaining_timeout_factory(deadline: float):
    return lambda: max(2.0, deadline - time.perf_counter())


def _is_navigation_interrupted_error(exc: Exception) -> bool:
    return "interrupted by another navigation" in str(exc or "").strip().lower()


def _urls_match_for_navigation(expected_url: str, current_url: str) -> bool:
    expected = urlsplit(str(expected_url or "").strip())
    current = urlsplit(str(current_url or "").strip())
    if not expected.scheme or not expected.netloc:
        return False
    return (
        expected.scheme.lower(),
        expected.netloc.lower(),
        expected.path.rstrip("/") or "/",
        expected.query,
    ) == (
        current.scheme.lower(),
        current.netloc.lower(),
        current.path.rstrip("/") or "/",
        current.query,
    )


async def _recover_interrupted_navigation(
    page: Any,
    *,
    url: str,
    wait_until: str,
    timeout_ms: int,
) -> bool:
    if timeout_ms <= 0:
        return False
    recovery_state = "domcontentloaded" if wait_until == "commit" else wait_until
    if recovery_state not in {"load", "domcontentloaded", "networkidle"}:
        recovery_state = "domcontentloaded"
    try:
        await page.wait_for_load_state(recovery_state, timeout=timeout_ms)
    except (asyncio.TimeoutError, PlaywrightTimeoutError, PlaywrightError):
        return False
    return _urls_match_for_navigation(url, str(getattr(page, "url", "") or ""))


async def _goto_with_interrupted_navigation_recovery(
    page: Any,
    *,
    url: str,
    wait_until: str,
    timeout_ms: int,
):
    try:
        return await page.goto(
            url,
            wait_until=wait_until,
            timeout=timeout_ms,
        )
    except PlaywrightError as exc:
        if not _is_navigation_interrupted_error(exc):
            raise
        if not await _recover_interrupted_navigation(
            page,
            url=url,
            wait_until=wait_until,
            timeout_ms=timeout_ms,
        ):
            raise
        logger.debug(
            "Recovered interrupted navigation url=%s wait_until=%s current_url=%s",
            url,
            wait_until,
            getattr(page, "url", ""),
        )
        return None


async def navigate_browser_page(
    page: Any,
    *,
    url: str,
    browser_engine: str | None = None,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
    readiness_policy: dict[str, object] | None,
    crawler_runtime_settings,
    elapsed_ms,
):
    navigation_wait_until = (
        str((readiness_policy or {}).get("navigation_wait_until") or "domcontentloaded")
        .strip()
        .lower()
    )
    total_timeout_ms = int(timeout_seconds * 1000)
    primary_timeout_cap_ms = int(
        crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms
    )
    if navigation_wait_until == "networkidle":
        primary_timeout_cap_ms = min(
            int(crawler_runtime_settings.browser_navigation_networkidle_timeout_ms),
            max(
                1,
                int(
                    total_timeout_ms
                    * float(
                        crawler_runtime_settings.browser_navigation_networkidle_primary_budget_ratio
                    )
                ),
            ),
        )
    goto_timeout_ms = min(total_timeout_ms, primary_timeout_cap_ms)
    fallback_timeout_ms = min(
        total_timeout_ms,
        int(crawler_runtime_settings.browser_navigation_min_final_commit_timeout_ms),
    )
    fallback_strategy = (
        "domcontentloaded" if navigation_wait_until == "networkidle" else "commit"
    )
    fallback_timeout = (
        min(
            total_timeout_ms,
            int(
                crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms
            ),
        )
        if fallback_strategy == "domcontentloaded"
        else fallback_timeout_ms
    )
    attempts = [
        (navigation_wait_until, goto_timeout_ms),
        (fallback_strategy, fallback_timeout),
    ]
    if fallback_strategy != "commit":
        attempts.append(("commit", fallback_timeout_ms))
    navigation_strategy = navigation_wait_until
    navigation_started_at = time.perf_counter()
    response = None
    try:
        for index, (strategy, attempt_timeout_ms) in enumerate(attempts):
            navigation_strategy = strategy
            try:
                response = await _goto_with_interrupted_navigation_recovery(
                    page, url=url, wait_until=strategy, timeout_ms=attempt_timeout_ms
                )
                break
            except Exception as exc:
                if all(
                    (
                        index == 0,
                        not isinstance(exc, (PlaywrightTimeoutError, PlaywrightError)),
                    )
                ):
                    raise
                if index + 1 < len(attempts):
                    continue
                phase_timings_ms["navigation"] = elapsed_ms(navigation_started_at)
                setattr(exc, "browser_phase_timings_ms", dict(phase_timings_ms))
                setattr(exc, "browser_navigation_strategy", navigation_strategy)
                raise
    finally:
        phase_timings_ms["navigation"] = elapsed_ms(navigation_started_at)
    response = await recover_browser_challenge(
        page,
        url=url,
        response=response,
        browser_engine=browser_engine,
        timeout_seconds=timeout_seconds,
        phase_timings_ms=phase_timings_ms,
        challenge_wait_max_seconds=float(
            crawler_runtime_settings.challenge_wait_max_seconds or 0
        ),
        challenge_poll_interval_ms=int(
            crawler_runtime_settings.challenge_poll_interval_ms
        ),
        navigation_timeout_ms=int(
            crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms
        ),
        elapsed_ms=elapsed_ms,
        classify_blocked_page=classify_blocked_page_async,
        get_page_html=get_page_html,
        looks_like_low_content_shell=looks_like_low_content_shell,
    )
    if response is not None:
        recovered_strategy = getattr(response, "browser_navigation_strategy", None)
        if recovered_strategy is not None:
            navigation_strategy = str(recovered_strategy) or navigation_strategy
    await _ensure_public_landed_url(page, response)
    return response, navigation_strategy


async def serialize_browser_page_content(
    page: Any,
    *,
    surface: str | None,
    traversal_mode: str | None,
    listing_recovery_mode: str | None,
    traversal_active: bool,
    timeout_seconds: float,
    max_pages: int,
    max_scrolls: int,
    max_records: int | None = None,
    prefetched_html: str | None = None,
    prefetched_analysis: HtmlAnalysis | None = None,
    phase_timings_ms: dict[str, int],
    execute_listing_traversal,
    recover_listing_page_content,
    elapsed_ms,
    on_event=None,
):
    should_flatten_shadow = "listing" not in str(surface or "").strip().lower()
    traversal_result = None
    traversal_html = ""
    rendered_html = ""
    listing_recovery_diagnostics = {
        "status": "skipped",
        "reason": "not_requested",
        "clicked_count": 0,
        "actions_taken": [],
    }
    recovery_started_at = time.perf_counter()
    normalized_listing_recovery_mode = _normalize_listing_recovery_mode(
        listing_recovery_mode
    )
    if normalized_listing_recovery_mode is not None:
        listing_recovery_diagnostics["requested_mode"] = (
            normalized_listing_recovery_mode
        )
    if traversal_active and normalized_listing_recovery_mode == "thin_listing":
        listing_recovery_diagnostics = await recover_listing_page_content(
            page,
            on_event=on_event,
        )
        listing_recovery_diagnostics["requested_mode"] = (
            normalized_listing_recovery_mode
        )
    elif normalized_listing_recovery_mode is not None:
        listing_recovery_diagnostics["reason"] = (
            "traversal_inactive" if not traversal_active else "unsupported_mode"
        )
    phase_timings_ms["listing_recovery"] = elapsed_ms(recovery_started_at)
    traversal_started_at = time.perf_counter()
    if traversal_active:
        traversal_result = await execute_listing_traversal(
            page,
            surface=str(surface or ""),
            traversal_mode=str(traversal_mode or ""),
            max_pages=max_pages,
            max_scrolls=max_scrolls,
            max_records=max_records,
            timeout_seconds=timeout_seconds,
            on_event=on_event,
        )
        traversal_html = traversal_result.compose_html()
        rendered_html = await get_page_html(
            page,
            flatten_shadow=should_flatten_shadow,
        )
        html, html_analysis = await _select_traversal_snapshot(
            surface=surface,
            traversal_result=traversal_result,
            traversal_html=traversal_html,
            rendered_html=rendered_html,
        )
    else:
        html = ""
        html_analysis = None
    phase_timings_ms["traversal"] = elapsed_ms(traversal_started_at)
    serialization_started_at = time.perf_counter()
    if traversal_result is None:
        html, rendered_html, html_analysis = await _resolve_rendered_snapshot(
            page,
            prefetched_html=prefetched_html,
            prefetched_analysis=prefetched_analysis,
            flatten_shadow=should_flatten_shadow,
        )
    phase_timings_ms["content_serialization"] = elapsed_ms(serialization_started_at)
    return (
        html,
        traversal_result,
        rendered_html,
        listing_recovery_diagnostics,
        html_analysis,
    )


def resolve_browser_fetch_policy(
    *,
    url: str,
    surface: str,
    traversal_mode: str | None,
    should_run_traversal,
) -> tuple[bool, dict[str, object], dict[str, object] | None]:
    traversal_active = should_run_traversal(surface, traversal_mode)
    readiness_policy = resolve_browser_readiness_policy(
        url,
        surface=surface,
        traversal_active=traversal_active,
    )
    readiness_override = readiness_policy.get("listing_override")
    return traversal_active, readiness_policy, readiness_override


def append_readiness_probe(
    readiness_probes: list[dict[str, object]],
    *,
    stage: str,
    probe: dict[str, object],
) -> None:
    readiness_probes.append({"stage": stage, **probe})
