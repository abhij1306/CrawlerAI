"""Unit tests for _propagate_listing_integrity_to_diagnostics in extraction_runtime.

Validates task 8.1 requirements:
- Thread IntegrityDecision onto browser_diagnostics under key listing_integrity
- Do NOT attach to individual records (INVARIANTS Rule 8)
- On retry, move prior decision to listing_integrity.previous
"""

from __future__ import annotations

import copy

from app.services.extraction_runtime import _propagate_listing_integrity_to_diagnostics


class TestPropagateListingIntegrityToDiagnostics:
    """Tests for _propagate_listing_integrity_to_diagnostics."""

    def test_threads_decision_onto_browser_diagnostics(self):
        """Decision from artifacts is written to browser_diagnostics under listing_integrity."""
        decision = {"outcome": "product_grid", "reason": "supported_set", "metrics": {"record_count": 5}}
        artifacts = {"listing_integrity": decision}
        browser_diagnostics: dict = {}

        _propagate_listing_integrity_to_diagnostics(artifacts, browser_diagnostics)

        assert browser_diagnostics["listing_integrity"] == decision

    def test_noop_when_artifacts_none(self):
        """No crash or mutation when artifacts is None."""
        browser_diagnostics: dict = {}
        _propagate_listing_integrity_to_diagnostics(None, browser_diagnostics)
        assert "listing_integrity" not in browser_diagnostics

    def test_noop_when_browser_diagnostics_none(self):
        """No crash when browser_diagnostics is None."""
        artifacts = {"listing_integrity": {"outcome": "product_grid", "reason": "supported_set", "metrics": {}}}
        result = _propagate_listing_integrity_to_diagnostics(artifacts, None)
        assert result is None

    def test_noop_when_no_decision_in_artifacts(self):
        """No mutation when artifacts has no listing_integrity key."""
        artifacts: dict = {"other_key": "value"}
        browser_diagnostics: dict = {}
        _propagate_listing_integrity_to_diagnostics(artifacts, browser_diagnostics)
        assert "listing_integrity" not in browser_diagnostics

    def test_noop_when_decision_not_dict(self):
        """Non-dict listing_integrity in artifacts is ignored."""
        artifacts: dict = {"listing_integrity": "not_a_dict"}
        browser_diagnostics: dict = {}
        _propagate_listing_integrity_to_diagnostics(artifacts, browser_diagnostics)
        assert "listing_integrity" not in browser_diagnostics

    def test_retry_moves_prior_to_previous(self):
        """On retry, prior decision is preserved under listing_integrity.previous."""
        first_decision = {"outcome": "promo_only_cluster", "reason": "cohort_heterogeneous", "metrics": {"record_count": 3}}
        second_decision = {"outcome": "product_grid", "reason": "supported_set", "metrics": {"record_count": 20}}

        browser_diagnostics: dict = {"listing_integrity": first_decision}
        artifacts = {"listing_integrity": second_decision}

        _propagate_listing_integrity_to_diagnostics(artifacts, browser_diagnostics)

        result = browser_diagnostics["listing_integrity"]
        assert result["outcome"] == "product_grid"
        assert result["reason"] == "supported_set"
        assert result["previous"] == first_decision

    def test_retry_does_not_mutate_original_artifacts(self):
        """The original decision dict in artifacts is not mutated by the previous-merge."""
        first_decision = {"outcome": "promo_only_cluster", "reason": "below_min_records", "metrics": {}}
        second_decision = {"outcome": "product_grid", "reason": "supported_set", "metrics": {}}
        second_decision_copy = copy.deepcopy(second_decision)

        browser_diagnostics: dict = {"listing_integrity": first_decision}
        artifacts = {"listing_integrity": second_decision}

        _propagate_listing_integrity_to_diagnostics(artifacts, browser_diagnostics)

        # Original artifacts dict should not have "previous" key added
        assert "previous" not in artifacts["listing_integrity"]
        assert artifacts["listing_integrity"] == second_decision_copy

    def test_does_not_attach_to_individual_records(self):
        """Decision is only on browser_diagnostics, never on records (INVARIANTS Rule 8).

        _propagate_listing_integrity_to_diagnostics does not accept records;
        this test verifies that the function only writes to browser_diagnostics
        and does not modify the artifacts dict's original entry.
        """
        decision = {"outcome": "product_grid", "reason": "supported_set", "metrics": {}}
        artifacts = {"listing_integrity": decision}
        browser_diagnostics: dict = {}

        _propagate_listing_integrity_to_diagnostics(artifacts, browser_diagnostics)

        # Decision is on browser_diagnostics
        assert "listing_integrity" in browser_diagnostics
        # Original artifacts entry is not mutated (no "previous" key added)
        assert "previous" not in artifacts["listing_integrity"]
