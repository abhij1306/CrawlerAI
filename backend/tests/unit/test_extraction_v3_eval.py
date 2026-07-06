from __future__ import annotations

import json
from pathlib import Path

from eval.corpus import stats, write_proposals
from eval.grounding import grounding_report
from eval.run import run_baseline, run_label_score


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "artifacts" / "runs" / "1"
AUDIT_PATH = ROOT.parent / "chatgpt_audit" / "audit_data.json"
LABEL_DIR = ROOT / "eval" / "labels"


def test_corpus_registers_commerce_detail_pages_without_false_verification(
    tmp_path: Path,
) -> None:
    result = stats(run_dir=RUN_DIR, audit_path=AUDIT_PATH, label_dir=tmp_path)

    assert result["registered"] == 91
    assert result["human_verified"] == 0
    assert result["unverified"] == 91
    assert result["variant_buckets"] == {
        "dom_only": 17,
        "embedded_json": 7,
        "partial": 12,
        "single_sku": 55,
        "unknown": 0,
    }


def test_corpus_writes_unverified_label_proposals(tmp_path: Path) -> None:
    written = write_proposals(run_dir=RUN_DIR, audit_path=AUDIT_PATH, label_dir=tmp_path)

    assert written == 91
    label = json.loads((tmp_path / "1.json").read_text(encoding="utf-8"))
    assert label["human_verified"] is False
    assert label["metadata"]["variant_bucket"] == "embedded_json"
    assert label["fields"]["title"]


def test_corpus_counts_human_verified_seed_labels() -> None:
    result = stats(run_dir=RUN_DIR, audit_path=AUDIT_PATH, label_dir=LABEL_DIR)

    assert result["registered"] == 91
    assert result["human_verified"] == 8
    assert result["valid"] is True


def test_label_score_runs_on_verified_seed_labels() -> None:
    report = run_label_score(
        run_dir=RUN_DIR,
        audit_path=AUDIT_PATH,
        label_dir=LABEL_DIR,
    )

    assert report["verified_pages"] == 8
    assert report["page_count"] == 8
    assert report["variant_metrics"]["pages_with_expected_variants"] == 6
    assert report["field_counts"]["price"]["tp"] >= 1
    assert 0.0 <= report["hallucination_proxy_rate"] <= 1.0
    assert 0.0 <= report["variant_matrix_accuracy"] <= 1.0


def test_grounding_report_runs_on_verified_seed_labels() -> None:
    report = grounding_report(
        run_dir=RUN_DIR,
        audit_path=AUDIT_PATH,
        label_dir=LABEL_DIR,
    )

    assert report["verified_pages"] == 8
    assert report["grounded_values"] >= 1
    assert 0.0 <= report["grounding_failure_rate"] <= 1.0


def test_baseline_reproduces_frozen_defect_counts(tmp_path: Path) -> None:
    report = run_baseline(
        run_dir=RUN_DIR,
        audit_path=AUDIT_PATH,
        out=tmp_path / "baseline.json",
    )

    assert report["matches_expected"] is True
    assert report["defect_counts"] == {
        "empty_records": 5,
        "empty_variants_where_expected": 11,
        "missing_price_on_commerce_detail": 13,
    }
