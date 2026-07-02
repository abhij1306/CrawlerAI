from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation import baseline

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "artifacts" / "runs" / "1"


@pytest.fixture(scope="module")
def summary() -> dict:
    if not (RUN_DIR / "results").is_dir():
        pytest.skip("frozen run corpus is not present")
    return baseline.summarize_run(RUN_DIR)


def _make_result(tmp_path: Path, name: str, diagnose: dict, record: dict) -> None:
    result_dir = tmp_path / "results" / name
    result_dir.mkdir(parents=True)
    (result_dir / "diagnose.json").write_text(json.dumps(diagnose), encoding="utf-8")
    (result_dir / "record.json").write_text(json.dumps(record), encoding="utf-8")


def test_summary_is_versioned(summary: dict) -> None:
    assert summary["schema_version"] == baseline.BASELINE_SCHEMA_VERSION
    assert summary["source_run"] == "1"


def test_cost_signals_are_absent_for_deterministic_run(summary: dict) -> None:
    assert summary["cost_signals"]["available"] is False


def test_outcomes_are_internally_consistent(summary: dict) -> None:
    outcomes = summary["outcomes"]
    assert outcomes["result_count"] > 0
    assert (
        outcomes["urls_with_records"] + outcomes["urls_zero_records"]
        == outcomes["result_count"]
    )
    assert sum(outcomes["verdict_distribution"].values()) == outcomes["result_count"]


def test_field_publish_rate_is_a_ratio(summary: dict) -> None:
    for rate in summary["fields"]["contract_field_publish_rate"].values():
        assert 0.0 <= rate <= 1.0


def test_root_causes_are_sorted_descending(summary: dict) -> None:
    counts = [c["count"] for c in summary["root_causes"]["top_root_causes"]]
    assert counts == sorted(counts, reverse=True)


def test_summary_is_json_serializable_and_deterministic(summary: dict) -> None:
    first = json.dumps(summary, sort_keys=True)
    second = json.dumps(baseline.summarize_run(RUN_DIR), sort_keys=True)
    assert first == second


def test_synthetic_run_reduces_expected_signals(tmp_path: Path) -> None:
    _make_result(
        tmp_path,
        "100",
        diagnose={
            "verdict": "partial",
            "data_integrity": "partial",
            "acquisition": {
                "method": "curl_cffi",
                "status_code": 200,
                "blocked": False,
            },
            "metrics": {
                "completeness_score": 0.5,
                "resolve_duration_ms": 10.0,
                "publish_duration_ms": 1.0,
                "variant_count": 2,
            },
            "fields": [
                {
                    "field": "title",
                    "status": "captured_published",
                    "reason_codes": ["SCALAR_LEXICOGRAPHIC"],
                },
                {"field": "description", "status": "captured_but_rejected"},
                {"field": "color", "status": "not_requested"},
            ],
            "findings": [
                {
                    "rule_id": "MISSING_CONTRACT_FIELD",
                    "severity": "medium",
                    "blocking": False,
                },
            ],
            "variants": {"dropped": []},
        },
        record={"record_count": 1, "records": [{}]},
    )
    _make_result(
        tmp_path,
        "101",
        diagnose={
            "verdict": "complete",
            "data_integrity": "complete",
            "acquisition": {
                "method": "curl_cffi",
                "status_code": 200,
                "blocked": False,
            },
            "metrics": {
                "completeness_score": 1.0,
                "resolve_duration_ms": 20.0,
                "publish_duration_ms": 2.0,
                "variant_count": 0,
            },
            "fields": [
                {
                    "field": "title",
                    "status": "captured_published",
                    "reason_codes": ["SCALAR_LEXICOGRAPHIC"],
                },
                {"field": "description", "status": "captured_published"},
            ],
            "findings": [],
            "variants": {"dropped": [{"reason": "x"}]},
        },
        record={"record_count": 0, "records": []},
    )
    (tmp_path / "report.json").write_text(
        json.dumps(
            {
                "root_cause_count": 1,
                "root_causes": [
                    {
                        "count": 1,
                        "examples": [
                            {
                                "rule_id": "MISSING_CONTRACT_FIELD",
                                "scope": "page",
                                "severity": "medium",
                                "blocking": False,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = baseline.summarize_run(tmp_path)

    outcomes = result["outcomes"]
    assert outcomes["result_count"] == 2
    assert outcomes["total_records"] == 1
    assert outcomes["urls_with_records"] == 1
    assert outcomes["verdict_distribution"] == {"complete": 1, "partial": 1}
    assert outcomes["completeness_score"]["min"] == 0.5

    fields = result["fields"]
    assert fields["contract_field_publish_rate"]["title"] == 1.0
    assert fields["contract_field_publish_rate"]["description"] == 0.5
    assert "color" not in fields["contract_field_publish_rate"]
    assert fields["reason_code_frequency"]["SCALAR_LEXICOGRAPHIC"] == 2

    variants = result["variants"]
    assert variants["total_variants"] == 2
    assert variants["urls_with_dropped_variants"] == 1

    findings = result["findings"]
    assert findings["finding_rule_frequency"]["MISSING_CONTRACT_FIELD"] == 1
    assert findings["blocking_finding_count"] == 0

    latency = result["extraction_latency"]
    assert latency["resolve_ms"]["p50"] is not None

    root = result["root_causes"]
    assert root["root_cause_count"] == 1
    assert root["top_root_causes"][0]["rule_id"] == "MISSING_CONTRACT_FIELD"


def test_generate_writes_sorted_json(tmp_path: Path) -> None:
    _make_result(
        tmp_path,
        "1",
        diagnose={
            "verdict": "complete",
            "data_integrity": "complete",
            "acquisition": {
                "method": "curl_cffi",
                "status_code": 200,
                "blocked": False,
            },
            "metrics": {
                "completeness_score": 1.0,
                "resolve_duration_ms": 1.0,
                "publish_duration_ms": 1.0,
                "variant_count": 0,
            },
            "fields": [],
            "findings": [],
            "variants": {"dropped": []},
        },
        record={"record_count": 1, "records": [{}]},
    )
    out_path = tmp_path / "baselines" / "out.json"
    baseline.generate(tmp_path, out_path)
    text = out_path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text)["schema_version"] == baseline.BASELINE_SCHEMA_VERSION
