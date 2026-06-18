from __future__ import annotations

from app.services.config.browser_surface_probe import (
    BROWSER_SURFACE_PROBE_AGENT_EVIDENCE_TEXT_LIMIT,
)
from browser_surface_probe.value_coercion import (
    BROWSER_VERSION_RE,
    object_dict,
    object_list,
    string_list,
)


def _ua_major(user_agent: object) -> int | None:
    match = BROWSER_VERSION_RE.search(str(user_agent or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _truncate_evidence(value: object) -> object:
    if isinstance(value, list):
        return object_list(value)[:5]
    text = value if isinstance(value, str) else str(value)
    return text[: int(BROWSER_SURFACE_PROBE_AGENT_EVIDENCE_TEXT_LIMIT)]


def build_agent_summary(report: dict[str, object]) -> dict[str, object]:
    metadata = object_dict(report.get("metadata"))
    baseline = object_dict(report.get("baseline"))
    consensus = object_dict(baseline.get("consensus"))
    findings = object_list(report.get("findings"))
    sites = object_dict(report.get("sites"))
    target_diagnostics = object_list(report.get("target_diagnostics"))
    severity_counts: dict[str, int] = {"fail": 0, "warn": 0, "info": 0}
    normalized_findings = [
        object_dict(finding) for finding in findings if isinstance(finding, dict)
    ]
    for finding in normalized_findings:
        severity = str(finding.get("severity") or "").strip().lower()
        if severity in severity_counts:
            severity_counts[severity] += 1
    site_rows: list[dict[str, object]] = []
    for site_id, raw_site_payload in sorted(sites.items()):
        site_payload = object_dict(raw_site_payload)
        snapshot_summary = object_dict(site_payload.get("snapshot_summary"))
        site_rows.append(
            {
                "site_id": site_id,
                "label": site_payload.get("label"),
                "status": site_payload.get("site_status"),
                "attempts": site_payload.get("attempts"),
                "line_count": snapshot_summary.get("line_count"),
                "line_count_raw": snapshot_summary.get("line_count_raw"),
                "row_count": snapshot_summary.get("row_count"),
                "row_count_raw": snapshot_summary.get("row_count_raw"),
                "validation_warnings": object_list(
                    site_payload.get("validation_warnings")
                ),
                "final_url": site_payload.get("final_url") or site_payload.get("url"),
                "error": site_payload.get("error"),
            }
        )
    target_rows: list[dict[str, object]] = []
    for raw_payload in target_diagnostics:
        if not isinstance(raw_payload, dict):
            continue
        payload = object_dict(raw_payload)
        root_cause = object_dict(payload.get("root_cause"))
        browser = object_dict(payload.get("browser"))
        httpx_payload = object_dict(payload.get("httpx"))
        curl_payload = object_dict(payload.get("curl_cffi"))
        target_rows.append(
            {
                "url": payload.get("url"),
                "host": payload.get("host"),
                "root_cause_category": root_cause.get("category"),
                "root_cause_confidence": root_cause.get("confidence"),
                "browser_status": browser.get("status"),
                "browser_blocked": browser.get("blocked"),
                "httpx_status": httpx_payload.get("status"),
                "httpx_blocked": httpx_payload.get("blocked"),
                "curl_status": curl_payload.get("status"),
                "curl_blocked": curl_payload.get("blocked"),
            }
        )
    return {
        "generated_at": metadata.get("generated_at"),
        "engine": metadata.get("browser_engine"),
        "source_kind": metadata.get("source_kind"),
        "degraded": bool(metadata.get("degraded")),
        "selected_proxy_mask": metadata.get("selected_proxy_mask"),
        "severity_counts": severity_counts,
        "findings": [
            {
                "severity": str(finding.get("severity") or ""),
                "category": str(finding.get("category") or ""),
                "message": str(finding.get("message") or ""),
                "evidence": _truncate_evidence(finding.get("evidence")),
            }
            for finding in normalized_findings
        ],
        "baseline": {
            "user_agent_major": _ua_major(consensus.get("user_agent")),
            "locale": consensus.get("locale"),
            "timezone": consensus.get("timezone"),
            "webdriver": consensus.get("webdriver"),
            "webrtc_ip_count": len(object_list(consensus.get("webrtc_ips"))),
            "automation_globals_count": len(
                object_list(consensus.get("automation_globals"))
            ),
            "iframe_leak": object_dict(consensus.get("iframe_leak")).get(
                "content_window_array_leak"
            ),
            "canvas_text_measure": object_dict(consensus.get("canvas")).get(
                "text_measure"
            ),
            "canvas_image_data_hash": object_dict(consensus.get("canvas")).get(
                "image_data_hash"
            ),
            "canvas_data_url_prefix": object_dict(consensus.get("canvas")).get(
                "data_url_prefix"
            ),
            "audio_fingerprint": object_dict(consensus.get("audio")).get(
                "fingerprint"
            ),
            "webgl_vendor": object_dict(consensus.get("webgl")).get("vendor"),
            "webgl_renderer": object_dict(consensus.get("webgl")).get("renderer"),
            "fonts_count": len(object_list(consensus.get("fonts"))),
            "max_touch_points": consensus.get("max_touch_points"),
            "pdf_viewer_enabled": consensus.get("pdf_viewer_enabled"),
            "cookie_enabled": consensus.get("cookie_enabled"),
            "drift_keys": sorted(object_dict(baseline.get("drift"))),
        },
        "sites": site_rows,
        "target_diagnostics": target_rows,
    }


def render_markdown(report: dict[str, object]) -> str:
    summary = build_agent_summary(report)
    findings = object_list(summary.get("findings"))
    sites = object_list(summary.get("sites"))
    target_diagnostics = object_list(summary.get("target_diagnostics"))
    baseline = object_dict(summary.get("baseline"))
    severity_counts = object_dict(summary.get("severity_counts"))
    lines = [
        "# Browser Fingerprint Report",
        "",
        f"- Generated: {summary.get('generated_at')}",
        f"- Engine: {summary.get('engine')}",
        f"- Source: {summary.get('source_kind')}",
        f"- Degraded: {summary.get('degraded')}",
        f"- Proxy: {summary.get('selected_proxy_mask')}",
        f"- Findings: fail={severity_counts.get('fail', 0)}, warn={severity_counts.get('warn', 0)}, info={severity_counts.get('info', 0)}",
        "",
        "## Baseline",
        f"- UA major: {baseline.get('user_agent_major')}",
        f"- Locale: {baseline.get('locale')}",
        f"- Timezone: {baseline.get('timezone')}",
        f"- Webdriver: {baseline.get('webdriver')}",
        f"- WebRTC IP count: {baseline.get('webrtc_ip_count')}",
        f"- Automation globals count: {baseline.get('automation_globals_count')}",
        f"- Iframe leak: {baseline.get('iframe_leak')}",
        f"- Canvas text measure: {baseline.get('canvas_text_measure')}",
        f"- Canvas image-data hash: {baseline.get('canvas_image_data_hash')}",
        f"- Canvas data-url prefix: {baseline.get('canvas_data_url_prefix')}",
        f"- Audio fingerprint: {baseline.get('audio_fingerprint')}",
        f"- WebGL vendor: {baseline.get('webgl_vendor')}",
        f"- WebGL renderer: {baseline.get('webgl_renderer')}",
        f"- Fonts count: {baseline.get('fonts_count')}",
        f"- Max touch points: {baseline.get('max_touch_points')}",
        f"- PDF viewer enabled: {baseline.get('pdf_viewer_enabled')}",
        f"- Cookie enabled: {baseline.get('cookie_enabled')}",
        f"- Drift keys: {', '.join(string_list(baseline.get('drift_keys'))) or 'none'}",
        "",
        "## Findings",
    ]
    if findings:
        for raw_finding in findings:
            finding = object_dict(raw_finding)
            lines.append(
                f"- {str(finding.get('severity') or '').upper()} [{finding.get('category')}]: {finding.get('message')}"
            )
    else:
        lines.append("- INFO: no findings")
    lines.extend(["", "## Sites"])
    for raw_site in sites:
        site = object_dict(raw_site)
        warnings = string_list(site.get("validation_warnings"))
        warning_text = ",".join(warnings) if warnings else "none"
        lines.append(
            f"- {site.get('site_id')}: status={site.get('status')} attempts={site.get('attempts')} lines={site.get('line_count')}/{site.get('line_count_raw')} rows={site.get('row_count')}/{site.get('row_count_raw')} warnings={warning_text}"
        )
    if target_diagnostics:
        lines.extend(["", "## Target Diagnostics"])
        for raw_payload in target_diagnostics:
            payload = object_dict(raw_payload)
            lines.append(
                f"- {payload.get('host') or payload.get('url')}: {payload.get('root_cause_category')} ({payload.get('root_cause_confidence')}) browser={payload.get('browser_status')}/{payload.get('browser_blocked')} httpx={payload.get('httpx_status')}/{payload.get('httpx_blocked')} curl={payload.get('curl_status')}/{payload.get('curl_blocked')}"
            )
    return "\n".join(lines).strip() + "\n"


__all__ = [
    "build_agent_summary",
    "render_markdown",
]
