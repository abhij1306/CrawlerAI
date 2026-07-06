from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.corpus import stats, write_proposals
from eval.grounding import grounding_report
from eval.run import run_baseline, run_label_score


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "artifacts" / "runs" / "1"
AUDIT_PATH = ROOT.parent / "chatgpt_audit" / "audit_data.json"
LABEL_DIR = ROOT / "eval" / "labels"


def _require_private_audit() -> None:
    if not AUDIT_PATH.exists():
        pytest.skip("private chatgpt_audit corpus is not present")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _synthetic_corpus(tmp_path: Path) -> tuple[Path, Path, Path]:
    run_dir = tmp_path / "runs" / "1"
    audit_path = tmp_path / "audit_data.json"
    label_dir = tmp_path / "labels"
    _write_json(
        audit_path,
        {
            "pages": [
                {
                    "dir": 1,
                    "surface": "detail",
                    "url": "https://example.com/products/shirt",
                    "variant_bucket": "embedded_json",
                    "platform": "shopify",
                    "structured": {"category_breadcrumb": "Apparel>Shirts"},
                }
            ]
        },
    )
    _write_json(
        run_dir / "results" / "1" / "record.json",
        {
            "record_count": 1,
            "records": [
                {
                    "title": "Trail Shirt",
                    "brand": "Acme",
                    "price": "10.00",
                    "currency": "USD",
                    "availability": "in_stock",
                    "category": "Apparel>Shirts",
                    "description": "Trail Shirt by Acme costs 10.00 USD.",
                    "image_url": "https://example.com/shirt.jpg",
                    "variants": [
                        {
                            "size": "M",
                            "color": "Red",
                            "availability": "in_stock",
                            "price": "10.00",
                        }
                    ],
                }
            ],
        },
    )
    (run_dir / "results" / "1" / "page.html").write_text(
        "<html><body><h1>Trail Shirt</h1><p>Acme 10.00 USD in stock</p></body></html>",
        encoding="utf-8",
    )
    return run_dir, audit_path, label_dir


def _write_verified_label(label_dir: Path) -> None:
    _write_json(
        label_dir / "1.json",
        {
            "schema_version": "extraction_v3_label.v1",
            "result_id": 1,
            "surface": "commerce_detail",
            "url": "https://example.com/products/shirt",
            "human_verified": True,
            "metadata": {},
            "fields": {
                "title": "Trail Shirt",
                "brand": "Acme",
                "price": "10.00",
                "currency": "USD",
                "availability": "in_stock",
                "category": "Apparel>Shirts",
                "description": "Trail Shirt by Acme costs 10.00 USD.",
                "images": ["https://example.com/shirt.jpg"],
                "sku": None,
                "gtin": None,
                "mpn": None,
                "sale_price": None,
            },
            "variants": [
                {
                    "size": "M",
                    "color": "Red",
                    "availability": "in_stock",
                    "price": "10.00",
                }
            ],
        },
    )


def test_corpus_registers_commerce_detail_pages_without_false_verification(
    tmp_path: Path,
) -> None:
    _require_private_audit()
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
    run_dir, audit_path, label_dir = _synthetic_corpus(tmp_path)
    written = write_proposals(run_dir=run_dir, audit_path=audit_path, label_dir=label_dir)

    assert written == 1
    label = json.loads((label_dir / "1.json").read_text(encoding="utf-8"))
    assert label["human_verified"] is False
    assert label["metadata"]["variant_bucket"] == "embedded_json"
    assert label["fields"]["title"]


def test_corpus_counts_human_verified_seed_labels() -> None:
    _require_private_audit()
    result = stats(run_dir=RUN_DIR, audit_path=AUDIT_PATH, label_dir=LABEL_DIR)

    assert result["registered"] == 91
    assert result["human_verified"] == 8
    assert result["valid"] is True


def test_label_score_runs_on_verified_seed_labels() -> None:
    _require_private_audit()
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


def test_label_score_runs_on_synthetic_verified_label(tmp_path: Path) -> None:
    run_dir, audit_path, label_dir = _synthetic_corpus(tmp_path)
    _write_verified_label(label_dir)

    report = run_label_score(
        run_dir=run_dir,
        audit_path=audit_path,
        label_dir=label_dir,
    )

    assert report["verified_pages"] == 1
    assert report["page_count"] == 1
    assert report["variant_metrics"]["pages_with_expected_variants"] == 1
    assert report["field_counts"]["price"]["tp"] == 1
    assert report["variant_matrix_accuracy"] == 1.0


def test_grounding_report_runs_on_verified_seed_labels(tmp_path: Path) -> None:
    run_dir, audit_path, label_dir = _synthetic_corpus(tmp_path)
    _write_verified_label(label_dir)
    report = grounding_report(
        run_dir=run_dir,
        audit_path=audit_path,
        label_dir=label_dir,
    )

    assert report["verified_pages"] == 1
    assert report["grounded_values"] >= 1
    assert 0.0 <= report["grounding_failure_rate"] <= 1.0


def test_baseline_reproduces_frozen_defect_counts(tmp_path: Path) -> None:
    _require_private_audit()
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
