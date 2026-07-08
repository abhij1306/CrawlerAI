from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import app.extraction.pipeline as extraction_pipeline
from app.connectors.llm.config_service import default_generalized_config_snapshot
from app.connectors.llm.generalized_extraction import hosted_generalized_adapter
from app.core.config.evaluation import (
    EXTRACTION_V3_BASELINE_SCHEMA_VERSION,
    EXTRACTION_V3_EVAL_SCHEMA_VERSION,
    EXTRACTION_V3_FULL_CORPUS_GATE_DEFECTS,
    GENERALIZED_EXTRACTION_HOSTED_ADAPTER_ID,
    GENERALIZED_EXTRACTION_LLM_TASK,
)
from app.core.extraction_memory.templates import normalize_route, source_pattern
from app.extraction.engine import extract
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface

from eval.corpus import (
    DEFAULT_AUDIT_PATH,
    DEFAULT_LABEL_DIR,
    DEFAULT_RUN_DIR,
    load_pages,
)
from eval.score import (
    baseline_defects as score_defects,
    baseline_report,
    score_records_against_labels,
)


DEFAULT_REPORT = Path(__file__).resolve().parent / "reports" / "baseline.json"


def run_baseline(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    out: Path | None = DEFAULT_REPORT,
) -> dict[str, Any]:
    report = {
        "schema_version": EXTRACTION_V3_BASELINE_SCHEMA_VERSION,
        "engine": "baseline",
        **baseline_report(run_dir=run_dir, audit_path=audit_path),
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report


def run_label_score(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    label_dir: Path = DEFAULT_LABEL_DIR,
) -> dict[str, Any]:
    pages = load_pages(run_dir=run_dir, audit_path=audit_path, label_dir=label_dir)
    verified_pages = tuple(page for page in pages if page.is_verified)
    report = score_records_against_labels(verified_pages).to_dict()
    report["verified_pages"] = len(verified_pages)
    return report


def run_v3_engine(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    label_dir: Path = DEFAULT_LABEL_DIR,
    tier: str = "cascade",
    no_recipes: bool = False,
    no_selectors: bool = False,
    llm_config_path: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    model_adapter: Any | None = None,
    out: Path | None = None,
) -> dict[str, Any]:
    pages = load_pages(run_dir=run_dir, audit_path=audit_path, label_dir=label_dir)
    verified_pages = tuple(page for page in pages if page.is_verified)
    adapter = (
        None
        if tier == "recipe"
        else (
            model_adapter
            or _hosted_adapter_from_config(llm_config_path)
            or _default_hosted_adapter(provider=provider, model=model)
        )
    )
    if tier == "generalized" and adapter is None:
        payloads, candidate_runtime = _missing_generalized_candidate(pages)
    else:
        payloads, candidate_runtime = _candidate_payloads(
            pages,
            tier=tier,
            no_selectors=no_selectors,
            model_adapter=adapter,
        )
    candidate = score_records_against_labels(
        verified_pages,
        record_payloads=payloads,
    ).to_dict()
    baseline = score_records_against_labels(verified_pages).to_dict()
    frozen_baseline_defects = baseline_report(run_dir=run_dir, audit_path=audit_path)[
        "defect_counts"
    ]
    candidate_full_defects = score_defects(pages, record_payloads=payloads)
    cascade_progress = _cascade_progress(
        pages=pages,
        candidate_payloads=payloads,
        page_runtime=candidate_runtime["pages"],
    )
    collector_ids = set(candidate_runtime["collector_ids"])
    selector_collectors = sorted(
        collector_id
        for collector_id in collector_ids
        if collector_id in {"css_recipe", "dom", "requested_fields"}
    )
    gate_reasons = _v3_gate_reasons(
        candidate=candidate,
        baseline=baseline,
        frozen_baseline_defects=frozen_baseline_defects,
        candidate_full_defects=candidate_full_defects,
        verified_pages=len(verified_pages),
        tier=tier,
        model_invocations=int(candidate_runtime["model_invocations"]),
        llm_config_supplied=adapter is not None,
        cascade_progress=cascade_progress,
    )
    selector_deletion_reasons = _selector_deletion_reasons(
        gate_reasons=gate_reasons,
        no_recipes=no_recipes,
        no_selectors=no_selectors,
        selector_collectors=selector_collectors,
        frozen_baseline_defects=frozen_baseline_defects,
        candidate_full_defects=candidate_full_defects,
    )
    report = {
        "schema_version": EXTRACTION_V3_EVAL_SCHEMA_VERSION,
        "engine": "v3",
        "tier": tier,
        "no_recipes": no_recipes,
        "no_selectors": no_selectors,
        "corpus_pages": len(pages),
        "verified_pages": len(verified_pages),
        "candidate": candidate,
        "baseline_on_verified_labels": baseline,
        "frozen_baseline_defect_counts": frozen_baseline_defects,
        "candidate_full_corpus_defect_counts": candidate_full_defects,
        "full_corpus_gate_defects": list(EXTRACTION_V3_FULL_CORPUS_GATE_DEFECTS),
        "cascade_progress": cascade_progress,
        "selector_collectors_seen": selector_collectors,
        "candidate_runtime": candidate_runtime,
        "llm_config_supplied": adapter is not None,
        "gate_passed": not gate_reasons,
        "gate_reasons": gate_reasons,
        "selector_deletion_unlocked": not selector_deletion_reasons,
        "selector_deletion_reasons": selector_deletion_reasons,
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run extraction V3 eval.")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--score-labels", action="store_true")
    parser.add_argument("--engine", choices=("v3",))
    parser.add_argument(
        "--tier",
        choices=("cascade", "deterministic", "generalized", "recipe"),
        default="cascade",
    )
    parser.add_argument("--no-recipes", action="store_true")
    parser.add_argument("--no-selectors", action="store_true")
    parser.add_argument("--require-pass", action="store_true")
    parser.add_argument("--llm-config")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--audit-path", default=str(DEFAULT_AUDIT_PATH))
    parser.add_argument("--label-dir", default=str(DEFAULT_LABEL_DIR))
    parser.add_argument("--out", default=str(DEFAULT_REPORT))
    parsed = parser.parse_args(argv)
    run_dir = Path(parsed.run_dir)
    audit_path = Path(parsed.audit_path)
    if parsed.baseline:
        report = run_baseline(
            run_dir=run_dir, audit_path=audit_path, out=Path(parsed.out)
        )
    elif parsed.score_labels:
        report = run_label_score(
            run_dir=run_dir,
            audit_path=audit_path,
            label_dir=Path(parsed.label_dir),
        )
    elif parsed.engine == "v3":
        report = run_v3_engine(
            run_dir=run_dir,
            audit_path=audit_path,
            label_dir=Path(parsed.label_dir),
            tier=parsed.tier,
            no_recipes=parsed.no_recipes,
            no_selectors=parsed.no_selectors,
            llm_config_path=Path(parsed.llm_config) if parsed.llm_config else None,
            provider=parsed.provider,
            model=parsed.model,
            out=Path(parsed.out),
        )
    else:
        parser.error("choose --baseline, --score-labels, or --engine v3")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    if parsed.require_pass and not bool(report.get("gate_passed", False)):
        return 1
    return 0


def _candidate_payloads(
    pages,
    *,
    tier: str,
    no_selectors: bool,
    model_adapter: Any | None,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    original_collectors = extraction_pipeline.default_collectors
    if no_selectors or tier == "generalized":
        extraction_pipeline.default_collectors = lambda: tuple(
            collector
            for collector in original_collectors()
            if _collector_allowed(collector.collector_id, tier=tier)
        )
    try:
        payloads: dict[int, dict[str, Any]] = {}
        collector_ids: set[str] = set()
        extractor_tiers: set[str] = set()
        model_invocations = 0
        page_runtime: list[dict[str, Any]] = []
        for page in pages:
            request = fixture_request_from_inputs(
                Surface.ECOMMERCE_DETAIL,
                (page.result_dir / "page.html").read_text(
                    encoding="utf-8",
                    errors="ignore",
                ),
                page.url,
                requested_url=page.url,
                max_records=1,
            ).model_copy(
                update={
                    "runtime_snapshot": _candidate_runtime_snapshot(
                        page=page,
                        tier=tier,
                        model_adapter=model_adapter,
                        no_selectors=no_selectors,
                    )
                }
            )
            result = extract(
                request,
                model_adapter=None if tier == "recipe" else model_adapter,
            )
            payloads[page.result_id] = {
                "record_count": len(result.records),
                "records": [_jsonable(record) for record in result.records],
            }
            collector_ids.update(row.collector_id for row in result.collector_outcomes)
            extractor_tiers.add(result.diagnostics.extractor_tier)
            page_model_invocations = result.metrics.universal_model_invocation_count
            model_invocations += page_model_invocations
            page_runtime.append(
                {
                    "result_id": page.result_id,
                    "collector_ids": sorted(
                        {row.collector_id for row in result.collector_outcomes}
                    ),
                    "extractor_tier": result.diagnostics.extractor_tier,
                    "model_invocations": page_model_invocations,
                }
            )
            if tier == "deterministic":
                continue
        return payloads, {
            "collector_ids": sorted(collector_ids),
            "extractor_tiers": sorted(extractor_tiers),
            "model_invocations": model_invocations,
            "pages": page_runtime,
        }
    finally:
        extraction_pipeline.default_collectors = original_collectors


def _missing_generalized_candidate(
    pages,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    return (
        {page.result_id: {"record_count": 0, "records": []} for page in pages},
        {
            "collector_ids": [],
            "extractor_tiers": [],
            "model_invocations": 0,
            "pages": [
                {
                    "result_id": page.result_id,
                    "collector_ids": [],
                    "extractor_tier": "blocked",
                    "model_invocations": 0,
                }
                for page in pages
            ],
        },
    )


def _collector_allowed(collector_id: str, *, tier: str) -> bool:
    if tier == "generalized":
        return collector_id == "url"
    return collector_id != "dom"


def _candidate_runtime_snapshot(
    *,
    page,
    tier: str,
    model_adapter: Any | None,
    no_selectors: bool,
) -> dict[str, Any]:
    if tier == "recipe":
        return _recipe_runtime_snapshot(page, no_selectors=no_selectors)
    return _runtime_snapshot(model_adapter)


def _recipe_runtime_snapshot(page, *, no_selectors: bool) -> dict[str, Any]:
    """Compile source-pin recipe hints, then replay without model invocation."""

    html = (page.result_dir / "page.html").read_text(encoding="utf-8", errors="ignore")
    primer = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        html,
        page.url,
        requested_url=page.url,
        max_records=1,
    )
    primer_result = extract(primer)
    evidence_by_id = {row.evidence_id: row for row in primer_result.evidence}
    contracts: list[dict[str, object]] = []
    for decision in primer_result.decisions:
        if decision.status != "resolved" or not decision.accepted_evidence_ids:
            continue
        evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
        if evidence is None or evidence.locator is None:
            continue
        contracts.append(
            {
                "canonical_field": decision.fact_type,
                "selected_source": source_pattern(
                    evidence.collector_id,
                    evidence.locator.value,
                ),
                "selection_origin": "generic",
                "resolver_rule": decision.rule_id,
            }
        )
    source_pins = [
        {
            "canonical_field": row["canonical_field"],
            "selected_source": row["selected_source"],
            "selection_origin": row["selection_origin"],
            "resolver_rule": row["resolver_rule"],
        }
        for row in contracts
    ]
    return {
        "surface": "ecommerce_detail",
        "templates": [
            {
                "template_id": f"eval-recipe-{page.result_id}",
                "fingerprint": f"eval-recipe-{page.result_id}",
                "route_pattern": normalize_route(page.url, "ecommerce_detail"),
                "contracts": contracts,
                "compiled_recipe": {
                    "compiler_version": "recipe.v1",
                    "selector_rules": [] if no_selectors else [],
                    "contracts": contracts,
                    "source_pins": source_pins,
                    "field_schema": [
                        {
                            "canonical_field": row["canonical_field"],
                            "required": False,
                            "value_sense": "",
                        }
                        for row in contracts
                    ],
                    "provenance": [
                        {
                            "source": "eval_primer",
                            "result_id": page.result_id,
                        }
                    ],
                },
            }
        ],
    }


def _runtime_snapshot(model_adapter: Any | None) -> dict[str, Any]:
    if model_adapter is None:
        return {}
    return {
        "llm_enabled": True,
        "universal_model": {
            "schema_version": "universal_model_artifact.v1",
            "artifact_id": "eval-generalized-extractor",
            "artifact_version": "eval",
            "adapter_id": model_adapter.adapter_id,
            "model_family": "eval-generalized",
            "deployment_mode": "shared",
            "benchmark_schema_version": "universal_model_benchmark.v2",
            "benchmark_report_id": "eval-gate",
            "benchmark_passed": True,
            "approved": True,
            "enabled": True,
            "confidence_threshold": 0.8,
            # Let the shared GENERALIZED_EXTRACTION_BUDGET.budget_ms govern the real
            # ceiling (_runtime_budget_ms takes the min of the two). A 1000ms
            # artifact timeout would re-cap every live hosted-provider call at 1s
            # and time it out before any response lands.
            "timeout_ms": 60000,
            "max_memory_mb": 256.0,
            "max_cost_per_page_usd": 0.02,
            "supported_surfaces": ["ecommerce_detail"],
        },
    }


def _hosted_adapter_from_config(config_path: Path | None):
    if config_path is None:
        return None
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if GENERALIZED_EXTRACTION_LLM_TASK in config:
        config = config[GENERALIZED_EXTRACTION_LLM_TASK]
    if not isinstance(config, dict):
        return None
    config.setdefault("task_type", GENERALIZED_EXTRACTION_LLM_TASK)
    return _adapter_from_snapshot(config)


def _default_hosted_adapter(*, provider: str | None, model: str | None):
    """Resolve the generalized adapter from the configured provider catalog.

    Provider-agnostic and UI-aligned: honors an explicit ``--provider``/``--model``,
    otherwise auto-selects the first catalog provider that has an API key set
    (Mistral is the catalog default). Returns ``None`` when nothing is configured.
    """
    snapshot = default_generalized_config_snapshot(provider=provider, model=model)
    if snapshot is None:
        return None
    return _adapter_from_snapshot(snapshot)


def _adapter_from_snapshot(config_snapshot: dict[str, Any]):
    adapter = hosted_generalized_adapter(config_snapshot=config_snapshot)
    if adapter and adapter.adapter_id == GENERALIZED_EXTRACTION_HOSTED_ADAPTER_ID:
        return adapter
    return None


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _v3_gate_reasons(
    *,
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    frozen_baseline_defects: dict[str, int],
    candidate_full_defects: dict[str, int],
    verified_pages: int,
    tier: str,
    model_invocations: int,
    llm_config_supplied: bool,
    cascade_progress: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    defects = candidate["defect_counts"]
    baseline_verified_defects = baseline["defect_counts"]
    if verified_pages == 0:
        reasons.append("no_verified_labels")
    if tier == "generalized" and not llm_config_supplied:
        reasons.append("generalized_adapter_missing")
    if tier == "generalized" and model_invocations == 0:
        reasons.append("generalized_tier_not_invoked")
    for key in EXTRACTION_V3_FULL_CORPUS_GATE_DEFECTS:
        baseline_value = frozen_baseline_defects[key]
        if candidate_full_defects[key] > baseline_value:
            reasons.append(f"regressed_full_corpus:{key}")
    for key in baseline_verified_defects:
        if defects[key] > baseline_verified_defects[key]:
            reasons.append(f"regressed_verified:{key}")
    for field, metrics in candidate["field_metrics"].items():
        baseline_f1 = baseline["field_metrics"][field]["f1"]
        if metrics["f1"] < baseline_f1:
            reasons.append(f"field_f1_regressed:{field}")
    if (
        tier == "cascade"
        and cascade_progress["baseline_failing_pages"] > 0
        and not cascade_progress["generalized_helped_failing_pages"]
    ):
        reasons.append("generalized_did_not_help_failing_pages")
    return reasons


def _selector_deletion_reasons(
    *,
    gate_reasons: list[str],
    no_recipes: bool,
    no_selectors: bool,
    selector_collectors: list[str],
    frozen_baseline_defects: dict[str, int],
    candidate_full_defects: dict[str, int],
) -> list[str]:
    reasons: list[str] = []
    if gate_reasons:
        reasons.append("cascade_gate_not_passed")
    if not no_recipes:
        reasons.append("recipes_not_disabled")
    if not no_selectors:
        reasons.append("selectors_not_disabled")
    if selector_collectors:
        reasons.append("selector_collectors_seen")
    for key in EXTRACTION_V3_FULL_CORPUS_GATE_DEFECTS:
        baseline_value = frozen_baseline_defects[key]
        if candidate_full_defects[key] > baseline_value:
            reasons.append(f"regressed_full_corpus:{key}")
    return reasons


def _cascade_progress(
    *,
    pages,
    candidate_payloads: dict[int, dict[str, Any]],
    page_runtime: list[dict[str, Any]],
) -> dict[str, Any]:
    runtime_by_page = {int(row["result_id"]): row for row in page_runtime}
    baseline_failing_pages: list[int] = []
    improved_pages: list[int] = []
    generalized_helped_pages: list[int] = []
    regressed_pages: list[int] = []
    for page in pages:
        baseline_total = _defect_total(page, record_payloads=None)
        candidate_total = _defect_total(page, record_payloads=candidate_payloads)
        if baseline_total > 0:
            baseline_failing_pages.append(page.result_id)
        if baseline_total > candidate_total:
            improved_pages.append(page.result_id)
            runtime = runtime_by_page.get(page.result_id, {})
            if int(runtime.get("model_invocations") or 0) > 0:
                generalized_helped_pages.append(page.result_id)
        if candidate_total > baseline_total:
            regressed_pages.append(page.result_id)
    return {
        "baseline_failing_pages": len(baseline_failing_pages),
        "candidate_improved_failing_pages": improved_pages,
        "generalized_helped_failing_pages": generalized_helped_pages,
        "candidate_regressed_pages": regressed_pages,
    }


def _defect_total(page, *, record_payloads: dict[int, dict[str, Any]] | None) -> int:
    return sum(score_defects((page,), record_payloads=record_payloads).values())


if __name__ == "__main__":
    raise SystemExit(main())
