"""Small browser-fetch assembly helpers."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.acquisition.browser_background_tasks import register_popup_guard_task
from app.acquisition.browser_diagnostics import (
    CHROMIUM_BROWSER_ENGINE,
    build_browser_diagnostics_contract,
    build_failed_browser_diagnostics,
    normalize_browser_engine,
)
from app.acquisition.browser_page_helpers import dismiss_safe_location_interstitial
from app.acquisition.browser_pool import get_browser_runtime
from app.acquisition.runtime import (
    PageFetchResult,
    copy_headers,
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


# Neutralizes the three ways a page spawns a new tab/window during crawling:
# direct window.open() calls, anchors with target=_blank/_new, and form
# submissions with target=_blank. Runs once per document (sentinel-guarded)
# so init-script + live-document application don't double-bind.
#
# Coverage:
#  * window.open neutralized at script time.
#  * Existing a[target] / form[target] rewritten to _self immediately.
#  * A MutationObserver rewrites future a[target]/form[target] (added nodes
#    and target-attribute mutations) so SPA-injected anchors are also caught.
#  * A capture-phase click listener stays as a final backstop for anything that
#    slips past attribute rewriting (e.g. shadow-DOM anchors).
_NEW_CONTEXT_SUPPRESS_SCRIPT = """(() => {
    if (window.__crawlerNoNewContext) { return; }
    window.__crawlerNoNewContext = true;
    try {
        window.open = function () { return null; };
    } catch (err) { /* read-only window.open: best effort */ }
    const rewriteTarget = (node) => {
        if (!node || node.nodeType !== 1) { return; }
        const tag = node.tagName;
        if ((tag === 'A' || tag === 'FORM') && node.target && node.target !== '_self') {
            try { node.target = '_self'; } catch (err) { /* readonly target */ }
        }
    };
    const rewriteTree = (root) => {
        if (!root) { return; }
        try {
            rewriteTarget(root);
            if (root.querySelectorAll) {
                root.querySelectorAll('a[target], form[target]').forEach(rewriteTarget);
            }
        } catch (err) { /* best effort */ }
    };
    const installObserver = () => {
        if (window.__crawlerNoNewContextObserver) { return; }
        const observerRoot = document.documentElement || document.body;
        if (!observerRoot) { return; }
        try {
            const observer = new MutationObserver((mutations) => {
                for (const mutation of mutations) {
                    if (mutation.type === 'attributes') {
                        rewriteTarget(mutation.target);
                    } else if (mutation.type === 'childList') {
                        mutation.addedNodes.forEach(rewriteTree);
                    }
                }
            });
            observer.observe(observerRoot, {
                subtree: true,
                childList: true,
                attributes: true,
                attributeFilter: ['target'],
            });
            window.__crawlerNoNewContextObserver = observer;
        } catch (err) { /* MutationObserver unavailable: backstop handles it */ }
    };
    try {
        rewriteTree(document);
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                rewriteTree(document);
                installObserver();
            }, { once: true });
        } else {
            installObserver();
        }
    } catch (err) { /* no document yet: init script re-runs per navigation */ }
    try {
        document.addEventListener('click', function (event) {
            let node = event.target;
            while (node && node !== document) {
                if ((node.tagName === 'A' || node.tagName === 'FORM')
                    && node.target && node.target !== '_self') {
                    node.target = '_self';
                    break;
                }
                node = node.parentNode;
            }
        }, true);
    } catch (err) { /* no document yet: init script re-runs per navigation */ }
})()"""


async def suppress_new_context_openers(page: Any) -> None:
    """Stop the page from ever spawning a new tab/window.

    Detail-expansion clicks fragment anchors and toggles; some carry
    target=_blank or invoke window.open, which flash open a new tab the popup
    guard then reaps. Neutralizing window.open and rewriting anchor targets to
    _self at the DOM level prevents the tab from opening at all. Best-effort:
    an init script covers every navigation, and an immediate evaluate covers the
    already-loaded document. The reactive popup guard stays as the backstop for
    anything JS contrives that attribute/open rewriting can't catch.
    """
    add_init_script = getattr(page, "add_init_script", None)
    if callable(add_init_script):
        with suppress(Exception):
            await add_init_script(_NEW_CONTEXT_SUPPRESS_SCRIPT)
    evaluate = getattr(page, "evaluate", None)
    if callable(evaluate):
        with suppress(Exception):
            await evaluate(_NEW_CONTEXT_SUPPRESS_SCRIPT)
