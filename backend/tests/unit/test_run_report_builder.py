from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.observability.run_report import (
    SCHEMA_VERSION,
    build_run_report,
    write_run_report,
)

pytestmark = pytest.mark.unit


def _write_diagnose(
    artifacts_dir: Path,
    *,
    run_id: int,
    url_result_id: int,
    payload: dict,
) -> Path:
    path = (
        artifacts_dir
        / "runs"
        / str(run_id)
        / "results"
        / str(url_result_id)
        / "diagnose.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def artifacts_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    return tmp_path


def test_empty_run_yields_zero_root_causes(artifacts_root: Path) -> None:
    (artifacts_root / "runs" / "1" / "results").mkdir(parents=True)
    report = build_run_report(1)
    assert report == {
        "schema_version": SCHEMA_VERSION,
        "run_id": 1,
        "root_cause_count": 0,
        "root_causes": [],
    }


def test_resolved_fields_are_not_root_causes(artifacts_root: Path) -> None:
    _write_diagnose(
        artifacts_root,
        run_id=1,
        url_result_id=10,
        payload={
            "fields": [
                {"field": "price", "status": "captured_and_resolved"},
                {"field": "currency", "status": "captured_published"},
            ],
            "variants": {"dropped": []},
        },
    )
    report = build_run_report(1)
    assert report["root_cause_count"] == 0
    assert report["root_causes"] == []


def test_unresolved_field_status_becomes_root_cause(artifacts_root: Path) -> None:
    _write_diagnose(
        artifacts_root,
        run_id=1,
        url_result_id=10,
        payload={
            "fields": [
                {"field": "price", "status": "captured_but_rejected"},
            ],
        },
    )
    report = build_run_report(1)
    assert report["root_cause_count"] == 1
    cause = report["root_causes"][0]
    assert cause["root_cause"] == "field:price:captured_but_rejected"
    assert cause["count"] == 1
    assert cause["diagnose_links"] == [
        "runs/1/results/10/diagnose.json",
    ]


def test_field_reason_codes_become_bounded_root_causes(artifacts_root: Path) -> None:
    _write_diagnose(
        artifacts_root,
        run_id=1,
        url_result_id=10,
        payload={
            "fields": [
                {
                    "field": "price",
                    "status": "captured_suppressed",
                    "reason_codes": ["invalid_decimal"],
                },
            ],
        },
    )

    report = build_run_report(1)

    causes = {row["root_cause"]: row for row in report["root_causes"]}
    assert "field:price:captured_suppressed" in causes
    assert "field_reason:price:captured_suppressed:invalid_decimal" in causes
    assert causes["field:price:captured_suppressed"]["examples"] == [
        {
            "field": "price",
            "reason_codes": ["invalid_decimal"],
            "status": "captured_suppressed",
        }
    ]


def test_findings_become_root_causes(artifacts_root: Path) -> None:
    _write_diagnose(
        artifacts_root,
        run_id=1,
        url_result_id=10,
        payload={
            "findings": [
                {
                    "rule_id": "PRICE_WITHOUT_CURRENCY",
                    "severity": "medium",
                    "blocking": False,
                    "scope": "selected_entity",
                },
                {
                    "rule_id": "PUBLIC_RESOLUTION_DIVERGENCE",
                    "severity": "critical",
                    "blocking": True,
                    "scope": "page",
                },
            ],
        },
    )

    report = build_run_report(1)

    assert [row["root_cause"] for row in report["root_causes"]] == [
        "blocking_finding:PUBLIC_RESOLUTION_DIVERGENCE",
        "finding:PRICE_WITHOUT_CURRENCY",
    ]



def test_record_completeness_metric_is_not_a_root_cause(artifacts_root: Path) -> None:
    _write_diagnose(
        artifacts_root,
        run_id=1,
        url_result_id=10,
        payload={
            "findings": [
                {
                    "rule_id": "RECORD_COMPLETENESS",
                    "severity": "medium",
                    "blocking": False,
                    "scope": "page",
                    "metadata": {"score": 0.5, "missing_fields": ["brand"]},
                }
            ]
        },
    )

    assert build_run_report(1)["root_causes"] == []


def test_missing_contract_fields_are_grouped_by_field(artifacts_root: Path) -> None:
    for url_result_id, field in ((10, "brand"), (11, "brand"), (12, "availability")):
        _write_diagnose(
            artifacts_root,
            run_id=1,
            url_result_id=url_result_id,
            payload={
                "findings": [
                    {
                        "rule_id": "MISSING_CONTRACT_FIELD",
                        "severity": "medium",
                        "blocking": False,
                        "scope": "page",
                        "metadata": {"field": field},
                    }
                ]
            },
        )

    report = build_run_report(1)

    assert [row["root_cause"] for row in report["root_causes"]] == [
        "finding:MISSING_CONTRACT_FIELD:brand",
        "finding:MISSING_CONTRACT_FIELD:availability",
    ]
    assert [row["count"] for row in report["root_causes"]] == [2, 1]


def test_publication_policy_reason_becomes_root_cause(artifacts_root: Path) -> None:
    _write_diagnose(
        artifacts_root,
        run_id=2,
        url_result_id=5,
        payload={
            "fields": [
                {
                    "field": "currency",
                    "status": "captured_and_resolved",
                    "publication_policy": "FAILED_ISO_4217",
                }
            ]
        },
    )
    report = build_run_report(2)
    assert (
        report["root_causes"][0]["root_cause"]
        == "publication_policy:currency:FAILED_ISO_4217"
    )


def test_variant_drop_becomes_root_cause(artifacts_root: Path) -> None:
    _write_diagnose(
        artifacts_root,
        run_id=3,
        url_result_id=8,
        payload={
            "fields": [],
            "variants": {
                "dropped": [
                    {
                        "row": "SKU-1",
                        "stage": "publication",
                        "rule": "PRICE",
                        "reason": "no_price",
                    }
                ]
            },
        },
    )
    report = build_run_report(3)
    assert report["root_causes"][0]["root_cause"] == "variant_dropped:publication:PRICE"


def test_groups_same_cause_across_urls_and_sorts_by_count(
    artifacts_root: Path,
) -> None:
    # Two URLs share publication_policy:price:NEGATIVE; one URL has a unique field issue.
    for url_result_id in (10, 11):
        _write_diagnose(
            artifacts_root,
            run_id=4,
            url_result_id=url_result_id,
            payload={
                "fields": [
                    {
                        "field": "price",
                        "status": "captured_and_resolved",
                        "publication_policy": "NEGATIVE",
                    }
                ]
            },
        )
    _write_diagnose(
        artifacts_root,
        run_id=4,
        url_result_id=12,
        payload={
            "fields": [{"field": "currency", "status": "source_unavailable"}],
        },
    )

    report = build_run_report(4)

    assert [cause["root_cause"] for cause in report["root_causes"]] == [
        "publication_policy:price:NEGATIVE",
        "field:currency:source_unavailable",
    ]
    assert report["root_causes"][0]["count"] == 2
    assert report["root_causes"][0]["diagnose_links"] == [
        "runs/4/results/10/diagnose.json",
        "runs/4/results/11/diagnose.json",
    ]


def test_malformed_diagnose_files_are_skipped(artifacts_root: Path) -> None:
    results_dir = artifacts_root / "runs" / "5" / "results"
    (results_dir / "1").mkdir(parents=True)
    (results_dir / "1" / "diagnose.json").write_text("not json", encoding="utf-8")
    _write_diagnose(
        artifacts_root,
        run_id=5,
        url_result_id=2,
        payload={"fields": [{"field": "x", "status": "source_unavailable"}]},
    )

    report = build_run_report(5)

    assert report["root_cause_count"] == 1
    assert report["root_causes"][0]["root_cause"] == "field:x:source_unavailable"


def test_publication_policy_mapping_value_uses_reason_key(artifacts_root: Path) -> None:
    _write_diagnose(
        artifacts_root,
        run_id=6,
        url_result_id=1,
        payload={
            "fields": [
                {
                    "field": "currency",
                    "status": "captured_and_resolved",
                    "publication_policy": {
                        "reason": "MIXED_CURRENCIES",
                        "code": 42,
                    },
                }
            ]
        },
    )
    report = build_run_report(6)
    assert (
        report["root_causes"][0]["root_cause"]
        == "publication_policy:currency:MIXED_CURRENCIES"
    )


@pytest.mark.asyncio
async def test_write_run_report_persists_report_json(artifacts_root: Path) -> None:
    _write_diagnose(
        artifacts_root,
        run_id=7,
        url_result_id=1,
        payload={"fields": [{"field": "title", "status": "source_unavailable"}]},
    )

    await write_run_report(7)

    report_path = artifacts_root / "runs" / "7" / "report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["run_id"] == 7
    assert report["root_cause_count"] == 1


@pytest.mark.asyncio
async def test_write_run_report_swallows_errors(
    artifacts_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_run_id: int) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr("app.observability.run_report.build_run_report", _boom)
    # Should not raise into the pipeline.
    await write_run_report(99)
