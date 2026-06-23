from __future__ import annotations

from pathlib import Path

import pytest

from harness.quality_evaluator import (
    audit_catalog_quality_manifest,
    build_catalog_quality_report,
    load_catalog_quality_manifest,
    validate_catalog_quality_manifest,
)

pytestmark = pytest.mark.unit

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "extraction"
    / "catalog_quality_20260623.json"
)


def test_frozen_catalog_quality_manifest_reproduces_baseline() -> None:
    manifest = load_catalog_quality_manifest(FIXTURE)

    assert manifest["record_count"] == 91
    assert audit_catalog_quality_manifest(manifest) == manifest["expected_counts"]
    assert validate_catalog_quality_manifest(manifest) == []


def test_frozen_catalog_quality_manifest_covers_single_issue_tracker() -> None:
    manifest = load_catalog_quality_manifest(FIXTURE)

    assert set(manifest["issue_examples"]) == {
        f"QD-{index:02d}" for index in range(1, 14)
    }
    assert all(manifest["issue_examples"].values())


def test_catalog_quality_report_is_clean_only_after_every_qd_resolution() -> None:
    manifest = load_catalog_quality_manifest(FIXTURE)

    report = build_catalog_quality_report(manifest)

    assert report["quality_clean"] is True
    assert report["unresolved_blocker_count"] == 0
    assert report["unresolved_issue_ids"] == ()
    assert report["baseline_signal_count"] == sum(
        manifest["expected_counts"].values()
    )
    assert report["affected_url_count"] > 0
    assert {issue["issue_id"] for issue in report["issues"]} == {
        f"QD-{index:02d}" for index in range(1, 14)
    }
    assert all(row["lineage_pointers"] for row in report["records"])


def test_quality_verdict_is_independent_of_transport_success() -> None:
    manifest = load_catalog_quality_manifest(FIXTURE)
    manifest["transport_success"] = True
    manifest["issue_resolutions"]["QD-06"] = {
        "classification": "unresolved",
        "findings": ["MISSING_OR_GENERIC_TITLE"],
        "verification": [],
    }

    report = build_catalog_quality_report(manifest)

    assert report["quality_clean"] is False
    assert report["unresolved_issue_ids"] == ("QD-06",)


def test_manifest_validation_reports_all_failures() -> None:
    manifest = load_catalog_quality_manifest(FIXTURE)
    manifest["record_count"] = 0
    manifest["issue_examples"]["QD-01"] = []
    manifest["expected_counts"]["missing_title"] = 999
    manifest["issue_resolutions"]["QD-13"] = {
        "classification": "unresolved",
        "findings": [],
        "verification": [],
    }

    errors = validate_catalog_quality_manifest(manifest)

    assert len(errors) == 5
    assert any("record_count" in error for error in errors)
    assert any("QD-01" in error for error in errors)
    assert any("QD-13 has unresolved" in error for error in errors)
    assert any("QD-13 has no finding" in error for error in errors)
    assert any("expected_counts mismatch" in error for error in errors)
