from __future__ import annotations

import re
from ipaddress import ip_address
from pathlib import Path

from app.core.config.browser_surface_probe import (
    BROWSER_SURFACE_PROBE_CREEPJS_LABELS,
    BROWSER_SURFACE_PROBE_FONT_TEST_STRINGS,
    BROWSER_SURFACE_PROBE_HIGH_ENTROPY_HINTS,
    BROWSER_SURFACE_PROBE_KEYWORD_GROUPS,
    BROWSER_SURFACE_PROBE_NEIGHBOR_LINE_WINDOW,
    BROWSER_SURFACE_PROBE_PIXELSCAN_LABELS,
    BROWSER_SURFACE_PROBE_SANNYSOFT_LABELS,
    BROWSER_SURFACE_PROBE_TABLE_ROW_LIMIT,
    BROWSER_SURFACE_PROBE_VISIBLE_TEXT_LIMIT,
    BROWSER_SURFACE_PROBE_WEBRTC_GATHER_TIMEOUT_MS,
)
from browser_surface_probe.value_coercion import (
    dedupe as _dedupe,
    extract_versions as _extract_versions,
    int_list as _int_list,
    looks_like_truthy_risk as _looks_like_truthy_risk,
    normalize_key as _normalize_key,
    normalize_space as _normalize_space,
    object_dict as _object_dict,
    object_list as _object_list,
    string_list as _string_list,
)

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_BASELINE_PROBE_SCRIPT_PATH = Path(__file__).resolve().with_name("baseline_probe.js")

__all__ = [
    "_collect_baseline",
    "_collect_behavioral_smoke",
    "_collect_page_snapshot",
    "_extract_creepjs",
    "_extract_generic_site",
    "_extract_pixelscan",
    "_sannysoft_signal_rows",
    "load_baseline_probe_script",
]


def _extract_ip_values(values: list[str]) -> list[str]:
    ips: list[str] = []
    for value in values:
        for match in _IP_RE.findall(str(value or "")):
            try:
                parsed = ip_address(match)
            except ValueError:
                continue
            if parsed.version == 4:
                ips.append(match)
    return sorted(set(ips))


def _looks_like_networkish_ipv4(value: str) -> bool:
    octets = str(value or "").split(".")
    if len(octets) != 4:
        return False
    try:
        numbers = [int(item) for item in octets]
    except ValueError:
        return False
    if any(number < 0 or number > 255 for number in numbers):
        return True
    if numbers[1:] in ([0, 0, 0], [255, 255, 255]):
        return True
    if numbers[2:] in ([0, 0], [255, 255]):
        return True
    if numbers[3] in {0, 255}:
        return True
    return False


def _clean_ip_values(
    values: list[str], *, known_versions: list[int] | None = None
) -> list[str]:
    version_set = {int(value) for value in (known_versions or [])}
    cleaned: list[str] = []
    for value in values:
        if _looks_like_networkish_ipv4(value):
            continue
        octets = str(value).split(".")
        if len(octets) == 4 and octets[1:] == ["0", "0", "0"]:
            try:
                if int(octets[0]) in version_set:
                    continue
            except ValueError:
                # Non-numeric leading octet: keep value as-is.
                pass
        cleaned.append(value)
    return sorted(set(cleaned))


def _normalize_snapshot_row(row: object) -> dict[str, object] | None:
    if not isinstance(row, dict):
        return None
    raw_cells = row.get("cells")
    cells = (
        [
            _normalize_space(value)
            for value in list(raw_cells)
            if _normalize_space(value)
        ]
        if isinstance(raw_cells, list)
        else []
    )
    label = _normalize_space(row.get("label")) or (cells[0] if cells else "")
    value = _normalize_space(row.get("value")) or " | ".join(cells[1:])
    if not (label or value or cells):
        return None
    return {
        "cells": cells,
        "label": label,
        "value": value,
    }


def _dedupe_snapshot_rows(rows: list[object]) -> tuple[list[dict[str, object]], int]:
    normalized_rows = [
        normalized
        for row in rows
        if (normalized := _normalize_snapshot_row(row)) is not None
    ]
    seen: set[tuple[tuple[str, ...], str, str]] = set()
    deduped: list[dict[str, object]] = []
    for row in normalized_rows:
        marker = (
            tuple(str(value).casefold() for value in _object_list(row.get("cells"))),
            _normalize_space(row.get("label")).casefold(),
            _normalize_space(row.get("value")).casefold(),
        )
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(row)
    return deduped, len(normalized_rows)


def _flatten_signal_values(payload: object) -> list[str]:
    if isinstance(payload, str):
        normalized = _normalize_space(payload)
        return [normalized] if normalized else []
    if isinstance(payload, dict):
        flattened: list[str] = []
        for value in payload.values():
            flattened.extend(_flatten_signal_values(value))
        return flattened
    if isinstance(payload, list):
        flattened = []
        for value in payload:
            flattened.extend(_flatten_signal_values(value))
        return flattened
    return []


def _label_alias_set(label_map: dict[str, tuple[str, ...]]) -> set[str]:
    aliases: set[str] = set()
    for values in label_map.values():
        aliases.update(_normalize_key(value) for value in values)
    return aliases


def _extract_labeled_values(
    lines: list[str],
    label_map: dict[str, tuple[str, ...]],
) -> dict[str, list[str]]:
    normalized_lines = [
        _normalize_space(value) for value in lines if _normalize_space(value)
    ]
    aliases = _label_alias_set(label_map)
    extracted: dict[str, list[str]] = {}
    for key, raw_aliases in label_map.items():
        values: list[str] = []
        aliases_for_key = [_normalize_key(value) for value in raw_aliases]
        for index, line in enumerate(normalized_lines):
            normalized_line = _normalize_key(line)
            if not any(alias and alias in normalized_line for alias in aliases_for_key):
                continue
            if ":" in line:
                _, raw_value = line.split(":", 1)
                normalized_value = _normalize_space(raw_value)
                if normalized_value:
                    values.append(normalized_value)
                    continue
            upper_bound = min(
                len(normalized_lines),
                index + 1 + int(BROWSER_SURFACE_PROBE_NEIGHBOR_LINE_WINDOW),
            )
            for candidate in normalized_lines[index + 1 : upper_bound]:
                candidate_key = _normalize_key(candidate)
                if not candidate_key or candidate_key in aliases:
                    continue
                values.append(candidate)
                break
        if values:
            extracted[key] = _dedupe(values)
    return extracted


def _extract_keyword_hits(lines: list[str], keyword_group: str) -> list[str]:
    keywords = BROWSER_SURFACE_PROBE_KEYWORD_GROUPS.get(keyword_group, ())
    hits = [
        _normalize_space(line)
        for line in lines
        if any(keyword in _normalize_space(line).lower() for keyword in keywords)
    ]
    return _dedupe(hits)


async def _collect_page_snapshot(page) -> dict[str, object]:
    raw_snapshot = await page.evaluate(
        """(limits) => {
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
            const rawBodyText = document.body ? (document.body.innerText || '') : '';
            const lines = rawBodyText
                .split(/\\n+/)
                .map((line) => normalize(line))
                .filter(Boolean)
                .slice(0, limits.textLineLimit);
            const rows = Array.from(document.querySelectorAll('tr'))
                .map((row) => {
                    const cells = Array.from(row.querySelectorAll('th, td'))
                        .map((cell) => normalize(cell.innerText || cell.textContent || ''))
                        .filter(Boolean);
                    if (!cells.length) {
                        return null;
                    }
                    return {
                        cells,
                        label: cells[0] || '',
                        value: cells.slice(1).join(' | '),
                    };
                })
                .filter(Boolean)
                .slice(0, limits.tableRowLimit);
            return {
                body_text: normalize(rawBodyText),
                lines,
                line_count: lines.length,
                rows,
                has_creep_object: typeof window.Creep !== 'undefined',
                has_fingerprint_object: typeof window.Fingerprint !== 'undefined',
            };
        }""",
        {
            "textLineLimit": int(BROWSER_SURFACE_PROBE_VISIBLE_TEXT_LIMIT),
            "tableRowLimit": int(BROWSER_SURFACE_PROBE_TABLE_ROW_LIMIT),
        },
    )
    snapshot_payload = dict(raw_snapshot) if isinstance(raw_snapshot, dict) else {}
    raw_lines = [
        _normalize_space(value)
        for value in list(snapshot_payload.get("lines") or [])
        if _normalize_space(value)
    ]
    deduped_lines = _dedupe(raw_lines)
    deduped_rows, raw_row_count = _dedupe_snapshot_rows(
        list(snapshot_payload.get("rows") or [])
    )
    return {
        "body_text": _normalize_space(snapshot_payload.get("body_text")),
        "lines": deduped_lines,
        "line_count": len(deduped_lines),
        "line_count_raw": len(raw_lines),
        "rows": deduped_rows,
        "row_count": len(deduped_rows),
        "row_count_raw": raw_row_count,
        "has_creep_object": bool(snapshot_payload.get("has_creep_object")),
        "has_fingerprint_object": bool(snapshot_payload.get("has_fingerprint_object")),
    }


async def _collect_behavioral_smoke(page) -> dict[str, object]:
    try:
        setup = await page.evaluate(
            """() => {
                const body = document.body;
                if (!body) {
                    return { ready: false, mouse_isTrusted: null, click_isTrusted: null };
                }
                const state = globalThis.__crawlerProbeBehavioralSmoke = {
                    mouse_isTrusted: null,
                    click_isTrusted: null,
                };
                let target = document.getElementById('__crawler_probe_mouse_target__');
                if (!target) {
                    target = document.createElement('div');
                    target.id = '__crawler_probe_mouse_target__';
                    target.setAttribute('aria-hidden', 'true');
                    target.style.cssText = [
                        'position:fixed',
                        'left:8px',
                        'top:8px',
                        'width:32px',
                        'height:32px',
                        'opacity:0.001',
                        'background:#000',
                        'pointer-events:auto',
                        'z-index:2147483647',
                    ].join(';');
                    body.appendChild(target);
                }
                target.addEventListener('mousemove', (event) => {
                    state.mouse_isTrusted = event.isTrusted;
                }, { once: true });
                target.addEventListener('click', (event) => {
                    state.click_isTrusted = event.isTrusted;
                }, { once: true });
                return { ready: true, x: 24, y: 24 };
            }"""
        )
    except Exception:  # noqa: BLE001 - browser evaluation is best-effort diagnostics
        return {"mouse_isTrusted": None, "click_isTrusted": None}
    if not _object_dict(setup).get("ready"):
        return {
            "mouse_isTrusted": _object_dict(setup).get("mouse_isTrusted"),
            "click_isTrusted": _object_dict(setup).get("click_isTrusted"),
        }
    try:
        await page.mouse.move(24, 24, steps=6)
        await page.wait_for_timeout(50)
        await page.mouse.click(24, 24, delay=50)
        await page.wait_for_timeout(50)
    except Exception:  # noqa: BLE001,S110  # nosec B110 - best-effort trust probe
        # Trust-probe input is best-effort; evaluation below reports actual state.
        pass
    try:
        return _object_dict(
            await page.evaluate(
                """() => {
                    const state = globalThis.__crawlerProbeBehavioralSmoke || {};
                    const target = document.getElementById('__crawler_probe_mouse_target__');
                    if (target && target.parentNode) {
                        target.parentNode.removeChild(target);
                    }
                    try {
                        delete globalThis.__crawlerProbeBehavioralSmoke;
                    } catch (_error) {}
                    return {
                        mouse_isTrusted: state.mouse_isTrusted ?? null,
                        click_isTrusted: state.click_isTrusted ?? null,
                    };
                }"""
            )
        )
    except Exception:  # noqa: BLE001 - browser evaluation is best-effort diagnostics
        return {"mouse_isTrusted": None, "click_isTrusted": None}


async def _collect_baseline(
    page,
    *,
    behavioral_smoke: dict[str, object] | None = None,
) -> dict[str, object]:
    baseline_probe_script = load_baseline_probe_script()
    return await page.evaluate(
        f"""async (input) => {{
{baseline_probe_script}
            return await globalThis.__crawlerProbeCollectBaseline(input);
        }}""",
        {
            "behavioralSmoke": dict(behavioral_smoke or {}),
            "highEntropyHints": list(BROWSER_SURFACE_PROBE_HIGH_ENTROPY_HINTS),
            "webrtcTimeoutMs": int(BROWSER_SURFACE_PROBE_WEBRTC_GATHER_TIMEOUT_MS),
            "fontTestStrings": list(BROWSER_SURFACE_PROBE_FONT_TEST_STRINGS),
        },
    )


def load_baseline_probe_script() -> str:
    return _BASELINE_PROBE_SCRIPT_PATH.read_text(encoding="utf-8")


def _sannysoft_signal_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    categorized: dict[str, list[dict[str, str]]] = {}
    failed_rows: list[dict[str, str]] = []
    for row in rows:
        label = _normalize_space(row.get("label"))
        value = _normalize_space(row.get("value"))
        row_payload = {"label": label, "value": value}
        normalized_label = _normalize_key(label)
        for key, aliases in BROWSER_SURFACE_PROBE_SANNYSOFT_LABELS.items():
            if any(_normalize_key(alias) in normalized_label for alias in aliases):
                categorized.setdefault(key, []).append(row_payload)
        if _looks_like_truthy_risk(value):
            failed_rows.append(row_payload)
    signal_values = _flatten_signal_values(categorized) + _flatten_signal_values(
        failed_rows
    )
    return {
        "matched_rows": categorized,
        "failed_rows": failed_rows,
        "signal_versions": _extract_versions(signal_values),
        "webdriver_hits": _flatten_signal_values(categorized.get("webdriver")),
        "headless_hits": [],
        "webrtc_hits": [],
        "screen_hits": _flatten_signal_values(categorized.get("screen")),
        "language_hits": _flatten_signal_values(categorized.get("languages")),
        "webgl_hits": _flatten_signal_values(categorized.get("webgl")),
    }


def _generic_line_signals(
    *,
    lines: list[str],
    label_map: dict[str, tuple[str, ...]],
) -> dict[str, object]:
    labeled = _extract_labeled_values(lines, label_map)
    all_values = _flatten_signal_values(labeled)
    return {
        "labeled_values": labeled,
        "keyword_hits": {
            key: _extract_keyword_hits(lines, key)
            for key in BROWSER_SURFACE_PROBE_KEYWORD_GROUPS
        },
        "signal_versions": _extract_versions(all_values),
        "ip_values": [],
    }


def _extract_pixelscan(snapshot: dict[str, object]) -> dict[str, object]:
    lines = [str(value) for value in _object_list(snapshot.get("lines"))]
    payload = _generic_line_signals(
        lines=lines, label_map=BROWSER_SURFACE_PROBE_PIXELSCAN_LABELS
    )
    labeled_values = _object_dict(payload.get("labeled_values"))
    payload["country_values"] = _flatten_signal_values(labeled_values.get("country"))
    payload["ip_values"] = _clean_ip_values(
        _extract_ip_values(_flatten_signal_values(labeled_values.get("ip"))),
        known_versions=_int_list(payload.get("signal_versions")),
    )
    payload["timezone_values"] = _flatten_signal_values(
        {
            "js_timezone": labeled_values.get("js_timezone"),
            "ip_time": labeled_values.get("ip_time"),
        }
    )
    payload["proxy_values"] = _flatten_signal_values(
        labeled_values.get("proxy_verdict")
    )
    payload["language_values"] = _flatten_signal_values(
        labeled_values.get("language_headers")
    )
    payload["screen_values"] = _flatten_signal_values(labeled_values.get("screen_size"))
    payload["webgl_values"] = _flatten_signal_values(labeled_values.get("webgl"))
    return payload


def _extract_creepjs(snapshot: dict[str, object]) -> dict[str, object]:
    lines = [str(value) for value in _object_list(snapshot.get("lines"))]
    payload = _generic_line_signals(
        lines=lines, label_map=BROWSER_SURFACE_PROBE_CREEPJS_LABELS
    )
    labeled_values = _object_dict(payload.get("labeled_values"))
    payload["fp_id_values"] = _flatten_signal_values(labeled_values.get("fp_id"))
    payload["fuzzy_fp_id_values"] = _flatten_signal_values(
        labeled_values.get("fuzzy_fp_id")
    )
    keyword_hits = _object_dict(payload.get("keyword_hits"))
    payload["headless_hits"] = _object_list(keyword_hits.get("headless"))
    payload["webrtc_hits"] = _object_list(keyword_hits.get("webrtc"))
    payload["timezone_hits"] = _object_list(keyword_hits.get("timezone"))
    payload["screen_hits"] = _object_list(keyword_hits.get("screen"))
    payload["ip_values"] = _clean_ip_values(
        _extract_ip_values(_string_list(payload.get("webrtc_hits"))),
        known_versions=_int_list(payload.get("signal_versions")),
    )
    return payload


def _extract_generic_site(snapshot: dict[str, object]) -> dict[str, object]:
    lines = [str(value) for value in _object_list(snapshot.get("lines"))]
    payload = _generic_line_signals(lines=lines, label_map={})
    payload["ip_values"] = _clean_ip_values(
        _extract_ip_values(lines),
        known_versions=_int_list(payload.get("signal_versions")),
    )
    return payload
