from __future__ import annotations

from ipaddress import ip_address

from app.core.config.browser_surface_probe import (
    BROWSER_SURFACE_PROBE_AGENT_EVIDENCE_TEXT_LIMIT,
)
from browser_surface_probe.value_coercion import (
    BROWSER_VERSION_RE,
    object_dict,
    object_list,
    string_list,
    coalesce as _coalesce,
    country_code_from_value as _country_code_from_value,
    dedupe as _dedupe,
    extract_versions as _extract_versions,
    int_list as _int_list,
    locale_region as _locale_region,
    looks_like_truthy_risk as _looks_like_truthy_risk,
    normalize_space as _normalize_space,
    percent_value as _percent_value,
    timezone_matches_country as _timezone_matches_country,
)
from browser_surface_probe.target_diagnostics import _target_root_cause

_object_dict = object_dict
_object_list = object_list
_string_list = string_list


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
            "audio_fingerprint": object_dict(consensus.get("audio")).get("fingerprint"),
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
    "build_findings",
    "render_markdown",
]


def _probe_status_findings(
    sites: dict[str, object],
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for status, category, message in (
        (
            "failed",
            "probe_site_failure",
            "One or more browser surface probe sites failed; report is partial.",
        ),
        (
            "degraded",
            "probe_site_degraded",
            "One or more browser surface probe extractors saw unexpected page structure.",
        ),
    ):
        matching = [
            site_id
            for site_id, payload in sites.items()
            if _object_dict(payload).get("site_status") == status
        ]
        if matching:
            findings.append(
                {
                    "severity": "warn",
                    "category": category,
                    "message": message,
                    "evidence": matching,
                }
            )
    return findings


def _observed_geo_country(target_diagnostics: list[object]) -> str | None:
    for diagnostic in target_diagnostics:
        geo = _object_dict(
            _object_dict(_object_dict(diagnostic).get("geo")).get("consensus")
        )
        country = _country_code_from_value(str(geo.get("country") or ""))
        if country:
            return country
    return None


def _geo_findings(
    consensus: dict[str, object],
    pixelscan: dict[str, object],
    target_diagnostics: list[object],
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    country = _coalesce(
        _string_list(_object_dict(pixelscan.get("extracted")).get("country_values"))
    )
    country_code = _country_code_from_value(str(country or ""))
    observed_country = _observed_geo_country(target_diagnostics)
    provider_drift = bool(
        country_code and observed_country and country_code != observed_country
    )
    if provider_drift:
        findings.append(
            {
                "severity": "warn",
                "category": "proxy_geo_provider_drift",
                "message": f"Pixelscan geolocates the same exit IP as {country_code} while direct geo endpoints report {observed_country}.",
                "evidence": {
                    "pixelscan_country": country,
                    "observed_geo_country": observed_country,
                },
            }
        )
    timezone_value = str(consensus.get("timezone") or "")
    if (
        _timezone_matches_country(timezone_value, country_code) is False
        and not provider_drift
    ):
        findings.append(
            {
                "severity": "fail",
                "category": "timezone_country_mismatch",
                "message": f"Timezone {timezone_value or 'unknown'} does not match Pixelscan country {country or 'unknown'}.",
                "evidence": {"timezone": timezone_value, "pixelscan_country": country},
            }
        )
    locale_region = _locale_region(str(consensus.get("locale") or ""))
    if (
        locale_region
        and country_code
        and locale_region != country_code
        and not provider_drift
    ):
        findings.append(
            {
                "severity": "warn",
                "category": "locale_region_drift",
                "message": f"Locale region {locale_region} drifts from Pixelscan country {country_code}.",
                "evidence": {"locale": consensus.get("locale"), "country": country},
            }
        )
    return findings


def _version_findings(
    consensus: dict[str, object], sites: dict[str, object]
) -> list[dict[str, object]]:
    baseline_versions = _extract_versions([str(consensus.get("user_agent") or "")])
    extracted_versions: list[int] = []
    for site in sites.values():
        extracted_versions.extend(
            _int_list(
                _object_dict(_object_dict(site).get("extracted")).get("signal_versions")
            )
        )
    extracted_versions = sorted(set(extracted_versions))
    if not (
        baseline_versions
        and extracted_versions
        and any(version not in baseline_versions for version in extracted_versions)
    ):
        return []
    return [
        {
            "severity": "fail",
            "category": "ua_version_drift",
            "message": "Reported browser versions drift across baseline and public checkers.",
            "evidence": {
                "baseline_versions": baseline_versions,
                "extracted_versions": extracted_versions,
            },
        }
    ]


def _webdriver_findings(
    consensus: dict[str, object],
    sannysoft: dict[str, object],
    creepjs: dict[str, object],
) -> list[dict[str, object]]:
    evidence = (
        ["baseline.navigator.webdriver=true"]
        if bool(consensus.get("webdriver"))
        else []
    )
    evidence.extend(
        _string_list(_object_dict(sannysoft.get("extracted")).get("webdriver_hits"))
    )
    keyword_hits = _object_dict(
        _object_dict(creepjs.get("extracted")).get("keyword_hits")
    )
    evidence.extend(_string_list(keyword_hits.get("webdriver")))
    evidence = [value for value in evidence if _looks_like_truthy_risk(value)]
    if not evidence:
        return []
    return [
        {
            "severity": "fail",
            "category": "webdriver_exposure",
            "message": "Public checks still see webdriver or automation signals.",
            "evidence": evidence[:10],
        }
    ]


def _headless_findings(creepjs: dict[str, object]) -> list[dict[str, object]]:
    extracted = _object_dict(creepjs.get("extracted"))
    evidence = _string_list(extracted.get("headless_hits"))
    evidence.extend(
        _string_list(_object_dict(extracted.get("keyword_hits")).get("headless"))
    )
    filtered: list[str] = []
    for value in evidence:
        if " like headless" in _normalize_space(value).lower():
            percent = _percent_value(value)
            if percent is None or percent < 10:
                continue
        if _looks_like_truthy_risk(value):
            filtered.append(value)
    if not filtered:
        return []
    return [
        {
            "severity": "fail",
            "category": "headless_leakage",
            "message": "Headless or stealth leakage is visible in public checks.",
            "evidence": filtered[:10],
        }
    ]


def _webrtc_findings(consensus: dict[str, object]) -> list[dict[str, object]]:
    public_ips: list[str] = []
    private_ips: list[str] = []
    for value in _string_list(consensus.get("webrtc_ips")):
        if not _normalize_space(value):
            continue
        try:
            parsed = ip_address(value)
        except ValueError:
            continue
        if parsed.is_loopback:
            continue
        (private_ips if parsed.is_private else public_ips).append(value)
    if public_ips:
        return [
            {
                "severity": "fail",
                "category": "webrtc_leakage",
                "message": "WebRTC exposed public IPs from the page context.",
                "evidence": public_ips,
            }
        ]
    if private_ips:
        return [
            {
                "severity": "warn",
                "category": "webrtc_private_ip_visibility",
                "message": "WebRTC exposed private-network IPs from the page context.",
                "evidence": private_ips,
            }
        ]
    return []


def _baseline_drift_findings(
    metadata: dict[str, object],
    consensus: dict[str, object],
    drift: dict[str, object],
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    if "screen" in drift or "viewport" in drift:
        findings.append(
            {
                "severity": "fail",
                "category": "screen_viewport_drift",
                "message": "Screen or viewport values changed across the three checker sites.",
                "evidence": {
                    "screen": drift.get("screen"),
                    "viewport": drift.get("viewport"),
                },
            }
        )
    automation_globals = [
        value
        for value in _string_list(consensus.get("automation_globals"))
        if value != "chrome.runtime.typeof=object"
    ]
    if automation_globals:
        findings.append(
            {
                "severity": "fail",
                "category": "automation_globals_exposure",
                "message": "Automation framework globals are visible in the page context.",
                "evidence": automation_globals[:10],
            }
        )
    iframe_leak = _object_dict(consensus.get("iframe_leak"))
    if iframe_leak and iframe_leak.get("content_window_array_leak") is True:
        findings.append(
            {
                "severity": "fail",
                "category": "iframe_content_window_leak",
                "message": "Iframe contentWindow array leak detected (automation marker).",
                "evidence": iframe_leak,
            }
        )
    for key, category, message in (
        (
            "canvas",
            "canvas_fingerprint_drift",
            "Canvas fingerprint values differ across probe sites.",
        ),
        (
            "audio",
            "audio_fingerprint_drift",
            "AudioContext fingerprint values differ across probe sites.",
        ),
    ):
        if key in drift:
            findings.append(
                {
                    "severity": "warn",
                    "category": category,
                    "message": message,
                    "evidence": drift.get(key),
                }
            )
    behavioral = _object_dict(consensus.get("behavioral_smoke"))
    if behavioral and (
        behavioral.get("mouse_isTrusted") is False
        or behavioral.get("click_isTrusted") is False
    ):
        findings.append(
            {
                "severity": "warn",
                "category": "synthetic_event_detection",
                "message": "Playwright input did not produce trusted DOM events.",
                "evidence": behavioral,
            }
        )
    if str(metadata.get("browser_engine") or "").strip().lower() == "chromium":
        findings.append(
            {
                "severity": "info",
                "category": "chromium_ja3_limitation",
                "message": "Chromium engine still uses a Playwright Chromium TLS fingerprint; use real_chrome for native Chrome JA3 parity.",
                "evidence": {"browser_engine": metadata.get("browser_engine")},
            }
        )
    return findings


def _site_identity_findings(sites: dict[str, object]) -> list[dict[str, object]]:
    site_ips: list[str] = []
    site_countries: list[str] = []
    for payload in sites.values():
        extracted = _object_dict(_object_dict(payload).get("extracted"))
        site_ips.extend(_string_list(extracted.get("ip_values")))
        site_countries.extend(_string_list(extracted.get("country_values")))
    public_ips: list[str] = []
    for value in site_ips:
        try:
            parsed = ip_address(value)
        except ValueError:
            continue
        if not (parsed.is_loopback or parsed.is_private or parsed.is_unspecified):
            public_ips.append(value)
    findings: list[dict[str, object]] = []
    if len(set(public_ips)) > 1:
        findings.append(
            {
                "severity": "warn",
                "category": "cross_site_ip_drift",
                "message": "Different public IPs were reported inside the same fingerprint run.",
                "evidence": sorted(set(public_ips)),
            }
        )
    country_codes = {
        code for value in site_countries if (code := _country_code_from_value(value))
    }
    if len(country_codes) > 1:
        findings.append(
            {
                "severity": "warn",
                "category": "cross_site_country_drift",
                "message": "Different countries were reported inside the same fingerprint run.",
                "evidence": _dedupe(site_countries),
            }
        )
    return findings


def _target_findings(
    consensus: dict[str, object], target_diagnostics: list[object]
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    failing = {
        "target_precontent_block",
        "browser_geo_identity_mismatch",
        "browser_session_or_fingerprint_block",
    }
    warning = {"transport_only_block", "target_diagnostic_inconclusive"}
    for diagnostic in target_diagnostics:
        payload = _object_dict(diagnostic)
        root_cause = _target_root_cause(consensus=consensus, diagnostic=payload)
        category = str(root_cause.get("category") or "")
        severity = (
            "fail" if category in failing else "warn" if category in warning else "info"
        )
        findings.append(
            {
                "severity": severity,
                "category": category,
                "message": f"{payload.get('url') or 'target'!s}: {root_cause.get('message')}",
                "evidence": root_cause.get("evidence"),
            }
        )
    return findings


def build_findings(report: dict[str, object]) -> list[dict[str, object]]:
    metadata = _object_dict(report.get("metadata"))
    baseline = _object_dict(report.get("baseline"))
    consensus = _object_dict(baseline.get("consensus"))
    drift = _object_dict(baseline.get("drift"))
    sites = _object_dict(report.get("sites"))
    target_diagnostics = _object_list(report.get("target_diagnostics"))
    pixelscan = _object_dict(sites.get("pixelscan"))
    sannysoft = _object_dict(sites.get("sannysoft"))
    creepjs = _object_dict(sites.get("creepjs"))

    findings = _probe_status_findings(sites)
    for group in (
        _geo_findings(consensus, pixelscan, target_diagnostics),
        _version_findings(consensus, sites),
        _webdriver_findings(consensus, sannysoft, creepjs),
        _headless_findings(creepjs),
        _webrtc_findings(consensus),
        _baseline_drift_findings(metadata, consensus, drift),
        _site_identity_findings(sites),
        _target_findings(consensus, target_diagnostics),
    ):
        findings.extend(group)
    if not findings:
        findings.append(
            {
                "severity": "info",
                "category": "no_risky_drift_detected",
                "message": "No risky fingerprint drift was detected by current rules.",
                "evidence": [],
            }
        )
    return findings
