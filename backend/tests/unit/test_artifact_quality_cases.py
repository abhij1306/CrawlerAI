from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from harness.artifact_quality_cases import (
    _case_signals,
    audit_artifact_quality_cases,
    load_artifact_quality_cases,
    validate_artifact_quality_cases,
)

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "extraction"
    / "artifact_quality_cases_20260625.json"
)


def test_artifact_quality_cases_are_valid_and_offline() -> None:
    manifest = load_artifact_quality_cases(FIXTURE)

    assert validate_artifact_quality_cases(manifest, backend_root=BACKEND_ROOT) == []


def test_artifact_report_distinguishes_integrity_failure_from_source_unavailable() -> (
    None
):
    manifest = load_artifact_quality_cases(FIXTURE)

    report = audit_artifact_quality_cases(manifest, backend_root=BACKEND_ROOT)
    cases = {case["case_id"]: case for case in report["cases"]}

    assert report["quality_clean"] is False
    assert report["case_count"] == 2
    assert cases["endclothing-cross-product-variants"]["classification"] == (
        "integrity_failure"
    )
    assert cases["target-product-api-unavailable"]["classification"] == (
        "source_unavailable"
    )
    assert cases["target-product-api-unavailable"]["unresolved_issue_ids"] == ()


def test_end_case_is_derived_from_stored_record_not_manual_resolution() -> None:
    manifest = load_artifact_quality_cases(FIXTURE)

    report = audit_artifact_quality_cases(manifest, backend_root=BACKEND_ROOT)
    end_case = next(
        case
        for case in report["cases"]
        if case["case_id"] == "endclothing-cross-product-variants"
    )

    assert end_case["signals"]["cross_product_variant_skus"] == (
        "11145-91001",
        "HM31TE011-WHT",
        "JN3708",
        "JQ6823",
        "VN000CQAOFW",
    )
    assert end_case["signals"]["raw_availability"].startswith("https://schema.org/")
    assert end_case["field_states"]["brand"] == "captured_but_rejected"
    assert end_case["field_states"]["availability"] == "captured_but_rejected"
    assert end_case["field_state_mismatches"] == ()
    assert "QD-13" in end_case["unresolved_issue_ids"]


def test_target_case_attributes_offer_absence_to_unavailable_product_source() -> None:
    manifest = load_artifact_quality_cases(FIXTURE)

    report = audit_artifact_quality_cases(manifest, backend_root=BACKEND_ROOT)
    target_case = next(
        case
        for case in report["cases"]
        if case["case_id"] == "target-product-api-unavailable"
    )

    assert target_case["signals"]["source_unavailable"] is True
    assert target_case["field_states"]["price"] == "source_unavailable"
    assert target_case["field_states"]["currency"] == "source_unavailable"
    assert target_case["field_states"]["availability"] == "source_unavailable"
    assert target_case["field_state_mismatches"] == ()


def test_selected_product_title_mismatch_is_integrity_failure() -> None:
    signals = _case_signals(
        {
            "expected_invariants": {
                "selected_product_title": "Expected Product"
            }
        },
        records={
            "records": [{"title": "Wrong Product"}],
            "provenance": [{"raw_data": {"title": "Wrong Product", "variants": []}}],
        },
        debug={},
    )

    assert signals["selected_product_title_matches"] is False
    assert signals["integrity_failure"] is True


def test_manifest_validation_rejects_declared_state_that_artifacts_do_not_support() -> (
    None
):
    manifest = deepcopy(load_artifact_quality_cases(FIXTURE))
    manifest["cases"][1]["expected_field_states"]["price"] = "captured_and_resolved"

    errors = validate_artifact_quality_cases(manifest, backend_root=BACKEND_ROOT)

    assert errors == [
        "target-product-api-unavailable field state mismatch: "
        "price expected=captured_and_resolved actual=source_unavailable"
    ]
