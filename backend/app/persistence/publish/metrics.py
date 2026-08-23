from __future__ import annotations

from typing import Any

from app.acquisition.acquirer import PageEvidence


def build_acquisition_profile(settings_view) -> dict[str, object]:
    if hasattr(settings_view, "acquisition_profile"):
        return dict(settings_view.acquisition_profile())
    return {}


def diagnostics_indicate_block(diagnostics: dict[str, object] | object) -> bool:
    return PageEvidence.from_browser_diagnostics(diagnostics).indicates_block


def is_effectively_blocked(acquisition_result) -> bool:
    return PageEvidence.from_acquisition_result(acquisition_result).indicates_block


def _acquisition_attempt_metrics(acquisition_result) -> dict[str, object]:
    diagnostics = getattr(acquisition_result, "acquisition_diagnostics", {})
    if not isinstance(diagnostics, dict):
        return {}
    canonical_result = diagnostics.get("result")
    if not isinstance(canonical_result, dict):
        return {}
    raw_attempts = canonical_result.get("attempts")
    attempts = raw_attempts if isinstance(raw_attempts, list) else []
    summaries: list[dict[str, object]] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        attempt_diagnostics = attempt.get("diagnostics")
        details = attempt_diagnostics if isinstance(attempt_diagnostics, dict) else {}
        summaries.append(
            {
                "attempt_id": attempt.get("attempt_id"),
                "transport": details.get("transport"),
                "method": details.get("method"),
                "outcome": attempt.get("outcome"),
                "status_code": attempt.get("status_code"),
                "proxy": details.get("proxy"),
                "duration_ms": details.get("duration_ms"),
                "error": attempt.get("error"),
            }
        )
    return {
        "acquisition_plan_id": canonical_result.get("plan_id"),
        "acquisition_attempt_count": len(summaries),
        "acquisition_attempts": summaries,
        "acquisition_selected_attempt_id": canonical_result.get("selected_attempt_id"),
        "acquisition_outcome": canonical_result.get("outcome"),
        "acquisition_termination_reason": diagnostics.get("termination_reason"),
    }


def build_url_metrics(
    acquisition_result,
    *,
    requested_fields: list[str] | None = None,
) -> dict[str, object]:
    browser_diagnostics = (
        dict(acquisition_result.browser_diagnostics or {})
        if isinstance(acquisition_result.browser_diagnostics, dict)
        else {}
    )
    return {
        **_acquisition_attempt_metrics(acquisition_result),
        "method": acquisition_result.method,
        "status_code": acquisition_result.status_code,
        "blocked": is_effectively_blocked(acquisition_result),
        "final_url": acquisition_result.final_url,
        "requested_fields": list(requested_fields or []),
        **_browser_metrics(acquisition_result, browser_diagnostics),
        "browser_profile": browser_diagnostics.get("browser_profile"),
        "browser_launch_mode": browser_diagnostics.get("browser_launch_mode"),
        "browser_headless": browser_diagnostics.get("browser_headless"),
        "browser_native_context": browser_diagnostics.get("browser_native_context"),
        "browser_stealth_enabled": browser_diagnostics.get("browser_stealth_enabled"),
        "browser_reason": browser_diagnostics.get("browser_reason"),
        "browser_outcome": browser_diagnostics.get("browser_outcome"),
        "html_bytes": int(browser_diagnostics.get("html_bytes", 0) or 0),
        "network_payloads": len(list(acquisition_result.network_payloads or [])),
        "adapter_name": acquisition_result.adapter_name,
        "platform_family": getattr(acquisition_result, "platform_family", None),
        "failure_reason": browser_diagnostics.get("failure_reason"),
        "browser_navigation_strategy": browser_diagnostics.get("navigation_strategy"),
        "network_payload_count": int(
            browser_diagnostics.get("network_payload_count", 0) or 0
        ),
        "malformed_network_payloads": int(
            browser_diagnostics.get("malformed_network_payloads", 0) or 0
        ),
        **_traversal_metrics(browser_diagnostics),
    }


def _browser_metrics(
    acquisition_result, diagnostics: dict[str, Any]
) -> dict[str, object]:
    browser_engine = (
        str(diagnostics.get("browser_engine") or "").strip().lower() or None
    )
    used = acquisition_result.method == "browser"
    return {
        "browser_fetch_method": f"browser:{browser_engine}"
        if used and browser_engine
        else None,
        "browser_used": used,
        "browser_attempted": bool(diagnostics.get("browser_attempted")) or used,
        "memory_browser_first": str(diagnostics.get("browser_reason") or "")
        .strip()
        .lower()
        in {"host-preference", "acquisition-contract"},
        "browser_engine": browser_engine,
        "browser_phase_timings_ms": (
            dict(diagnostics.get("phase_timings_ms") or {})
            if isinstance(diagnostics.get("phase_timings_ms"), dict)
            else {}
        ),
    }


def _traversal_metrics(diagnostics: dict[str, Any]) -> dict[str, object]:
    requested = str(diagnostics.get("requested_traversal_mode") or "").strip()
    selected = str(diagnostics.get("selected_traversal_mode") or requested).strip()
    activated = bool(diagnostics.get("traversal_activated"))
    progress_events = int(diagnostics.get("traversal_progress_events", 0) or 0)
    pages_advanced = int(diagnostics.get("pages_advanced", 0) or 0)
    pages_collected = _collected_page_count(
        activated=activated,
        selected_mode=selected,
        progress_events=progress_events,
        pages_advanced=pages_advanced,
    )
    return {
        "requested_traversal_mode": requested or None,
        "traversal_mode_used": selected or None,
        "traversal_stop_reason": diagnostics.get("traversal_stop_reason"),
        "traversal_attempted": bool(requested),
        "traversal_succeeded": progress_events > 0,
        "traversal_fell_back": bool(requested) and not activated,
        "traversal_fallback_used": bool(diagnostics.get("traversal_fallback_used")),
        "traversal_fallback_recovered": bool(
            diagnostics.get("traversal_fallback_recovered")
        ),
        "traversal_fallback_record_count": int(
            diagnostics.get("traversal_fallback_record_count", 0) or 0
        ),
        "pages_collected": pages_collected,
        "pages_scrolled": pages_advanced,
        "scroll_iterations": int(diagnostics.get("scroll_iterations", 0) or 0),
        "load_more_clicks": int(diagnostics.get("load_more_clicks", 0) or 0),
        "traversal_iterations": int(diagnostics.get("traversal_iterations", 0) or 0),
    }


def _collected_page_count(
    *, activated: bool, selected_mode: str, progress_events: int, pages_advanced: int
) -> int:
    if not activated:
        return 1
    progress = pages_advanced if selected_mode == "paginate" else progress_events
    return max(1, progress + 1)


def finalize_url_metrics(
    url_metrics: dict[str, object],
    *,
    record_count: int,
) -> dict[str, object]:
    finalized = dict(url_metrics or {})
    finalized["record_count"] = max(0, int(record_count))
    return finalized
