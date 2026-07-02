"""Freeze a deterministic baseline over a completed offline extraction run.

Phase 0 / Slice 0.1. This reduces a run's frozen artifacts
(``results/<id>/record.json`` + ``diagnose.json`` and the run-level
``report.json``) to a small, stable, versioned summary. That summary is the
regression reference every later phase must beat and must never silently
regress.

The module only *reads* frozen JSON. It performs no extraction, imports no
extraction runtime, and carries no site-specific literals. All aggregation is
order-independent (counters / percentiles) and serialized with sorted keys, so
the output is byte-stable across machines and Python runs.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

BASELINE_SCHEMA_VERSION = "extraction_baseline.v1"

# Deterministic extraction runs entirely offline with no model calls, so there
# is no per-record cost signal to freeze. Recorded explicitly (rather than
# omitted) so Phase 5/7 can populate it when LLM fallback/repair land.
_COST_SIGNALS: dict[str, Any] = {
    "available": False,
    "reason": "deterministic extraction has no LLM cost in the hot path",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _round(value: float) -> float:
    return round(float(value), 6)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = int(round(q * (len(ordered) - 1)))
    rank = max(0, min(len(ordered) - 1, rank))
    return _round(ordered[rank])


def _iter_result_dirs(run_dir: Path) -> list[Path]:
    results = run_dir / "results"
    if not results.is_dir():
        return []
    dirs = [
        child
        for child in results.iterdir()
        if child.is_dir() and (child / "diagnose.json").exists()
    ]
    return sorted(dirs, key=lambda child: child.name)


def _load_results(run_dir: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for result_dir in _iter_result_dirs(run_dir):
        diagnose = _load_json(result_dir / "diagnose.json")
        record_path = result_dir / "record.json"
        record = (
            _load_json(record_path)
            if record_path.exists()
            else {"record_count": 0, "records": []}
        )
        pairs.append((record, diagnose))
    return pairs


def _summarize_outcomes(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    verdicts: Counter[str] = Counter()
    integrity: Counter[str] = Counter()
    completeness: list[float] = []
    total_records = 0
    urls_with_records = 0
    for record, diagnose in pairs:
        verdicts[str(diagnose.get("verdict", "unknown"))] += 1
        integrity[str(diagnose.get("data_integrity", "unknown"))] += 1
        score = diagnose.get("metrics", {}).get("completeness_score")
        if score is not None:
            completeness.append(float(score))
        count = int(record.get("record_count", 0))
        total_records += count
        urls_with_records += 1 if count > 0 else 0
    return {
        "result_count": len(pairs),
        "total_records": total_records,
        "urls_with_records": urls_with_records,
        "urls_zero_records": len(pairs) - urls_with_records,
        "verdict_distribution": dict(sorted(verdicts.items())),
        "data_integrity_distribution": dict(sorted(integrity.items())),
        "completeness_score": {
            "mean": _round(sum(completeness) / len(completeness))
            if completeness
            else None,
            "min": _round(min(completeness)) if completeness else None,
            "p50": _percentile(completeness, 0.5),
            "p95": _percentile(completeness, 0.95),
        },
    }


def _summarize_latency(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    resolve: list[float] = []
    publish: list[float] = []
    total: list[float] = []
    for _record, diagnose in pairs:
        metrics = diagnose.get("metrics", {})
        r = metrics.get("resolve_duration_ms")
        p = metrics.get("publish_duration_ms")
        if r is not None:
            resolve.append(float(r))
        if p is not None:
            publish.append(float(p))
        if r is not None and p is not None:
            total.append(float(r) + float(p))
    return {
        "resolve_ms": {
            "p50": _percentile(resolve, 0.5),
            "p95": _percentile(resolve, 0.95),
        },
        "publish_ms": {
            "p50": _percentile(publish, 0.5),
            "p95": _percentile(publish, 0.95),
        },
        "total_ms": {"p50": _percentile(total, 0.5), "p95": _percentile(total, 0.95)},
    }


def _summarize_fields(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    status_by_field: dict[str, Counter[str]] = {}
    reason_codes: Counter[str] = Counter()
    requested: Counter[str] = Counter()
    published: Counter[str] = Counter()
    for _record, diagnose in pairs:
        for field in diagnose.get("fields", []):
            name = str(field.get("field", "unknown"))
            status = str(field.get("status", "unknown"))
            status_by_field.setdefault(name, Counter())[status] += 1
            for code in field.get("reason_codes", []):
                reason_codes[str(code)] += 1
            if status != "not_requested":
                requested[name] += 1
                if status == "captured_published":
                    published[name] += 1
    return {
        "field_status_counts": {
            name: dict(sorted(counts.items()))
            for name, counts in sorted(status_by_field.items())
        },
        "contract_field_publish_rate": {
            name: _round(published[name] / requested[name])
            for name in sorted(requested)
        },
        "reason_code_frequency": dict(sorted(reason_codes.items())),
    }


def _summarize_variants(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    distribution: Counter[str] = Counter()
    total = 0
    with_variants = 0
    with_dropped = 0
    for _record, diagnose in pairs:
        count = int(diagnose.get("metrics", {}).get("variant_count", 0))
        distribution[str(count)] += 1
        total += count
        with_variants += 1 if count > 0 else 0
        if diagnose.get("variants", {}).get("dropped"):
            with_dropped += 1
    return {
        "total_variants": total,
        "urls_with_variants": with_variants,
        "urls_with_dropped_variants": with_dropped,
        "variant_count_distribution": dict(sorted(distribution.items())),
    }


def _summarize_findings(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    by_rule: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    blocking = 0
    for _record, diagnose in pairs:
        for finding in diagnose.get("findings", []):
            by_rule[str(finding.get("rule_id", "unknown"))] += 1
            by_severity[str(finding.get("severity", "unknown"))] += 1
            blocking += 1 if finding.get("blocking") else 0
    return {
        "finding_rule_frequency": dict(sorted(by_rule.items())),
        "finding_severity_frequency": dict(sorted(by_severity.items())),
        "blocking_finding_count": blocking,
    }


def _summarize_acquisition(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    method: Counter[str] = Counter()
    status_code: Counter[str] = Counter()
    blocked = 0
    for _record, diagnose in pairs:
        acquisition = diagnose.get("acquisition", {})
        method[str(acquisition.get("method"))] += 1
        status_code[str(acquisition.get("status_code"))] += 1
        if acquisition.get("blocked"):
            blocked += 1
    return {
        "method_distribution": dict(sorted(method.items())),
        "status_code_distribution": dict(sorted(status_code.items())),
        "blocked_count": blocked,
    }


def _summarize_root_causes(run_dir: Path) -> dict[str, Any]:
    report_path = run_dir / "report.json"
    if not report_path.exists():
        return {"root_cause_count": 0, "top_root_causes": []}
    report = _load_json(report_path)
    reduced: list[dict[str, Any]] = []
    for cause in report.get("root_causes", []):
        example = (cause.get("examples") or [{}])[0]
        reduced.append(
            {
                "rule_id": str(example.get("rule_id", "unknown")),
                "scope": str(example.get("scope", "unknown")),
                "severity": str(example.get("severity", "unknown")),
                "count": int(cause.get("count", 0)),
            }
        )
    reduced.sort(key=lambda c: (-c["count"], c["rule_id"], c["scope"]))
    return {
        "root_cause_count": int(report.get("root_cause_count", len(reduced))),
        "top_root_causes": reduced[:15],
    }


def summarize_run(run_dir: Path | str) -> dict[str, Any]:
    """Reduce a completed run's frozen artifacts to a stable baseline summary."""
    run_dir = Path(run_dir)
    pairs = _load_results(run_dir)
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "source_run": run_dir.name,
        "outcomes": _summarize_outcomes(pairs),
        "extraction_latency": _summarize_latency(pairs),
        "fields": _summarize_fields(pairs),
        "variants": _summarize_variants(pairs),
        "findings": _summarize_findings(pairs),
        "acquisition": _summarize_acquisition(pairs),
        "root_causes": _summarize_root_causes(run_dir),
        "cost_signals": _COST_SIGNALS,
    }


def generate(run_dir: Path | str, out_path: Path | str) -> dict[str, Any]:
    """Compute the baseline for ``run_dir`` and write it to ``out_path``."""
    summary = summarize_run(run_dir)
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


_DEFAULT_RUN = Path(__file__).resolve().parents[2] / "artifacts" / "runs" / "1"
_DEFAULT_OUT = Path(__file__).resolve().parent / "baselines" / "run_1.json"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Freeze the deterministic extraction baseline."
    )
    parser.add_argument("--run-dir", default=str(_DEFAULT_RUN))
    parser.add_argument("--out", default=str(_DEFAULT_OUT))
    parsed = parser.parse_args(argv)
    summary = generate(parsed.run_dir, parsed.out)
    print(f"wrote {parsed.out}: {summary['outcomes']['result_count']} results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
