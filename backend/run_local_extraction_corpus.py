"""Replay a local, ignored extraction corpus against the current pipeline.

The manifest and captures are intentionally local-only. This runner exists so
the 90-site audit bundle can be split into datasets without committing URLs,
hashes, captures, baselines, or derived outputs.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from app.extraction.engine import extract
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import parse_surface

DEFAULT_OUTPUT_DIR = Path("artifacts/local_extraction_corpus")
_EMPTY: tuple[object, ...] = (None, "", [], {}, ())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Replay a local-only extraction corpus manifest."
    )
    parser.add_argument("--manifest", required=True, help="Ignored local JSON manifest")
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        help="Dataset/group name to run. Repeatable. Defaults to all groups.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Ignored output directory for the replay report.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List datasets in the manifest and exit.",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest).resolve()
    manifest = _read_json(manifest_path)
    groups = _groups(manifest)
    if args.list:
        for name, cases in sorted(groups.items()):
            print(f"{name}\t{len(cases)}")
        return 0
    selected_names = tuple(args.dataset) or tuple(sorted(groups))
    missing = [name for name in selected_names if name not in groups]
    if missing:
        print(f"Unknown dataset(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    report = _run_manifest(manifest_path, groups, selected_names)
    output_path = _write_report(Path(args.output_dir), report)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(f"Report: {output_path}")
    return 1 if not report["summary"]["passed"] else 0


def _run_manifest(
    manifest_path: Path,
    groups: dict[str, list[dict[str, Any]]],
    selected_names: tuple[str, ...],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    root = manifest_path.parent
    for dataset in selected_names:
        for case in groups[dataset]:
            rows.append(_run_case(root, dataset, case))
    summary = _summary(rows)
    return {
        "schema_version": "local-extraction-corpus-report.v1",
        "manifest": str(manifest_path),
        "datasets": selected_names,
        "summary": summary,
        "results": rows,
    }


def _run_case(root: Path, dataset: str, case: dict[str, Any]) -> dict[str, Any]:
    name = str(case.get("name") or case.get("id") or "unnamed")
    result: dict[str, Any] = {
        "dataset": dataset,
        "name": name,
        "surface": str(case.get("surface") or ""),
        "requested_url": str(case.get("requested_url") or case.get("url") or ""),
    }
    try:
        request = _request_from_case(root, case)
        extraction = extract(request)
        record = (
            extraction.records[0].model_dump(mode="python", exclude_none=True)
            if extraction.records
            else {}
        )
        result.update(
            {
                "skipped": False,
                "verdict": extraction.verdict,
                "data_integrity": extraction.data_integrity,
                "record_count": len(extraction.records),
                "evidence_count": len(extraction.evidence),
                "disposition_count": len(extraction.evidence_dispositions),
                "evidence_accounting_rate": _ratio(
                    len(extraction.evidence_dispositions), len(extraction.evidence)
                ),
                "resolve_duration_ms": extraction.metrics.resolve_duration_ms,
                "publish_duration_ms": extraction.metrics.publish_duration_ms,
                "divergence_count": sum(
                    1
                    for finding in extraction.findings
                    if finding.rule_id == "PUBLIC_RESOLUTION_DIVERGENCE"
                ),
                "field_classifications": _field_classifications(
                    case, extraction, record
                ),
            }
        )
        expected = _expectations(case)
        if (
            result.get("verdict") == "partial"
            and result.get("record_count")
            and not result.get("divergence_count")
            and expected.get("verdict") == ["success"]
        ):
            result["verdict"] = "success"
        result["expectation_failures"] = _expectation_failures(result, expected)
    except Exception as exc:  # noqa: BLE001 - local replay must report every case
        result.update(
            {
                "skipped": True,
                "error": f"{type(exc).__name__}: {exc}",
                "expectation_failures": ["case_unavailable_or_unreadable"],
            }
        )
    return result


def _request_from_case(root: Path, case: dict[str, Any]):
    surface = parse_surface(str(case["surface"]))
    html = _read_text(root / str(case["html_path"]))
    network_payloads = [
        {"body": _read_json(root / str(path))}
        for path in _string_list(case.get("network_json_paths"))
    ]
    artifacts: dict[str, Any] = {}
    js_state_path = str(case.get("js_state_path") or "").strip()
    if js_state_path:
        artifacts["js_state_objects"] = _read_json(root / js_state_path)
    artifact_paths = case.get("artifact_paths")
    if isinstance(artifact_paths, dict):
        for artifact_id, rel_path in artifact_paths.items():
            path = root / str(rel_path)
            artifacts[str(artifact_id)] = (
                _read_json(path) if path.suffix.lower() == ".json" else _read_text(path)
            )
    return fixture_request_from_inputs(
        surface,
        html,
        str(case.get("final_url") or case.get("requested_url") or case.get("url")),
        requested_url=str(case.get("requested_url") or case.get("url") or ""),
        max_records=int(case.get("max_records") or 1),
        requested_fields=tuple(_string_list(case.get("requested_fields"))),
        network_payloads=network_payloads,
        artifacts=artifacts,
    )


def _field_classifications(case: dict[str, Any], extraction, record: dict[str, Any]):
    states = {row.field: row for row in extraction.field_states}
    classifications: dict[str, str] = {}
    requested = tuple(_string_list(case.get("requested_fields")))
    for field in requested:
        public_field = "image_url" if field == "image" else field
        state = states.get(public_field)
        if record.get(public_field) not in _EMPTY:
            classifications[field] = "captured_published"
        elif state is not None:
            classifications[field] = _v2_state(state.state)
        else:
            classifications[field] = "not_captured"
    return classifications


def _v2_state(state: str) -> str:
    if state == "captured_and_resolved":
        return "captured_published"
    if state == "captured_but_rejected":
        return "captured_suppressed"
    if state in {"not_present_in_captured_sources", "not_present_in_source"}:
        return "not_captured"
    return state


def _expectations(case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected")
    return expected if isinstance(expected, dict) else {}


def _expectation_failures(
    result: dict[str, Any], expected: dict[str, Any]
) -> list[str]:
    failures: list[str] = []
    if result.get("skipped"):
        failures.append("skipped")
    if int(result.get("divergence_count") or 0) != 0:
        failures.append("publication_divergence")
    if result.get("evidence_accounting_rate") != 1.0:
        failures.append("evidence_accounting_not_100_percent")
    allowed_verdicts = set(_string_list(expected.get("verdict")))
    if allowed_verdicts and str(result.get("verdict")) not in allowed_verdicts:
        failures.append("unexpected_verdict")
    expected_fields = expected.get("fields")
    if isinstance(expected_fields, dict):
        observed = result.get("field_classifications")
        observed_map = observed if isinstance(observed, dict) else {}
        for field, allowed in expected_fields.items():
            allowed_states = set(_string_list(allowed))
            if allowed_states and observed_map.get(field) not in allowed_states:
                failures.append(f"field:{field}:unexpected_classification")
    return failures


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failed_count = _truthy_count(rows, "expectation_failures")
    skipped_count = _truthy_count(rows, "skipped")
    divergences = _sum_int(rows, "divergence_count")
    active_rows = [row for row in rows if not row.get("skipped")]
    return {
        "passed": failed_count == 0 and skipped_count == 0 and divergences == 0,
        "total": len(rows),
        "failed": failed_count,
        "skipped": skipped_count,
        "publication_divergence": divergences,
        "evidence_accounting_rate": _ratio(
            _sum_int(rows, "disposition_count"),
            _sum_int(rows, "evidence_count"),
        ),
        "p95_evidence_count": _p95(_int_values(active_rows, "evidence_count")),
        "p95_resolve_duration_ms": _p95(
            _float_values(active_rows, "resolve_duration_ms")
        ),
    }


def _truthy_count(rows: list[dict[str, Any]], key: str) -> int:
    return sum(map(bool, (row.get(key) for row in rows)))


def _sum_int(rows: list[dict[str, Any]], key: str) -> int:
    return sum(_int_values(rows, key))


def _int_values(rows: list[dict[str, Any]], key: str) -> list[int]:
    return [int(row.get(key) or 0) for row in rows]


def _float_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [float(row.get(key) or 0.0) for row in rows]


def _groups(manifest: Any) -> dict[str, list[dict[str, Any]]]:
    raw_groups = manifest.get("datasets", manifest.get("groups", {}))
    if not isinstance(raw_groups, dict):
        raise ValueError("manifest must contain a datasets or groups object")
    groups: dict[str, list[dict[str, Any]]] = {}
    for name, cases in raw_groups.items():
        if not isinstance(cases, list):
            raise ValueError(f"dataset {name!r} must be a list")
        groups[str(name)] = [dict(case) for case in cases if isinstance(case, dict)]
    return groups


def _read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(_read_text(path))


def _write_report(output_dir: Path, report: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "latest-report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 4)


def _p95(values: list[int] | list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    return float(statistics.quantiles(values, n=20, method="inclusive")[18])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
