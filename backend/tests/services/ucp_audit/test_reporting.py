from __future__ import annotations

from app.services.config.ucp_audit import D_UCP1_ID
from app.services.ucp_audit.reporting import (
    build_markdown_report,
    build_report_payload,
)
from app.services.ucp_audit.types import (
    UCPComplianceReport,
    UCPDimensionScore,
    UCPFinding,
)


def test_report_payload_contains_summary_scores_and_findings() -> None:
    finding = UCPFinding(
        code="manifest_missing",
        dimension_id=D_UCP1_ID,
        severity="blocking",
    )
    report = UCPComplianceReport(
        domain="example.com",
        audit_id="audit-1",
        overall_score=64,
        dimension_scores=[
            UCPDimensionScore(
                dimension_id=D_UCP1_ID,
                score=0,
                status="fail",
                findings=[finding],
                weight=1.0,
            )
        ],
        all_findings=[finding],
        d_ucp1_gate_applied=True,
        agent_view_samples=[],
    )

    payload = build_report_payload(report)

    assert payload["domain"] == "example.com"
    assert payload["overall_score"] == 64
    assert payload["d_ucp1_gate_applied"] is True
    assert payload["dimension_scores"][0]["dimension_id"] == D_UCP1_ID
    assert payload["findings"][0]["code"] == "manifest_missing"
    assert payload["agent_view_samples"] == []


def test_markdown_report_has_operational_sections() -> None:
    report = UCPComplianceReport(
        domain="example.com",
        audit_id="audit-1",
        overall_score=88,
        dimension_scores=[
            UCPDimensionScore(
                dimension_id=D_UCP1_ID,
                score=100,
                status="pass",
                findings=[],
                weight=1.0,
            )
        ],
        all_findings=[],
        d_ucp1_gate_applied=False,
        agent_view_samples=[],
    )

    markdown = build_markdown_report(report)

    assert "# UCP Compliance Audit: example\\.com" in markdown
    assert "## Executive Summary" in markdown
    assert "## Dimension Scores" in markdown
    assert "## Findings" in markdown


def test_markdown_report_escapes_interpolated_values() -> None:
    report = UCPComplianceReport(
        domain="store_[x].com",
        audit_id="audit(1)",
        overall_score=88,
        dimension_scores=[
            UCPDimensionScore(
                dimension_id="D-UCP[1]",
                score=100,
                status="pass!",
                findings=[],
                weight=1.0,
            )
        ],
        all_findings=[
            UCPFinding(
                code="manifest_missing*",
                dimension_id="D-UCP[1]",
                severity="blocking",
                message="fix [manifest](now)",
            )
        ],
        d_ucp1_gate_applied=False,
        agent_view_samples=[],
    )

    markdown = build_markdown_report(report)

    assert "store\\_\\[x\\]\\.com" in markdown
    assert "audit\\(1\\)" in markdown
    assert "D\\-UCP\\[1\\]" in markdown
    assert "manifest\\_missing\\*" in markdown
    assert "fix \\[manifest\\]\\(now\\)" in markdown
