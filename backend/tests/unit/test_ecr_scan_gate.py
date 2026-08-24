from __future__ import annotations

import pytest

from ecr_scan_gate import evaluate_ecr_scan

pytestmark = pytest.mark.unit


def _scan(*findings: dict[str, str], status: str = "ACTIVE") -> dict[str, object]:
    return {
        "imageScanStatus": {"status": status},
        "imageScanFindings": {"enhancedFindings": list(findings)},
    }


def _finding(*, severity: str, fix_available: str | None) -> dict[str, str]:
    finding = {
        "severity": severity,
        "title": f"fixture-{severity.lower()}",
    }
    if fix_available is not None:
        finding["fixAvailable"] = fix_available
    return finding


def test_safe_enhanced_scan_passes() -> None:
    report = evaluate_ecr_scan(_scan(_finding(severity="MEDIUM", fix_available="YES")))

    assert report == {
        "allowed": True,
        "scan_status": "ACTIVE",
        "reason": "policy_passed",
        "finding_count": 0,
        "findings": [],
    }


@pytest.mark.parametrize("fix_available", ["YES", "PARTIAL"])
def test_fixable_high_finding_blocks_release(fix_available: str) -> None:
    report = evaluate_ecr_scan(
        _scan(_finding(severity="HIGH", fix_available=fix_available)),
        reviewed_no_fix_high_critical=True,
        risk_acceptance_reference="SEC-123",
    )

    assert report["allowed"] is False
    assert report["reason"] == "fixable_high_or_critical"


def test_unclassified_critical_finding_cannot_be_excepted() -> None:
    report = evaluate_ecr_scan(
        _scan(_finding(severity="CRITICAL", fix_available=None)),
        reviewed_no_fix_high_critical=True,
        risk_acceptance_reference="SEC-123",
    )

    assert report["allowed"] is False
    assert report["reason"] == "unclassified_high_or_critical"


def test_missing_finding_severity_blocks_release() -> None:
    report = evaluate_ecr_scan(_scan({"title": "missing-severity"}))

    assert report["allowed"] is False
    assert report["reason"] == "enhanced_scan_finding_severity_invalid"


def test_no_fix_high_requires_explicit_review_and_reference() -> None:
    scan = _scan(_finding(severity="HIGH", fix_available="NO"))

    assert evaluate_ecr_scan(scan)["allowed"] is False
    assert (
        evaluate_ecr_scan(scan, reviewed_no_fix_high_critical=True)["allowed"] is False
    )
    accepted = evaluate_ecr_scan(
        scan,
        reviewed_no_fix_high_critical=True,
        risk_acceptance_reference="SEC-123 expires 2026-09-30",
    )
    assert accepted["allowed"] is True
    assert accepted["finding_count"] == 1


@pytest.mark.parametrize("payload", [{}, _scan(status="FAILED")])
def test_missing_or_failed_scan_blocks_release(payload: dict[str, object]) -> None:
    report = evaluate_ecr_scan(payload)

    assert report["allowed"] is False
    assert report["reason"] == "scan_not_ready_or_failed"


def test_basic_scan_output_does_not_satisfy_enhanced_scan_policy() -> None:
    payload = {
        "imageScanStatus": {"status": "COMPLETE"},
        "imageScanFindings": {"findings": []},
    }

    report = evaluate_ecr_scan(payload)

    assert report["allowed"] is False
    assert report["reason"] == "enhanced_scan_evidence_missing"
