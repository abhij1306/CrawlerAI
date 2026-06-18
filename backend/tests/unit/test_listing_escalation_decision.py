"""Unit tests for listing_integrity_escalation_decision.

Covers all skip reasons and the happy-path retry trigger:
- not_listing_surface
- gate_ok
- already_retried
- blocked
- challenge_state
- escalation_disabled
- host_hard_block
- no_stronger_tier
- Happy path: promo_only_cluster triggers retry with correct tier computation
"""

from __future__ import annotations

import pytest

from dataclasses import dataclass
from unittest.mock import patch

from app.services.pipeline.listing_escalation_decision import (
    listing_integrity_escalation_decision,
)


@dataclass
class _FakeGateDecision:
    outcome: str = "promo_only_cluster"
    reason: str = "cohort_heterogeneous"
    metrics: dict | None = None

    def __post_init__(self):
        if self.metrics is None:
            self.metrics = {"record_count": 5, "cohort_homogeneity_ratio": 0.3, "sibling_category_count": 0, "support_signal_count": 2}


@dataclass
class _FakeRetryState:
    listing_integrity_retry_count: int = 0


@dataclass
class _FakePolicySnapshot:
    challenge_state: bool = False
    escalation_disabled: bool = False
    host_hard_block: bool = False


@dataclass
class _FakeAcquisitionResult:
    method: str = "curl_cffi"
    blocked: bool = False
    browser_diagnostics: dict | None = None

    def __post_init__(self):
        if self.browser_diagnostics is None:
            self.browser_diagnostics = {}


def _call(
    *,
    surface: str = "ecommerce_listing",
    gate_outcome: str = "promo_only_cluster",
    gate_reason: str = "cohort_heterogeneous",
    method: str = "curl_cffi",
    browser_engine: str = "",
    blocked: bool = False,
    retry_count: int = 0,
    challenge_state: bool = False,
    escalation_disabled: bool = False,
    host_hard_block: bool = False,
    escalation_enabled: bool = True,
    max_retries: int = 1,
) -> dict[str, object]:
    acq = _FakeAcquisitionResult(
        method=method,
        blocked=blocked,
        browser_diagnostics={"browser_engine": browser_engine} if browser_engine else {},
    )
    gate = _FakeGateDecision(outcome=gate_outcome, reason=gate_reason)
    retry_state = _FakeRetryState(listing_integrity_retry_count=retry_count)
    policy = _FakePolicySnapshot(
        challenge_state=challenge_state,
        escalation_disabled=escalation_disabled,
        host_hard_block=host_hard_block,
    )
    with patch(
        "app.services.pipeline.listing_escalation_decision.crawler_runtime_settings"
    ) as mock_settings:
        mock_settings.listing_integrity_escalation_enabled = escalation_enabled
        mock_settings.listing_integrity_escalation_retry_max_per_run = max_retries
        return listing_integrity_escalation_decision(
            acq,
            gate_decision=gate,
            surface=surface,
            retry_state=retry_state,
            policy_snapshot=policy,
        )


class TestSkipReasons:
    """Each skip reason produces should_retry=False with the correct reason."""

    @pytest.mark.unit
    def test_not_listing_surface(self):
        result = _call(surface="ecommerce_detail")
        assert result["should_retry"] is False
        assert result["reason"] == "not_listing_surface"

    @pytest.mark.unit
    def test_gate_ok(self):
        result = _call(gate_outcome="product_grid")
        assert result["should_retry"] is False
        assert result["reason"] == "gate_ok"

    @pytest.mark.unit
    def test_already_retried(self):
        result = _call(retry_count=1, max_retries=1)
        assert result["should_retry"] is False
        assert result["reason"] == "already_retried"

    @pytest.mark.unit
    def test_blocked(self):
        result = _call(blocked=True)
        assert result["should_retry"] is False
        assert result["reason"] == "blocked"

    @pytest.mark.unit
    def test_challenge_state(self):
        result = _call(challenge_state=True)
        assert result["should_retry"] is False
        assert result["reason"] == "challenge_state"

    @pytest.mark.unit
    def test_escalation_disabled(self):
        result = _call(escalation_enabled=False)
        assert result["should_retry"] is False
        assert result["reason"] == "escalation_disabled"

    @pytest.mark.unit
    def test_host_hard_block(self):
        result = _call(host_hard_block=True)
        assert result["should_retry"] is False
        assert result["reason"] == "host_hard_block"

    @pytest.mark.unit
    def test_no_stronger_tier_from_real_chrome(self):
        """Already at real_chrome — no stronger tier available."""
        result = _call(method="browser", browser_engine="real_chrome")
        assert result["should_retry"] is False
        assert result["reason"] == "no_stronger_tier"

    @pytest.mark.unit
    def test_no_stronger_tier_patchright(self):
        """At patchright — listing escalation does not go to real_chrome."""
        result = _call(method="browser", browser_engine="patchright")
        assert result["should_retry"] is False
        assert result["reason"] == "no_stronger_tier"


class TestHappyPathRetry:
    """Retry triggers with correct tier computation."""

    @pytest.mark.unit
    def test_curl_cffi_escalates_to_browser_patchright(self):
        result = _call(method="curl_cffi")
        assert result["should_retry"] is True
        assert result["reason"] == "promo_only_cluster"
        assert result["prior_tier"] == "curl_cffi"
        assert result["next_tier"] == "browser:patchright"

    @pytest.mark.unit
    def test_httpx_escalates_to_browser_patchright(self):
        result = _call(method="httpx")
        assert result["should_retry"] is True
        assert result["prior_tier"] == "httpx"
        assert result["next_tier"] == "browser:patchright"

    @pytest.mark.unit
    def test_patchright_no_escalation(self):
        """Listing escalation does not go beyond patchright to real_chrome."""
        result = _call(method="browser", browser_engine="patchright")
        assert result["should_retry"] is False
        assert result["reason"] == "no_stronger_tier"

    @pytest.mark.unit
    def test_chromium_no_escalation(self):
        """Listing escalation does not go beyond chromium to real_chrome."""
        result = _call(method="browser", browser_engine="chromium")
        assert result["should_retry"] is False
        assert result["reason"] == "no_stronger_tier"

    @pytest.mark.unit
    def test_job_listing_surface_triggers_retry(self):
        result = _call(surface="job_listing", method="curl_cffi")
        assert result["should_retry"] is True
        assert result["next_tier"] == "browser:patchright"


class TestCandidateSummary:
    """candidate_summary is always populated from gate_decision metrics."""

    @pytest.mark.unit
    def test_candidate_summary_present_on_skip(self):
        result = _call(gate_outcome="product_grid")
        assert "candidate_summary" in result
        summary = result["candidate_summary"]
        assert "record_count" in summary
        assert "cohort_homogeneity_ratio" in summary

    @pytest.mark.unit
    def test_candidate_summary_present_on_retry(self):
        result = _call(method="curl_cffi")
        assert "candidate_summary" in result
        summary = result["candidate_summary"]
        assert summary["record_count"] == 5

    @pytest.mark.unit
    def test_gate_reason_propagated(self):
        result = _call(gate_reason="below_min_records")
        assert result["gate_reason"] == "below_min_records"
