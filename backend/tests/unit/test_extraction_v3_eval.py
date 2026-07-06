from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.connectors.llm.config_service import default_generalized_config_snapshot
from app.core.config.evaluation import (
    GENERALIZED_EXTRACTION_HOSTED_ADAPTER_ID,
    GENERALIZED_EXTRACTION_LLM_TASK,
)
from app.extraction.contracts import (
    EntityHint,
    ModelEvidenceCandidate,
    UniversalModelResult,
)
from eval.corpus import stats, write_proposals
from eval.grounding import grounding_report
from eval.run import main, run_baseline, run_label_score, run_v3_engine


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


class EvalModelAdapter:
    adapter_id = GENERALIZED_EXTRACTION_HOSTED_ADAPTER_ID

    def predict(self, page, artifact, *, timeout_ms):
        del timeout_ms
        entry = next(row for row in page.entries if "Trail Shirt" in row.text)
        hint = EntityHint(
            entity_type="product",
            url="https://example.com/products/shirt",
        )
        return UniversalModelResult(
            adapter_id=self.adapter_id,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            predictions=(
                ModelEvidenceCandidate(
                    prediction_id="title",
                    artifact_id=page.source.artifact_id,
                    source_path=entry.path,
                    fact_type="product.title",
                    raw_value="Trail Shirt",
                    value="Trail Shirt",
                    subject_id="model-product-1",
                    subject_scope="product",
                    confidence=0.95,
                    entity_hint=hint,
                ),
            ),
            latency_ms=1.0,
            memory_mb=16.0,
            cost_usd=0.001,
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


def test_v3_engine_gate_scores_candidate_records_and_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir, audit_path, label_dir = _synthetic_corpus(tmp_path)
    _write_verified_label(label_dir)
    # Neutralize the env-based default provider so this exercises the genuine
    # "no adapter configured" path deterministically, regardless of whether a
    # MISTRALAI_API_KEY happens to be present in the developer's/CI's .env.
    monkeypatch.setattr(
        "eval.run.default_generalized_config_snapshot",
        lambda **_: None,
    )

    report = run_v3_engine(
        run_dir=run_dir,
        audit_path=audit_path,
        label_dir=label_dir,
        tier="generalized",
        no_recipes=True,
        no_selectors=True,
        out=None,
    )

    assert report["engine"] == "v3"
    assert report["verified_pages"] == 1
    assert report["no_recipes"] is True
    assert report["no_selectors"] is True
    assert report["selector_collectors_seen"] == []
    assert "dom" not in report["candidate_runtime"]["collector_ids"]
    assert report["gate_passed"] is False
    assert "generalized_adapter_missing" in report["gate_reasons"]
    assert "generalized_tier_not_invoked" in report["gate_reasons"]
    assert any(
        reason.startswith("regressed_verified:")
        for reason in report["gate_reasons"]
    )


def test_v3_engine_gate_can_invoke_supplied_generalized_adapter(tmp_path: Path) -> None:
    run_dir, audit_path, label_dir = _synthetic_corpus(tmp_path)
    _write_verified_label(label_dir)

    report = run_v3_engine(
        run_dir=run_dir,
        audit_path=audit_path,
        label_dir=label_dir,
        tier="generalized",
        no_recipes=True,
        no_selectors=True,
        model_adapter=EvalModelAdapter(),
        out=None,
    )

    assert report["candidate_runtime"]["model_invocations"] == 1
    assert report["candidate_runtime"]["extractor_tiers"] == ["ml"]
    assert "generalized_tier_not_invoked" not in report["gate_reasons"]


def test_default_config_snapshot_honors_explicit_provider() -> None:
    # A pinned provider is honored even without a detected key (the key may arrive
    # via env at call time) and drives the provider-agnostic snapshot.
    snapshot = default_generalized_config_snapshot(provider="groq", model="some-model")

    assert snapshot is not None
    assert snapshot["provider"] == "groq"
    assert snapshot["model"] == "some-model"
    assert snapshot["task_type"] == GENERALIZED_EXTRACTION_LLM_TASK


def test_default_config_snapshot_auto_selects_configured_provider(monkeypatch) -> None:
    # Unpinned: the first catalog provider with a configured key wins (Mistral is
    # the catalog default), and its recommended model is filled in.
    import app.core.config as config_module

    for attr in (
        "mistral_api_key",
        "groq_api_key",
        "nvidia_api_key",
        "openrouter_api_key",
        "anthropic_api_key",
    ):
        monkeypatch.setattr(config_module.settings, attr, "", raising=False)
    monkeypatch.setattr(config_module.settings, "groq_api_key", "sk-test", raising=False)

    snapshot = default_generalized_config_snapshot()

    assert snapshot is not None
    assert snapshot["provider"] == "groq"
    assert snapshot["model"]


def test_default_config_snapshot_none_when_unconfigured(monkeypatch) -> None:
    import app.core.config as config_module

    for attr in (
        "mistral_api_key",
        "groq_api_key",
        "nvidia_api_key",
        "openrouter_api_key",
        "anthropic_api_key",
    ):
        monkeypatch.setattr(config_module.settings, attr, "", raising=False)

    assert default_generalized_config_snapshot() is None


def test_v3_engine_require_pass_returns_nonzero_for_red_gate(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    run_dir, audit_path, label_dir = _synthetic_corpus(tmp_path)
    _write_verified_label(label_dir)
    # Keep the CLI gate path offline and deterministic: don't let an env-provided
    # provider key resolve a live hosted adapter during candidate extraction.
    monkeypatch.setattr(
        "eval.run.default_generalized_config_snapshot",
        lambda **_: None,
    )

    code = main(
        [
            "--engine",
            "v3",
            "--tier",
            "generalized",
            "--no-recipes",
            "--no-selectors",
            "--require-pass",
            "--run-dir",
            str(run_dir),
            "--audit-path",
            str(audit_path),
            "--label-dir",
            str(label_dir),
            "--out",
            str(tmp_path / "v3_gate.json"),
        ]
    )

    assert code == 1
    assert json.loads(capsys.readouterr().out)["gate_passed"] is False


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
