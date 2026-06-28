"""Small browser-fetch assembly helpers."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse
from weakref import WeakKeyDictionary

from app.acquisition.browser_background_tasks import register_popup_guard_task
from app.acquisition.browser_diagnostics import (
    CHROMIUM_BROWSER_ENGINE,
    REAL_CHROME_BROWSER_ENGINE,
    build_browser_diagnostics_contract,
    build_failed_browser_diagnostics,
    normalize_browser_engine,
)
from app.acquisition.browser_page_helpers import dismiss_safe_location_interstitial
from app.acquisition.browser_pool import get_browser_runtime
from app.acquisition.browser_readiness import looks_like_low_content_shell
from app.acquisition.browser_recovery import recover_browser_challenge
from app.acquisition.dom_runtime import get_page_html
from app.acquisition.runtime import (
    PageFetchResult,
    classify_blocked_page_async,
    copy_headers,
)
from app.core.config.browser_fingerprint_profiles import (
    WARMUP_VENDOR_BLOCK_PREFIX,
)
from app.core.config.runtime_settings import (
    crawler_runtime_settings,
    proxy_rotation_mode,
)
from app.core.domain_utils import normalize_domain
from app.core.shared.field_coerce import clean_text
from app.extraction.documents import HtmlDocument

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BrowserFetchRequest:
    url: str
    timeout_seconds: float
    run_id: int | None = None
    proxy: str | None = None
    browser_engine: str = CHROMIUM_BROWSER_ENGINE
    browser_reason: str | None = None
    escalation_lane: str | None = None
    host_policy_snapshot: dict[str, object] | None = None
    proxy_profile: dict[str, object] | None = None
    locality_profile: dict[str, object] | None = None
    surface: str | None = None
    traversal_mode: str | None = None
    requested_fields: list[str] | None = None
    listing_recovery_mode: str | None = None
    capture_screenshot: bool = False
    max_pages: int = 1
    max_scrolls: int = 1
    max_records: int | None = None
    on_event: Any = None
    runtime_provider: Any = get_browser_runtime
    proxied_page_factory: Any = None


@dataclass(slots=True)
class BrowserFetchState:
    request: BrowserFetchRequest
    normalized_domain: str | None
    normalized_engine: str
    normalized_surface: str
    proxy_rotation: str | None
    browser_proxy_mode: str
    allow_storage_state: bool
    phase_timings_ms: dict[str, int] = field(default_factory=dict)
    runtime_engine: str = ""
    runtime_binary: str = ""
    runtime_bridge_used: bool = False
    skip_origin_warmup: bool = False


def new_browser_fetch_state(request: BrowserFetchRequest) -> BrowserFetchState:
    normalized_engine = normalize_browser_engine(request.browser_engine)
    allow_storage_state = proxy_rotation_mode(request.proxy_profile) != "rotating"
    proxy_mode = (
        "direct"
        if not request.proxy
        else "launch"
        if request.proxied_page_factory is None
        else "page"
    )
    return BrowserFetchState(
        request=request,
        normalized_domain=normalize_domain(request.url),
        normalized_engine=normalized_engine,
        normalized_surface=str(request.surface or "").strip().lower(),
        proxy_rotation=proxy_rotation_mode(request.proxy_profile),
        browser_proxy_mode=proxy_mode,
        allow_storage_state=allow_storage_state,
        runtime_engine=normalized_engine,
        runtime_binary=normalized_engine,
        runtime_bridge_used=proxy_mode == "page",
    )


def browser_storage_state_is_persistable(
    *,
    blocked: bool,
    finalized_diagnostics: dict[str, object] | None,
) -> bool:
    if blocked:
        return False
    diagnostics = dict(finalized_diagnostics or {})
    outcome = str(diagnostics.get("browser_outcome") or "").strip().lower()
    if outcome in {"challenge_page", "low_content_shell", "location_required"}:
        return False
    provider_hits = diagnostics.get("challenge_provider_hits")
    if not isinstance(provider_hits, list) or not provider_hits:
        return True
    probes = diagnostics.get("readiness_probes")
    return isinstance(probes, list) and any(
        isinstance(probe, dict) and bool(probe.get("is_ready")) for probe in probes
    )


def browser_page_load_elapsed_ms(phase_timings_ms: Mapping[str, object]) -> int:
    navigation_ms = _timing_ms(phase_timings_ms.get("navigation"))
    challenge_wait_ms = _timing_ms(phase_timings_ms.get("challenge_wait"))
    challenge_retry_ms = _timing_ms(phase_timings_ms.get("challenge_retry"))
    return navigation_ms + challenge_wait_ms + challenge_retry_ms


def _timing_ms(value: object) -> int:
    try:
        return max(0, int(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


async def emit_page_loaded_event(
    page: Any,
    *,
    phase_timings_ms: dict[str, int],
    on_event,
    emit_browser_event: Callable[..., Awaitable[None]],
) -> None:
    page_title = ""
    try:
        page_title = clean_text(await page.title())
    except Exception:
        # Best-effort: page title is cosmetic for the event; ignore failures.
        page_title = ""
    await emit_browser_event(
        on_event,
        "info",
        (
            f"Page loaded in {browser_page_load_elapsed_ms(phase_timings_ms)}ms"
            + (f' - title="{page_title}"' if page_title else "")
        ),
    )


async def dismiss_browser_interstitial(
    page: Any,
    *,
    phase_timings_ms: dict[str, int],
    on_event,
    emit_browser_event: Callable[..., Awaitable[None]],
    elapsed_ms: Callable[[float], int],
) -> dict[str, object]:
    interstitial_started_at = time.perf_counter()
    diagnostics = await dismiss_safe_location_interstitial(page)
    elapsed = elapsed_ms(interstitial_started_at)
    # Label the cost honestly: when nothing was dismissed, the time was spent on
    # detection, not dismissal. Avoids "status: not_found yet
    # interstitial_dismissal: 3873ms" in diagnostics.
    if str(diagnostics.get("status") or "").strip().lower() == "dismissed":
        phase_timings_ms["interstitial_dismissal"] = elapsed
        await emit_browser_event(
            on_event,
            "info",
            f"Dismissed location interstitial via {diagnostics.get('selector')}",
        )
    else:
        phase_timings_ms["interstitial_probe"] = elapsed
    return diagnostics


def build_browser_fetch_result(
    *,
    url: str,
    final_url: str,
    html: str,
    finalized: dict[str, object],
    finalized_status_code: object,
    finalized_platform_family: str | None,
    diagnostics: dict[str, object],
) -> PageFetchResult:
    content_type = finalized.get("content_type")
    raw_html_document = finalized.get("html_document")
    html_document = (
        raw_html_document if isinstance(raw_html_document, HtmlDocument) else None
    )
    return PageFetchResult(
        url=url,
        final_url=final_url,
        html=html,
        status_code=_status_code_or_zero(finalized_status_code),
        method="browser",
        content_type=str(content_type or ""),
        blocked=bool(finalized.get("blocked", False)),
        platform_family=finalized_platform_family,
        headers=copy_headers(finalized.get("page_headers")),
        network_payloads=_network_payload_rows(finalized.get("network_payloads")),
        browser_diagnostics=diagnostics,
        artifacts=_mapping_value(finalized.get("artifacts")),
        html_document=html_document,
    )


def _status_code_or_zero(value: object) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def build_browser_fetch_diagnostics(
    *,
    finalized_diagnostics: dict[str, object],
    runtime_bridge_used: bool,
    browser_proxy_mode: str,
    escalation_lane: str | None,
    host_policy_snapshot: dict[str, object] | None,
    resolved_proxy_rotation_mode: str | None,
    allow_storage_state: bool,
    behavior_diagnostics: dict[str, object],
    browser_reason: str | None,
    browser_engine: str,
    browser_binary: str,
) -> dict[str, object]:
    return build_browser_diagnostics_contract(
        diagnostics={
            **finalized_diagnostics,
            "bridge_used": runtime_bridge_used,
            "browser_proxy_mode": browser_proxy_mode,
            "escalation_lane": str(escalation_lane or "").strip().lower() or None,
            "host_policy_snapshot": dict(host_policy_snapshot or {}),
            "proxy_rotation_mode": resolved_proxy_rotation_mode,
            "browser_state_reuse_allowed": allow_storage_state,
            "behavior_realism": dict(behavior_diagnostics or {}),
        },
        browser_reason=browser_reason,
        browser_outcome=str(finalized_diagnostics.get("browser_outcome") or ""),
        browser_engine=browser_engine,
        browser_binary=browser_binary,
    )


def attach_browser_fetch_exception_context(
    exc: Exception,
    *,
    browser_proxy_mode: str,
    phase_timings_ms: dict[str, int],
    browser_reason: str | None,
    proxy: str | None,
    runtime_engine: str,
    runtime_binary: str,
    runtime_bridge_used: bool,
    escalation_lane: str | None,
    host_policy_snapshot: dict[str, object] | None,
) -> None:
    setattr(exc, "browser_proxy_mode", browser_proxy_mode)
    setattr(exc, "browser_phase_timings_ms", dict(phase_timings_ms or {}))
    setattr(
        exc,
        "browser_diagnostics",
        build_failed_browser_diagnostics(
            browser_reason=browser_reason,
            exc=exc,
            proxy=proxy,
            browser_engine=runtime_engine,
            browser_binary=runtime_binary,
            bridge_used=runtime_bridge_used,
            escalation_lane=escalation_lane,
            host_policy_snapshot=host_policy_snapshot,
        ),
    )


def _mapping_value(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _network_payload_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


async def _emit_popup_event(on_event, level: str, message: str) -> None:
    if on_event is None:
        return
    try:
        await on_event(level, message)
    except Exception:
        logger.debug("Browser event callback failed", exc_info=True)


async def _close_unexpected_popup(page: Any, *, on_event=None) -> None:
    popup_url = str(getattr(page, "url", "") or "").strip() or "about:blank"
    close_page = getattr(page, "close", None)
    if not callable(close_page):
        return
    with suppress(Exception):
        await close_page()
        await _emit_popup_event(
            on_event,
            "info",
            f"Closed unexpected popup page: {popup_url}",
        )


def install_popup_guard(page: Any, *, on_event=None) -> list[tuple[Any, str, Any]]:
    context = getattr(page, "context", None)
    if callable(context):
        with suppress(Exception):
            context = context()
    if context is None:
        return []

    def handle_context_page(candidate: Any) -> None:
        if candidate is page:
            return
        task = asyncio.create_task(
            _close_unexpected_popup(candidate, on_event=on_event)
        )
        register_popup_guard_task(task)

    emitter_on = getattr(context, "on", None)
    if not callable(emitter_on):
        return []
    emitter_on("page", handle_context_page)
    return [(context, "page", handle_context_page)]


def remove_popup_guard(registrations: list[tuple[Any, str, Any]]) -> None:
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


WarmupKey = tuple[str, str, str, str]
_ORIGIN_WARMUP_STATE_LOCKS: WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Lock
] = WeakKeyDictionary()
_ORIGIN_WARMUP_IN_FLIGHT: set[WarmupKey] = set()
_ORIGIN_WARMUP_RECENT: dict[WarmupKey, float] = {}
_ORIGIN_WARMUP_RECENT_MAX_ENTRIES = 512


@dataclass(frozen=True, slots=True)
class _WarmupRequest:
    page: Any
    url: str
    warm_url: str
    browser_engine: str
    warm_pause_ms: int
    phase_timings_ms: dict[str, int]


def origin_warmup_state_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _ORIGIN_WARMUP_STATE_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _ORIGIN_WARMUP_STATE_LOCKS[loop] = lock
    return lock


def _warmup_elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _warmup_key(
    *,
    url: str,
    browser_engine: str,
    proxy: str | None,
    proxy_profile: dict[str, object] | None,
) -> WarmupKey:
    parsed = urlparse(url)
    return (
        normalize_browser_engine(browser_engine),
        str(parsed.scheme or "").lower(),
        str(parsed.netloc or "").lower(),
        str(proxy or proxy_rotation_mode(proxy_profile) or "direct").lower(),
    )


def _prune_recent_warmups(*, now: float, ttl_seconds: float) -> None:
    if ttl_seconds <= 0:
        _ORIGIN_WARMUP_RECENT.clear()
        return
    for key, completed_at in list(_ORIGIN_WARMUP_RECENT.items()):
        if now - completed_at >= ttl_seconds:
            _ORIGIN_WARMUP_RECENT.pop(key, None)
    if len(_ORIGIN_WARMUP_RECENT) <= _ORIGIN_WARMUP_RECENT_MAX_ENTRIES:
        return
    keep_count = _ORIGIN_WARMUP_RECENT_MAX_ENTRIES // 2
    excess = len(_ORIGIN_WARMUP_RECENT) - keep_count
    for key in list(_ORIGIN_WARMUP_RECENT)[:excess]:
        _ORIGIN_WARMUP_RECENT.pop(key, None)


async def _begin_warmup(key: WarmupKey) -> bool:
    now = time.monotonic()
    ttl_seconds = max(
        0.0,
        float(crawler_runtime_settings.origin_warmup_dedupe_ttl_seconds),
    )
    async with origin_warmup_state_lock():
        _prune_recent_warmups(now=now, ttl_seconds=ttl_seconds)
        if key in _ORIGIN_WARMUP_IN_FLIGHT:
            return False
        completed_at = _ORIGIN_WARMUP_RECENT.get(key)
        if ttl_seconds > 0 and completed_at is not None:
            if now - completed_at < ttl_seconds:
                return False
        _ORIGIN_WARMUP_IN_FLIGHT.add(key)
        return True


async def _finish_warmup(key: WarmupKey, *, succeeded: bool = False) -> None:
    async with origin_warmup_state_lock():
        _ORIGIN_WARMUP_IN_FLIGHT.discard(key)
        ttl_seconds = max(
            0.0,
            float(crawler_runtime_settings.origin_warmup_dedupe_ttl_seconds),
        )
        if succeeded and ttl_seconds > 0:
            _ORIGIN_WARMUP_RECENT[key] = time.monotonic()


def _eligible_warmup_url(
    *,
    url: str,
    surface: str,
    browser_engine: str,
    browser_reason: str | None,
    proxy_profile: dict[str, object] | None,
    skip_for_reusable_domain_state: bool,
) -> str | None:
    if "detail" not in str(surface or "").strip().lower():
        return None
    # Real Chrome warms on its single active page, which serializes a second
    # navigation (and challenge fight) onto the critical path before the product
    # URL is even requested. Origin warmup is sibling-page only.
    if normalize_browser_engine(browser_engine) == REAL_CHROME_BROWSER_ENGINE:
        return None
    if proxy_rotation_mode(proxy_profile) == "rotating":
        return None
    if skip_for_reusable_domain_state:
        return None
    reason = str(browser_reason or "").strip().lower()
    # Only warm when a bot wall was actually detected: pre-seeding clearance
    # cookies at the origin root only pays off against vendor challenges.
    if not reason.startswith(WARMUP_VENDOR_BLOCK_PREFIX):
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    warm_url = f"{parsed.scheme}://{parsed.netloc}/"
    if warm_url.rstrip("/") == str(url or "").strip().rstrip("/"):
        return None
    return warm_url


def _warmup_budget_ms(timeout_seconds: float) -> int:
    ratio = max(
        0.0,
        float(crawler_runtime_settings.origin_warmup_max_budget_ratio),
    )
    return min(
        max(750, int(max(0.1, float(timeout_seconds)) * 1000 * ratio)),
        int(crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms),
    )


async def _open_warmup_page(request: _WarmupRequest) -> Any | None:
    context = getattr(request.page, "context", None)
    if callable(context):
        with suppress(Exception):
            context = context()
    new_page = getattr(context, "new_page", None)
    if not callable(new_page):
        logger.debug(
            "Skipping origin warmup for %s because page context cannot spawn a sibling page",
            request.url,
        )
        return None
    return await new_page()


def _copy_challenge_timings(
    target: dict[str, int],
    source: dict[str, int],
) -> None:
    for key in ("challenge_wait", "challenge_retry"):
        value = source.get(key)
        if value:
            target[f"origin_warmup_{key}"] = int(value)


async def _run_warmup(request: _WarmupRequest, *, budget_ms: int) -> bool:
    started_at = time.perf_counter()
    warm_page = None
    succeeded = False
    try:
        warm_page = await _open_warmup_page(request)
        if warm_page is None:
            return False
        response = await warm_page.goto(
            request.warm_url,
            wait_until="domcontentloaded",
            timeout=budget_ms,
        )
        remaining_ms = max(750, budget_ms - _warmup_elapsed_ms(started_at))
        challenge_timings: dict[str, int] = {}
        await recover_browser_challenge(
            warm_page,
            url=request.warm_url,
            response=response,
            browser_engine=request.browser_engine,
            timeout_seconds=max(1.0, remaining_ms / 1000),
            phase_timings_ms=challenge_timings,
            challenge_wait_max_seconds=min(
                max(
                    0.0,
                    float(crawler_runtime_settings.challenge_wait_max_seconds or 0),
                ),
                max(1.0, remaining_ms / 1000),
            ),
            challenge_poll_interval_ms=int(
                crawler_runtime_settings.challenge_poll_interval_ms
            ),
            navigation_timeout_ms=remaining_ms,
            elapsed_ms=_warmup_elapsed_ms,
            classify_blocked_page=classify_blocked_page_async,
            get_page_html=get_page_html,
            looks_like_low_content_shell=looks_like_low_content_shell,
        )
        request.phase_timings_ms["origin_warmup_behavior"] = 0
        remaining_ms = max(0, budget_ms - _warmup_elapsed_ms(started_at))
        await warm_page.wait_for_timeout(min(request.warm_pause_ms, remaining_ms))
        _copy_challenge_timings(request.phase_timings_ms, challenge_timings)
        succeeded = True
    except Exception:
        logger.debug("Origin warmup failed for %s", request.url, exc_info=True)
    finally:
        if warm_page is not None:
            close_page = getattr(warm_page, "close", None)
            if callable(close_page):
                with suppress(Exception):
                    await close_page()
        request.phase_timings_ms["origin_warmup"] = _warmup_elapsed_ms(started_at)
    return succeeded


async def maybe_warm_origin_before_navigation(
    page: Any,
    *,
    url: str,
    surface: str,
    browser_engine: str = CHROMIUM_BROWSER_ENGINE,
    browser_reason: str | None,
    proxy: str | None = None,
    proxy_profile: dict[str, object] | None,
    skip_for_reusable_domain_state: bool = False,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
) -> None:
    warm_pause_ms = max(
        0,
        int(crawler_runtime_settings.origin_warm_pause_ms or 0),
    )
    if warm_pause_ms <= 0:
        return
    # Never let warmup consume the product navigation's budget: only warm when
    # there is enough headroom for the real navigation to keep a full
    # domcontentloaded window after the warmup spends its share.
    nav_floor_ms = int(
        crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms
    )
    if int(max(0.0, timeout_seconds) * 1000) <= nav_floor_ms:
        return
    warm_url = _eligible_warmup_url(
        url=url,
        surface=surface,
        browser_engine=browser_engine,
        browser_reason=browser_reason,
        proxy_profile=proxy_profile,
        skip_for_reusable_domain_state=skip_for_reusable_domain_state,
    )
    if warm_url is None:
        return
    key = _warmup_key(
        url=url,
        browser_engine=browser_engine,
        proxy=proxy,
        proxy_profile=proxy_profile,
    )
    if not await _begin_warmup(key):
        phase_timings_ms["origin_warmup"] = 0
        return
    budget_ms = _warmup_budget_ms(timeout_seconds)
    succeeded = False
    try:
        if budget_ms >= 750:
            succeeded = await _run_warmup(
                _WarmupRequest(
                    page=page,
                    url=url,
                    warm_url=warm_url,
                    browser_engine=browser_engine,
                    warm_pause_ms=warm_pause_ms,
                    phase_timings_ms=phase_timings_ms,
                ),
                budget_ms=budget_ms,
            )
    finally:
        await asyncio.shield(_finish_warmup(key, succeeded=succeeded))
