"""Listing-integrity acquisition escalation decision.

Pure decision function that mirrors the contract shape of
``extraction_retry_decision.low_quality_extraction_browser_retry_decision``:
no I/O, no mutation of inputs.

Determines whether a listing-quality retry at a stronger acquisition tier
should be triggered when the Listing_Integrity_Gate flags a candidate set
as ``promo_only_cluster``.
"""

from __future__ import annotations

from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.pipeline.runtime_helpers import effective_blocked


def listing_integrity_escalation_decision(
    acquisition_result,
    *,
    gate_decision,
    surface: str,
    retry_state,
    policy_snapshot,
) -> dict[str, object]:
    """Decide whether to trigger a listing-quality retry at a stronger tier.

    Parameters
    ----------
    acquisition_result:
        The current :class:`AcquisitionResult` (read-only).
    gate_decision:
        The :class:`IntegrityDecision` from the Listing_Integrity_Gate.
    surface:
        The active listing surface (e.g. ``"ecommerce_listing"``).
    retry_state:
        Object exposing ``listing_integrity_retry_count: int``.
    policy_snapshot:
        Immutable snapshot of acquisition policy exposing:
        - ``challenge_state: bool``
        - ``host_hard_block: bool``
        Note: escalation is gated by ``settings.listing_integrity_escalation_enabled``.

    Returns
    -------
    dict with keys:
        should_retry, reason, prior_tier, next_tier, gate_reason, candidate_summary
    """

    settings = crawler_runtime_settings

    # Build candidate_summary from gate_decision metrics (safe defaults).
    gate_metrics = getattr(gate_decision, "metrics", None) or {}
    candidate_summary: dict[str, object] = {
        "record_count": gate_metrics.get("record_count", 0),
        "cohort_homogeneity_ratio": gate_metrics.get("cohort_homogeneity_ratio", 0.0),
        "sibling_category_count": gate_metrics.get("sibling_category_count", 0),
        "support_signal_count": gate_metrics.get("support_signal_count", 0),
    }

    def _skip(reason: str) -> dict[str, object]:
        return {
            "should_retry": False,
            "reason": reason,
            "prior_tier": None,
            "next_tier": None,
            "gate_reason": getattr(gate_decision, "reason", ""),
            "candidate_summary": candidate_summary,
        }

    # --- Skip rules (evaluated in order) ---

    # 1. Surface must be a listing surface.
    surface_lower = str(surface or "").strip().lower()
    if not (
        surface_lower.startswith("ecommerce_listing")
        or surface_lower.startswith("job_listing")
    ):
        return _skip("not_listing_surface")

    # 2. Gate must have flagged promo_only_cluster.
    gate_outcome = getattr(gate_decision, "outcome", "")
    if gate_outcome != "promo_only_cluster":
        return _skip("gate_ok")

    # 3. Already retried the maximum number of times.
    retry_count = getattr(retry_state, "listing_integrity_retry_count", 0)
    max_retries = settings.listing_integrity_escalation_retry_max_per_run
    if retry_count >= max_retries:
        return _skip("already_retried")

    # 4. Acquisition is blocked (prioritize runtime blocks over feature flag
    # so logs/metrics always surface the block reason).
    if effective_blocked(acquisition_result):
        return _skip("blocked")

    # 5. Escalation must be enabled.
    if not settings.listing_integrity_escalation_enabled:
        return _skip("escalation_disabled")

    # 6. Policy-level skip conditions.
    if getattr(policy_snapshot, "challenge_state", False):
        return _skip("challenge_state")

    if getattr(policy_snapshot, "host_hard_block", False):
        return _skip("host_hard_block")

    # 6. Determine current tier and compute next tier.
    method = str(getattr(acquisition_result, "method", "") or "").strip().lower()
    browser_diagnostics = getattr(acquisition_result, "browser_diagnostics", None) or {}
    browser_engine = str(
        browser_diagnostics.get("browser_engine", "") if isinstance(browser_diagnostics, dict) else ""
    ).strip().lower()

    prior_tier = _compute_prior_tier(method, browser_engine)
    next_tier = _compute_next_tier(method, browser_engine)

    if next_tier is None:
        return _skip("no_stronger_tier")

    # --- Trigger retry ---
    return {
        "should_retry": True,
        "reason": "promo_only_cluster",
        "prior_tier": prior_tier,
        "next_tier": next_tier,
        "gate_reason": getattr(gate_decision, "reason", ""),
        "candidate_summary": candidate_summary,
    }


def _compute_prior_tier(method: str, browser_engine: str) -> str:
    """Derive a human-readable tier label from the acquisition method and engine."""
    if method in ("curl_cffi", "httpx"):
        return method
    if method == "browser":
        if browser_engine:
            return f"browser:{browser_engine}"
        return "browser:chromium"
    return method or "unknown"


def _compute_next_tier(method: str, browser_engine: str) -> str | None:
    """Return the next stronger tier, or None if no escalation path exists.

    Tier escalation map:
      curl_cffi / httpx → browser:patchright
      otherwise → None (no_stronger_tier)

    Real Chrome is reserved for blocked-site escalation only; listing
    integrity failures do not warrant real_chrome because the issue is
    extraction quality, not access denial.
    """
    if method in ("curl_cffi", "httpx"):
        return "browser:patchright"

    return None
