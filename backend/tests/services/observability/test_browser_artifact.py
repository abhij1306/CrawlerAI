"""Unit tests for the honest/lean browser.json shaper (Slice 2).

Uses a run-33-style diagnostics payload to assert the contradictions are gone:
no derivable fields, no listing fields on detail surfaces, no all-zero timings,
honest post-fetch host outcome, and correct interstitial cost labeling.
"""

from __future__ import annotations

import pytest

from app.services.observability.browser_artifact import (
    derive_browser_profile_fields,
    shape_browser_artifact,
)

pytestmark = pytest.mark.unit


def _run33_like() -> dict:
    return {
        "browser_attempted": True,
        "browser_binary": "patchright",
        "browser_engine": "patchright",
        "browser_headless": True,
        "browser_launch_mode": "headless",
        "browser_native_context": False,
        "browser_outcome": "usable_content",
        "browser_profile": "patchright_shaped",
        "browser_stealth_enabled": False,
        "behavior_realism": {},
        "challenge_element_hits": [],
        "challenge_evidence": [],
        "challenge_provider_hits": [],
        "navigation_strategy": "domcontentloaded",
        "network_payload_count": 25,
        "failure_reason": None,
        "host_policy_snapshot": {
            "chromium_blocked": False,
            "patchright_blocked": False,
            "patchright_success": False,
            "prefer_browser": False,
        },
        "interstitial": {"location_required": False, "status": "not_found"},
        "listing_readiness": {"reason": "fast_path_ready", "status": "skipped"},
        "listing_recovery": {"actions_taken": [], "status": "skipped"},
        "listing_artifact_capture": {"listing_visual_capture": {"status": "skipped"}},
        "extractable_listing_evidence": {
            "listing_visual_elements": 0,
            "rendered_listing_fragments": 0,
        },
        "rendered_listing_fragment_count": 0,
        "listing_visual_element_count": 0,
        "escalation_lane": "http_escalation",
        "phase_timings_ms": {
            "challenge_retry": 0,
            "challenge_wait": 0,
            "content_serialization": 0,
            "interstitial_dismissal": 3873,
            "navigation": 3060,
            "page_acquire": 1580,
            "payload_capture": 4,
            "readiness_wait": 0,
            "total": 12214,
            "traversal": 0,
        },
    }


def test_derivable_fields_dropped_on_detail():
    shaped = shape_browser_artifact(_run33_like(), surface="ecommerce_detail")
    for key in (
        "browser_headless",
        "browser_launch_mode",
        "browser_profile",
        "browser_native_context",
        "browser_binary",
        "browser_stealth_enabled",
    ):
        assert key not in shaped
    # engine itself is kept (not derivable)
    assert shaped["browser_engine"] == "patchright"


def test_derivable_fields_recomputable_on_read():
    derived = derive_browser_profile_fields("patchright")
    assert derived["browser_profile"] == "patchright_shaped"
    assert derived["browser_launch_mode"] in {"headless", "headful"}
    assert derived["browser_binary"] == "patchright"


def test_listing_fields_dropped_on_detail_surface():
    shaped = shape_browser_artifact(_run33_like(), surface="ecommerce_detail")
    for key in (
        "listing_readiness",
        "listing_recovery",
        "listing_artifact_capture",
        "extractable_listing_evidence",
        "rendered_listing_fragment_count",
        "listing_visual_element_count",
    ):
        assert key not in shaped


def test_listing_fields_kept_on_listing_surface():
    shaped = shape_browser_artifact(_run33_like(), surface="ecommerce_listing")
    assert "listing_readiness" in shaped


def test_all_zero_timings_dropped_nonzero_kept():
    shaped = shape_browser_artifact(_run33_like(), surface="ecommerce_detail")
    timings = shaped["phase_timings_ms"]
    assert "challenge_wait" not in timings
    assert "traversal" not in timings
    assert "readiness_wait" not in timings
    assert timings["navigation"] == 3060
    assert timings["total"] == 12214


def test_interstitial_cost_relabeled_when_not_dismissed():
    shaped = shape_browser_artifact(_run33_like(), surface="ecommerce_detail")
    timings = shaped["phase_timings_ms"]
    # not_found -> the 3873ms is detection (probe), not dismissal
    assert "interstitial_dismissal" not in timings
    assert timings["interstitial_probe"] == 3873


def test_interstitial_dismissal_kept_when_dismissed():
    payload = _run33_like()
    payload["interstitial"] = {"status": "dismissed", "selector": ".btn"}
    shaped = shape_browser_artifact(payload, surface="ecommerce_detail")
    assert shaped["phase_timings_ms"]["interstitial_dismissal"] == 3873
    assert "interstitial_probe" not in shaped["phase_timings_ms"]


def test_prefetch_host_snapshot_replaced_with_honest_outcome():
    shaped = shape_browser_artifact(_run33_like(), surface="ecommerce_detail", blocked=False)
    assert "host_policy_snapshot" not in shaped
    outcome = shaped["host_outcome"]
    # usable_content + not blocked => honest success, no misleading false flags
    assert outcome["result"] == "success"
    assert outcome["engine"] == "patchright"
    assert outcome["blocked"] is False


def test_host_outcome_reports_blocked():
    payload = _run33_like()
    payload["browser_outcome"] = "challenge_page"
    payload["failure_reason"] = "challenge_shell"
    shaped = shape_browser_artifact(payload, surface="ecommerce_detail", blocked=True)
    outcome = shaped["host_outcome"]
    assert outcome["result"] == "blocked"
    assert outcome["blocked"] is True
    assert outcome["failure_reason"] == "challenge_shell"


def test_empty_padding_dropped():
    shaped = shape_browser_artifact(_run33_like(), surface="ecommerce_detail")
    assert "behavior_realism" not in shaped
    assert "challenge_evidence" not in shaped
    assert "challenge_provider_hits" not in shaped
    assert "challenge_element_hits" not in shaped


def test_populated_challenge_evidence_is_kept():
    payload = _run33_like()
    payload["challenge_evidence"] = ["title:access denied"]
    shaped = shape_browser_artifact(payload, surface="ecommerce_detail")
    assert shaped["challenge_evidence"] == ["title:access denied"]
