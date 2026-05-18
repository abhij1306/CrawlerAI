from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Literal

from app.services.ucp_audit.types import UCPComplianceReport

_MARKDOWN_SPECIAL_CHARS = "\\`*_{}[]()#+-.!"
_MARKDOWN_SELECTIVE_SAFE_CHARS = frozenset({".", "-"})


def escape_markdown(
    value: object,
    *,
    mode: Literal["full", "selective"] = "full",
    safe_chars: Iterable[str] | None = None,
) -> str:
    text = str(value)
    safe = set(safe_chars or ())
    if mode == "selective":
        safe.update(_MARKDOWN_SELECTIVE_SAFE_CHARS)
    return "".join(
        f"\\{char}" if char in _MARKDOWN_SPECIAL_CHARS and char not in safe else char
        for char in text
    )


def build_report_payload(report: UCPComplianceReport) -> dict[str, Any]:
    return {
        "domain": report.domain,
        "audit_id": report.audit_id,
        "overall_score": report.overall_score,
        "d_ucp1_gate_applied": report.d_ucp1_gate_applied,
        "dimension_scores": [asdict(item) for item in report.dimension_scores],
        "findings": [asdict(item) for item in report.all_findings],
        "agent_view_samples": [asdict(item) for item in report.agent_view_samples],
    }


def build_markdown_report(report: UCPComplianceReport) -> str:
    lines = [
        f"# UCP Compliance Audit: {escape_markdown(report.domain, mode='selective')}",
        "",
        "## Executive Summary",
        f"- Audit ID: {escape_markdown(report.audit_id, mode='selective')}",
        f"- Overall score: {escape_markdown(report.overall_score)}",
        f"- D-UCP1 gate applied: {escape_markdown(report.d_ucp1_gate_applied)}",
        "",
        "## Dimension Scores",
    ]
    for dimension in report.dimension_scores:
        lines.append(
            f"- {escape_markdown(dimension.dimension_id)}: "
            f"{escape_markdown(dimension.score)} ({escape_markdown(dimension.status)})"
        )
    lines.extend(["", "## Findings"])
    if report.all_findings:
        for finding in report.all_findings:
            message = f" - {escape_markdown(finding.message)}" if finding.message else ""
            lines.append(
                f"- {escape_markdown(finding.dimension_id)} {escape_markdown(finding.code)} "
                f"[{escape_markdown(finding.severity)}]{message}"
            )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"
