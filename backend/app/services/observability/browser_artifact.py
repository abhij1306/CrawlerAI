"""Shape the persisted ``browser.json`` to be honest and lean.

The in-memory ``browser_diagnostics`` dict produced during acquisition stays
unchanged — runtime consumers (contract memory, listing decisions, log lines)
keep reading it as-is. This module only shapes the *saved* artifact:

- drop engine-derivable fields (recomputable from ``browser_engine`` on read)
- drop listing-only diagnostics on non-listing surfaces
- drop empty-list / empty-dict padding for known noise keys
- drop all-zero ``phase_timings_ms`` entries
- replace the pre-fetch ``host_policy_snapshot`` with an honest post-fetch
  ``host_outcome``
- relabel interstitial timing as detection cost when nothing was dismissed

Readers that want the derivable fields back call ``derive_browser_profile_fields``.
"""

from __future__ import annotations

from typing import Any

from app.services.acquisition.browser_diagnostics import (
    browser_profile_diagnostics,
    normalize_browser_engine,
)
from app.services.config import observability as obs_config
from app.services.db_utils import mapping_or_empty


def derive_browser_profile_fields(browser_engine: object) -> dict[str, Any]:
    """Recompute the dropped engine-derivable fields from the engine label."""
    engine = normalize_browser_engine(browser_engine)
    derived = dict(browser_profile_diagnostics(engine))
    derived["browser_engine"] = engine
    derived["browser_binary"] = engine
    return derived


def _is_listing_surface(surface: str | None) -> bool:
    return obs_config.LISTING_SURFACE_KEYWORD in str(surface or "").strip().lower()


def _shape_phase_timings(timings: Any) -> dict[str, Any]:
    """Keep timing entries that carry signal (non-zero, parseable).

    The ``total`` acquire time is always preserved when present and numeric
    (even if zero) because the baseline drift loop reads it as the per-run
    timing observation; dropping it would silently stall timing baselines.
    """
    if not isinstance(timings, dict):
        return {}
    shaped: dict[str, Any] = {}
    for key, value in timings.items():
        key_str = str(key)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            # Non-numeric timing payloads (e.g. an error marker) are signal.
            shaped[key_str] = value
            continue
        if numeric != 0 or key_str == "total":
            shaped[key_str] = value
    return shaped


def _relabel_interstitial_timing(
    timings: dict[str, Any],
    interstitial: Any,
) -> dict[str, Any]:
    """When nothing was dismissed, interstitial time is detection, not dismissal.

    Fixes the dishonest "status: not_found yet interstitial_dismissal: 3873ms".
    """
    dismissal_key = obs_config.INTERSTITIAL_DISMISSAL_TIMING_KEY
    if dismissal_key not in timings:
        return timings
    status = ""
    if isinstance(interstitial, dict):
        status = str(interstitial.get("status") or "").strip().lower()
    if status == "dismissed":
        return timings
    relabeled = dict(timings)
    relabeled[obs_config.INTERSTITIAL_PROBE_TIMING_KEY] = relabeled.pop(dismissal_key)
    return relabeled


def _build_host_outcome(
    diagnostics: dict[str, Any],
    *,
    blocked: bool,
) -> dict[str, Any]:
    """Honest post-fetch host outcome derived from this run's actual result.

    Replaces the pre-fetch ``host_policy_snapshot`` (which described what we knew
    *before* launching and read back misleadingly, e.g. ``patchright_success:
    false`` on a successful run).
    """
    engine = normalize_browser_engine(diagnostics.get("browser_engine"))
    outcome = str(diagnostics.get("browser_outcome") or "").strip().lower()
    succeeded = (not blocked) and outcome in {"usable_content", "ok"}
    host_outcome: dict[str, Any] = {
        "engine": engine,
        "browser_outcome": outcome or None,
        "blocked": bool(blocked),
        "result": "success" if succeeded else ("blocked" if blocked else "incomplete"),
    }
    failure_reason = diagnostics.get("failure_reason")
    if failure_reason:
        host_outcome["failure_reason"] = failure_reason
    escalation_lane = diagnostics.get("escalation_lane")
    if escalation_lane:
        host_outcome["escalation_lane"] = escalation_lane
    return host_outcome


def shape_browser_artifact(
    diagnostics: dict[str, Any],
    *,
    surface: str | None,
    blocked: bool = False,
) -> dict[str, Any]:
    """Return the lean, honest payload to persist as ``<page>.browser.json``."""
    payload = dict(mapping_or_empty(diagnostics))

    # 1. Honest post-fetch host outcome replaces the pre-fetch snapshot.
    payload.pop(obs_config.BROWSER_ARTIFACT_PREFETCH_HOST_KEY, None)
    payload[obs_config.BROWSER_ARTIFACT_HOST_OUTCOME_KEY] = _build_host_outcome(
        payload,
        blocked=blocked,
    )

    # 2. Drop engine-derivable fields (recomputed on read).
    for key in obs_config.BROWSER_ARTIFACT_DERIVABLE_FIELDS:
        payload.pop(key, None)

    # 3. Drop listing-only diagnostics on non-listing surfaces.
    if not _is_listing_surface(surface):
        for key in obs_config.BROWSER_ARTIFACT_LISTING_ONLY_FIELDS:
            payload.pop(key, None)

    # 4. Phase timings: drop all-zero entries; relabel interstitial honestly.
    timings = _shape_phase_timings(payload.get("phase_timings_ms"))
    timings = _relabel_interstitial_timing(timings, payload.get("interstitial"))
    if timings:
        payload["phase_timings_ms"] = timings
    else:
        payload.pop("phase_timings_ms", None)

    # 5. Drop empty-list/empty-dict padding for known noise keys.
    for key in obs_config.BROWSER_ARTIFACT_DROP_WHEN_EMPTY:
        value = payload.get(key)
        if value in ([], {}):
            payload.pop(key, None)

    return payload


__all__ = ["derive_browser_profile_fields", "shape_browser_artifact"]
