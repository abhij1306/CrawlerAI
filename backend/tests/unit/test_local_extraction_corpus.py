from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_local_extraction_corpus

pytestmark = pytest.mark.unit


def test_local_extraction_corpus_runs_partition_without_skips(tmp_path: Path) -> None:
    html_path = tmp_path / "case.html"
    html_path.write_text(
        """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Trail Shoe",
         "offers":{"@type":"Offer","price":"19.99","priceCurrency":"USD"}}
        </script>
        </head><body><h1>Trail Shoe</h1></body></html>
        """,
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "datasets": {
                    "clean": [
                        {
                            "name": "clean product",
                            "surface": "ecommerce_detail",
                            "requested_url": "https://example.com/products/shoe",
                            "html_path": "case.html",
                            "requested_fields": ["title", "price"],
                            "expected": {
                                "verdict": ["success"],
                                "fields": {
                                    "title": ["captured_published"],
                                    "price": ["captured_published"],
                                },
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    code = run_local_extraction_corpus.main(
        [
            "--manifest",
            str(manifest_path),
            "--dataset",
            "clean",
            "--output-dir",
            str(output_dir),
        ]
    )

    report = json.loads((output_dir / "latest-report.json").read_text("utf-8"))
    assert code == 0
    assert report["summary"]["skipped"] == 0
    assert report["summary"]["publication_divergence"] == 0
    assert report["summary"]["evidence_accounting_rate"] == 1.0


def test_local_extraction_corpus_fails_closed_on_missing_capture(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "datasets": {
                    "missing": [
                        {
                            "name": "missing product",
                            "surface": "ecommerce_detail",
                            "requested_url": "https://example.com/products/missing",
                            "html_path": "missing.html",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    code = run_local_extraction_corpus.main(
        [
            "--manifest",
            str(manifest_path),
            "--dataset",
            "missing",
            "--output-dir",
            str(output_dir),
        ]
    )

    report = json.loads((output_dir / "latest-report.json").read_text("utf-8"))
    assert code == 1
    assert report["summary"]["skipped"] == 1
    assert report["summary"]["passed"] is False
