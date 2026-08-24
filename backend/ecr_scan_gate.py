"""Fail-closed policy gate for Amazon ECR enhanced image-scan findings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_ACCEPTED_SCAN_STATUSES = frozenset({"ACTIVE", "COMPLETE"})
_BLOCKING_SEVERITIES = frozenset({"HIGH", "CRITICAL"})
_NONBLOCKING_SEVERITIES = frozenset({"INFORMATIONAL", "LOW", "MEDIUM"})
_VALID_SEVERITIES = _NONBLOCKING_SEVERITIES | _BLOCKING_SEVERITIES
_FIX_AVAILABLE = frozenset({"YES", "PARTIAL"})


def _finding_summary(finding: dict[str, Any]) -> dict[str, str]:
    package_details = finding.get("packageVulnerabilityDetails")
    if not isinstance(package_details, dict):
        package_details = {}
    return {
        "id": str(
            package_details.get("vulnerabilityId")
            or finding.get("title")
            or finding.get("findingArn")
            or "unknown"
        ),
        "severity": str(finding.get("severity") or "UNDEFINED").upper(),
        "fix_available": str(finding.get("fixAvailable") or "UNCLASSIFIED").upper(),
    }


def evaluate_ecr_scan(
    payload: dict[str, Any],
    *,
    reviewed_no_fix_high_critical: bool = False,
    risk_acceptance_reference: str = "",
) -> dict[str, Any]:
    status, error, raw_findings = _enhanced_findings(payload)
    if error is not None:
        return _report(False, status, error, [])
    high_critical = _high_critical_findings(raw_findings)
    return _finding_decision(
        status,
        high_critical,
        reviewed_no_fix_high_critical=reviewed_no_fix_high_critical,
        risk_acceptance_reference=risk_acceptance_reference,
    )


def _enhanced_findings(
    payload: dict[str, Any],
) -> tuple[str, str | None, list[Any]]:
    status = str((payload.get("imageScanStatus") or {}).get("status") or "UNKNOWN")
    scan_findings = payload.get("imageScanFindings")
    if status not in _ACCEPTED_SCAN_STATUSES or not isinstance(scan_findings, dict):
        return status, "scan_not_ready_or_failed", []
    if "enhancedFindings" not in scan_findings:
        return status, "enhanced_scan_evidence_missing", []
    raw_findings = scan_findings.get("enhancedFindings")
    if not isinstance(raw_findings, list):
        return status, "enhanced_scan_evidence_invalid", []
    if any(
        not isinstance(finding, dict)
        or str(finding.get("severity") or "").upper() not in _VALID_SEVERITIES
        for finding in raw_findings
    ):
        return status, "enhanced_scan_finding_severity_invalid", []
    return status, None, raw_findings


def _high_critical_findings(raw_findings: list[Any]) -> list[dict[str, str]]:
    return [
        _finding_summary(finding)
        for finding in raw_findings
        if isinstance(finding, dict)
        and str(finding.get("severity") or "").upper() in _BLOCKING_SEVERITIES
    ]


def _finding_decision(
    status: str,
    high_critical: list[dict[str, str]],
    *,
    reviewed_no_fix_high_critical: bool,
    risk_acceptance_reference: str,
) -> dict[str, Any]:
    fixable = [
        finding
        for finding in high_critical
        if finding["fix_available"] in _FIX_AVAILABLE
    ]
    unclassified = [
        finding
        for finding in high_critical
        if finding["fix_available"] not in {*_FIX_AVAILABLE, "NO"}
    ]
    no_fix = [finding for finding in high_critical if finding["fix_available"] == "NO"]
    if fixable:
        return _report(False, status, "fixable_high_or_critical", fixable)
    if unclassified:
        return _report(False, status, "unclassified_high_or_critical", unclassified)
    reviewed = reviewed_no_fix_high_critical and bool(risk_acceptance_reference.strip())
    if no_fix and not reviewed:
        return _report(False, status, "unreviewed_no_fix_high_or_critical", no_fix)
    return _report(True, status, "policy_passed", no_fix)


def _report(
    allowed: bool,
    status: str,
    reason: str,
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "allowed": allowed,
        "scan_status": status,
        "reason": reason,
        "finding_count": len(findings),
        "findings": findings,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan_json", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--reviewed-no-fix-high-critical", action="store_true")
    parser.add_argument("--risk-acceptance-reference", default="")
    return parser


def main() -> int:
    args = _parser().parse_args()
    payload = json.loads(args.scan_json.read_text(encoding="utf-8"))
    report = evaluate_ecr_scan(
        payload,
        reviewed_no_fix_high_critical=args.reviewed_no_fix_high_critical,
        risk_acceptance_reference=args.risk_acceptance_reference,
    )
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":")))
    return 0 if report["allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
