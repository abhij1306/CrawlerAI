"""Small browser-fetch assembly helpers."""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from app.services.acquisition.browser_diagnostics import (
    build_browser_diagnostics_contract,
    build_failed_browser_diagnostics,
)
from app.services.acquisition.browser_page_helpers import dismiss_safe_location_interstitial
from app.services.acquisition.runtime import PageFetchResult, copy_headers
from app.services.shared.field_coerce import clean_text


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
        pass
    await emit_browser_event(
        on_event,
        "info",
        (
            f"Page loaded in {phase_timings_ms.get('navigation', 0)}ms"
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
