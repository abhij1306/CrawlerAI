from __future__ import annotations

from typing import Any


def build_markdown_report(report: dict[str, Any]) -> str:
    scores = dict(report.get("scores") or {})
    lines = [
        "# Page Technical Audit",
        "",
        f"URL: {report.get('url', '')}",
        "",
        "## Scores",
        "",
    ]
    for key, value in scores.items():
        label = str(key).replace("_", " ").title()
        lines.append(f"- {label}: {'N/A' if value is None else f'{value}/100'}")
    failures = [
        check
        for group in ("source_checks", "dom_checks", "diff_checks")
        for check in list(report.get(group) or [])
        if isinstance(check, dict)
        and check.get("applicable", True)
        and not check.get("passed", False)
    ]
    lines.extend(["", "## Findings", ""])
    if not failures:
        lines.append("No failed checks.")
    for check in failures:
        lines.extend(
            [
                f"### {check.get('label') or check.get('id')}",
                "",
                f"- Severity: {check.get('severity')}",
                f"- Source: {check.get('data_source')}",
                f"- Detected: `{check.get('detected_value')}`",
                f"- Expected: `{check.get('expected_value')}`",
                f"- Fix: {check.get('fix')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
