from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from radon.complexity import cc_visit

pytestmark = pytest.mark.unit

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
# SLICE-6 closeout reconciliation: measured against the working tree after the
# cascade refactor/reformat. Net ratchet-DOWN — seven modules (browser_capture,
# browser_pool, cookie_store, browser_attempt_runner, intelligence/discovery,
# intelligence/matching, schemas/crawl) dropped below the 700-line threshold
# and left the ledger; most survivors shrank.
OVERSIZED_MODULE_DEBT = {
    # Closeout hardening (readiness terminal states, escalation diagnostics,
    # coderabbit findings 1-7): browser_readiness re-entered the ledger at the
    # threshold edge; extraction collectors shrank with the srcset helper
    # dedup; extraction_memory grew with the bounded persist lock-wait seam.
    # Audit-fix reconciliation (2026-07-22, measured against working tree):
    # extraction/resolution/__init__.py left the ledger (2,044 -> 175 facade
    # after the god-package split); enrichment/service.py grew with the
    # Celery job runner (2.7); intelligence/service.py entered with the
    # concurrent candidate polling; extraction_memory grew with the
    # knowledge.py query-layer move (4.6).
    "acquisition/browser_readiness.py": 702,
    "acquisition/browser_recovery.py": 723,
    "acquisition/browser_result_builder.py": 744,
    "core/config/extraction_rules/_detail.py": 1026,
    "enrichment/service.py": 903,
    "extraction/collectors/dom.py": 1062,
    "extraction/collectors/js_state.py": 914,
    "extraction/collectors/jsonld.py": 783,
    "extraction/contracts.py": 856,
    "extraction/engine.py": 1059,
    "extraction/entities.py": 850,
    "extraction/pipeline.py": 781,
    "extraction/result_building.py": 738,
    "extraction/validation.py": 743,
    "intelligence/service.py": 750,
    # LEARN-ONCE recipe tier: persist_learned_recipe + release payload building
    # + drift counter live here (no TOML manifest counterpart; this dict is the
    # sole ledger for this persistence module).
    "persistence/extraction_memory.py": 1375,
}
# SLICE-6 closeout reconciliation: probe_browser_readiness (30) was decomposed
# into _listing_discovery_signals/_listing_readiness_verdict and left the
# ledger. Four entries grew with the brand/field-state consolidation and are
# tracked for the next cleanup slice: infer_brand_from_product_url 69 -> 86,
# infer_brand_from_page_identity 38 -> 39, field_evidence_states 41 -> 46,
# projection_field_states 70 -> 78.
COMPLEX_FUNCTION_DEBT = {
    ("acquisition/browser_block_detection.py", "_block_policy_matches"): 32,
    ("acquisition/browser_capture.py", "_repair_truncated_json_prefix"): 30,
    ("acquisition/browser_detail.py", "_candidate_is_admitted"): 56,
    ("acquisition/browser_identity.py", "build_playwright_context_spec"): 22,
    ("acquisition/browser_listing_visual.py", "listing_visual_elements_html"): 22,
    ("acquisition/browser_page_helpers.py", "_select_primary_browser_html"): 22,
    ("acquisition/browser_readiness.py", "analyze_extractable_content"): 35,
    ("acquisition/browser_readiness.py", "_has_detail_dom_signals"): 22,
    ("acquisition/platform_policy.py", "detect_platform_family"): 24,
    ("acquisition/source_capabilities.py", "build_source_capability_diagnostics"): 26,
    ("core/records/confidence.py", "_field_penalties"): 23,
    ("core/records/divergence.py", "compare_records_to_projection"): 21,
    ("core/records/divergence.py", "_compare_variants"): 23,
    ("core/records/divergence.py", "_compare_assets"): 35,
    ("core/records/field_url_normalization.py", "canonical_public_record_url"): 30,
    ("core/records/js_state_scope.py", "path_product_identity_conflicts"): 21,
    ("core/records/normalizers/__init__.py", "normalize_decimal_price"): 26,
    ("core/records/normalizers/__init__.py", "normalize_value"): 27,
    ("core/records/schema_service.py", "_snapshot_to_resolved"): 29,
    ("core/records/structured_variant_state.py", "with_parent_variant_axes"): 21,
    ("core/records/url_identity.py", "_short_numeric_product_asset_conflicts"): 28,
    ("core/shared/field_coerce.py", "sanitize_option_scalar"): 32,
    ("core/shared/field_coerce_dispatch.py", "coerce_field_value"): 54,
    ("core/shared/field_coerce_text.py", "infer_brand_from_page_identity"): 39,
    ("core/shared/field_coerce_text.py", "infer_brand_from_product_url"): 86,
    ("core/shared/text_coerce.py", "is_title_noise"): 22,
    ("core/shared/url_utils.py", "extract_urls"): 25,
    ("core/extraction_memory/contract_runtime.py", "match_template"): 23,
    ("core/extraction_memory/contract_runtime.py", "resolved_contract_outcomes"): 23,
    ("crawl/crud.py", "create_crawl_run"): 23,
    ("crawl/profile/acquisition_contract.py", "build_success_acquisition_contract"): 22,
    ("crawl/sitemap_nav.py", "_looks_like_category_url"): 21,
    ("crawl/site_link_discovery.py", "discover_rendered_category_links"): 23,
    ("extraction/collectors/_helpers.py", "_subject_id"): 23,
    ("extraction/collectors/jsonld.py", "_variant"): 30,
    ("extraction/collectors/js_state.py", "network_row"): 41,
    ("extraction/collectors/js_state.py", "_looks_like_variant"): 23,
    ("extraction/engine.py", "_assess"): 27,
    ("extraction/entities.py", "_variant_groups"): 21,
    ("extraction/entities.py", "_variant_identity_keys"): 24,
    ("extraction/pipeline.py", "_flag_brand_conflicts"): 30,
    ("extraction/pipeline.py", "normalize_evidence"): 40,
    ("extraction/pipeline.py", "_title_flags"): 29,
    ("extraction/publication.py", "commerce_detail_projection"): 43,
    ("extraction/publication.py", "serialize_commerce_detail_projection"): 26,
    ("enrichment/service.py", "run_job"): 25,
    ("extraction/replay.py", "fixture_bundle_from_inputs"): 29,
    # Audit-fix reconciliation (2026-07-22): the seven resolution entries moved
    # from the retired god-package __init__ to the split modules, values
    # unchanged; enrichment run_job + intelligence _poll_candidates_and_score
    # entered with the Celery job migration (2.7).
    ("extraction/resolution/decisions.py", "_resolve_scalar"): 22,
    ("extraction/resolution/derived.py", "_semantic_derived_facts"): 25,
    ("extraction/resolution/derived.py", "_brand_from_title"): 22,
    (
        "extraction/resolution/offers.py",
        "_offer_atomic_price_currency_preferences",
    ): 22,
    ("extraction/resolution/price_units.py", "_price_unit_repairs"): 37,
    ("extraction/resolution/resolver.py", "resolve"): 31,
    ("extraction/resolution/variant_rollup.py", "_reconcile_variant_prices"): 25,
    ("extraction/resolution/variant_rollup.py", "_inherit_variant_offer_facts"): 22,
    ("extraction/result_building.py", "field_evidence_states"): 46,
    ("extraction/result_building.py", "projection_field_states"): 78,
    ("extraction/validation.py", "_validate_child_join_failures"): 33,
    ("extraction/validation.py", "_validate_availability_consistency"): 25,
    ("intelligence/discovery.py", "_parse_serpapi_immersive_results"): 33,
    ("intelligence/service.py", "_poll_candidates_and_score"): 25,
    ("intelligence/matching.py", "_apply_identity_floor"): 21,
    ("intelligence/matching.py", "extract_search_result_snapshot"): 22,
    ("observability/diagnose.py", "build_diagnosis"): 25,
    ("observability/run_report.py", "_root_causes"): 37,
    ("persistence/publish/metrics.py", "build_url_metrics"): 30,
}

LEGACY_RECORD_FIELD_COMPATIBILITY_OWNERS = {
    "core response shaping": "schemas/crawl.py",
    "canonical persistence": "crawl/pipeline/persistence.py",
}


def _class_owners(class_name: str) -> set[str]:
    owners: set[str] = set()
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.ClassDef) and node.name == class_name
            for node in ast.walk(tree)
        ):
            owners.add(path.relative_to(APP_ROOT).as_posix())
    return owners


def _physical_line_count(path: Path) -> int:
    return sum(
        bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines()
    )


def _parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function_parameter_names(relative_path: str, function_name: str) -> set[str]:
    path = APP_ROOT / relative_path
    tree = _parse_module(path)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != function_name:
            continue
        arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        return {argument.arg for argument in arguments}
    raise AssertionError(f"Function not found: {relative_path}:{function_name}")


PACKAGE_LOC_BUDGETS = {
    # Closeout hardening reconciliation: acquisition/crawl/core/intelligence
    # grew slightly with readiness terminal states, the bounded persist
    # lock-wait, and the discovery dependency-injection seams; extraction
    # ratcheted DOWN with the srcset helper dedup.
    # Run-lifecycle scalability reconciliation: crawl grew with the run queue
    # claim/lease, resume-seeding, and bounded-summary machinery (net of the
    # dead-code deletions); batch_runtime.py itself ratcheted back under the
    # 700-line oversized threshold.
    # Audit-fix reconciliation (2026-07-22, measured on working tree):
    # acquisition grew (16,828 -> 17,104) with the browser-pool collaborator
    # modules + SSRF redirect validation; extraction grew (16,437 -> 16,753)
    # with the resolution split modules; enrichment (2,057 -> 2,250) and
    # intelligence (3,277 -> 3,448) grew with the Celery job runners.
    # Budgets are only raised, never lowered.
    "acquisition": 17_104,
    "crawl": 9_250,
    "core": 20_761,
    "enrichment": 2_250,
    "connectors": 2_444,
    "intelligence": 3_448,
    "extraction": 16_753,
    "evaluation": 2_009,
}
# Audit-fix reconciliation (2026-07-22): total grew (86,376 -> 87,144) with
# the resolution split, browser-pool collaborators, SSRF hardening, and
# Celery job runners (net of the dead-code purge). Measured on working tree.
TOTAL_APP_LOC_BUDGET = 87_144


def test_production_package_loc_budgets() -> None:
    app_files = [
        path for path in APP_ROOT.rglob("*.py") if "__pycache__" not in path.parts
    ]
    assert sum(_physical_line_count(path) for path in app_files) <= TOTAL_APP_LOC_BUDGET
    for package, budget in PACKAGE_LOC_BUDGETS.items():
        package_root = APP_ROOT / package
        package_total = sum(
            _physical_line_count(path)
            for path in app_files
            if package_root in path.parents
        )
        assert package_total <= budget, (package, package_total, budget)


def test_no_new_oversized_modules() -> None:
    oversized = {
        path.relative_to(APP_ROOT).as_posix(): _physical_line_count(path)
        for path in APP_ROOT.rglob("*.py")
        if _physical_line_count(path) > 700
    }
    assert oversized.keys() == OVERSIZED_MODULE_DEBT.keys()
    assert all(
        lines <= OVERSIZED_MODULE_DEBT[path] for path, lines in oversized.items()
    )


def test_no_new_complex_functions() -> None:
    complex_functions: dict[tuple[str, str], int] = {}
    for path in APP_ROOT.rglob("*.py"):
        relative_path = path.relative_to(APP_ROOT).as_posix()
        for block in cc_visit(path.read_text(encoding="utf-8")):
            if block.complexity > 20:
                complex_functions[(relative_path, block.name)] = block.complexity
    assert complex_functions.keys() == COMPLEX_FUNCTION_DEBT.keys()
    assert all(
        complexity <= COMPLEX_FUNCTION_DEBT[key]
        for key, complexity in complex_functions.items()
    )


def test_legacy_record_columns_have_no_new_direct_consumers() -> None:
    pattern = re.compile(
        r"\b(?:record|row)\.(?:raw_data|discovered_data|source_trace|raw_html_path)\b"
    )
    owners = {
        path.relative_to(APP_ROOT).as_posix()
        for path in APP_ROOT.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }
    assert owners <= set(LEGACY_RECORD_FIELD_COMPATIBILITY_OWNERS.values())


@pytest.mark.parametrize(
    ("relative_path", "loader_name"),
    (
        ("api/records.py", "load_canonical_record_views"),
        ("connectors/public_api/extraction_service.py", "load_record_artifacts"),
        ("crawl/review/__init__.py", "load_record_artifacts"),
        ("persistence/record_export_service.py", "load_record_artifacts"),
    ),
)
def test_legacy_record_consumers_enter_through_canonical_reader(
    relative_path: str,
    loader_name: str,
) -> None:
    source = (APP_ROOT / relative_path).read_text(encoding="utf-8")
    assert loader_name in source


def test_config_is_owned_by_core_package() -> None:
    assert (APP_ROOT / "core" / "config" / "__init__.py").is_file()
    assert not (APP_ROOT / "core" / "config.py").exists()
    assert not (APP_ROOT / "services" / "config").exists()


def test_acquisition_is_owned_by_top_level_package() -> None:
    assert (APP_ROOT / "acquisition" / "planner.py").is_file()
    assert (APP_ROOT / "acquisition" / "executor.py").is_file()
    assert not (APP_ROOT / "services" / "acquisition").exists()
    assert not (APP_ROOT / "services" / "fetch").exists()


def test_acquisition_does_not_construct_beautifulsoup_trees() -> None:
    acquisition_root = APP_ROOT / "acquisition"
    for path in acquisition_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".", 1)[0] != "bs4" for alias in node.names
                ), path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".", 1)[0] != "bs4", path


def test_application_does_not_import_bs4() -> None:
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".", 1)[0] != "bs4" for alias in node.names
                ), path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".", 1)[0] != "bs4", path


def test_bs4_is_not_a_backend_dependency() -> None:
    pyproject = (APP_ROOT.parent / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "beautifulsoup4" not in pyproject
    assert "soupsieve" not in pyproject


def test_requested_fields_do_not_initiate_browser_acquisition() -> None:
    policy_text = (APP_ROOT / "acquisition" / "fetch" / "browser_policy.py").read_text(
        encoding="utf-8"
    )
    fetch_text = (APP_ROOT / "acquisition" / "fetch" / "fetch_context.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "requested_detail_fields_require_browser",
        "REQUESTED_FIELDS_BROWSER_REASON",
        "requested-fields",
    ):
        assert forbidden not in policy_text
        assert forbidden not in fetch_text


def test_extraction_is_owned_by_top_level_package() -> None:
    assert (APP_ROOT / "extraction" / "engine.py").is_file()
    assert not (APP_ROOT / "services" / "extraction").exists()


def test_crawl_and_workers_are_owned_by_top_level_packages() -> None:
    assert (APP_ROOT / "crawl" / "pipeline" / "extraction_loop.py").is_file()
    assert (APP_ROOT / "workers" / "celery_dispatcher.py").is_file()
    assert not (APP_ROOT / "services" / "crawl").exists()
    assert not (APP_ROOT / "services" / "pipeline").exists()
    assert not (APP_ROOT / "services" / "dispatch").exists()


def test_observability_is_owned_by_top_level_package() -> None:
    assert (APP_ROOT / "observability" / "diagnose.py").is_file()
    assert (APP_ROOT / "observability" / "run_report.py").is_file()
    assert not (APP_ROOT / "services" / "observability").exists()
    # The self-healing trace/audit/baseline layer was collapsed into the
    # self-contained diagnose.json + deterministic report.json pair.
    assert not (APP_ROOT / "observability" / "run_trace.py").exists()
    assert not (APP_ROOT / "observability" / "run_audit.py").exists()
    assert not (APP_ROOT / "observability" / "baseline.py").exists()
    assert not (APP_ROOT / "observability" / "artifact_reader.py").exists()


def test_intelligence_and_enrichment_are_top_level_packages() -> None:
    assert (APP_ROOT / "intelligence" / "matching.py").is_file()
    assert (APP_ROOT / "enrichment" / "deterministic.py").is_file()
    assert not (APP_ROOT / "services" / "product_intelligence").exists()
    assert not (APP_ROOT / "services" / "data_enrichment").exists()


def test_connectors_are_owned_by_top_level_package() -> None:
    assert (APP_ROOT / "connectors" / "llm" / "provider_client.py").is_file()
    adapter_dir = APP_ROOT / "connectors" / "adapters"
    assert not any(adapter_dir.glob("*.py"))
    assert not (APP_ROOT / "services" / "adapters").exists()
    assert not (APP_ROOT / "services" / "llm").exists()


def test_persistence_support_packages_are_top_level() -> None:
    assert (APP_ROOT / "persistence" / "url_result_artifacts.py").is_file()
    assert (APP_ROOT / "persistence" / "export" / "schema.py").is_file()
    assert (APP_ROOT / "persistence" / "publish" / "verdict.py").is_file()
    assert not (APP_ROOT / "services" / "storage").exists()
    assert not (APP_ROOT / "services" / "export").exists()
    assert not (APP_ROOT / "services" / "publish").exists()
    # Pages-scheme artifact storage collapsed into the single URL-result writer.
    assert not (APP_ROOT / "persistence" / "storage").exists()
    assert not (APP_ROOT / "persistence" / "artifact_store.py").exists()


def test_legacy_services_package_is_deleted() -> None:
    assert not (APP_ROOT / "services").exists()


def test_dead_acquisition_http_adapter_is_deleted() -> None:
    assert not (APP_ROOT / "acquisition" / "http_client.py").exists()


def test_runtime_compatibility_aliases_are_retired() -> None:
    import app.acquisition.acquirer as acquirer
    import app.acquisition.runtime_plan as runtime_plan
    import app.acquisition.traversal_helpers as traversal_helpers
    import app.acquisition.traversal_recovery as traversal_recovery

    assert not hasattr(runtime_plan, "AcquisitionPlan")
    assert not hasattr(runtime_plan, "AcquisitionPlanUpdates")
    assert not hasattr(acquirer, "AcquisitionResult")
    assert "checkpoint" not in acquirer.AcquisitionRequest.__dataclass_fields__
    assert not hasattr(traversal_helpers, "_wait_for_dom_mutation_settle")
    assert not hasattr(
        traversal_helpers,
        "wait_for_traversal_dom_mutation_settle",
    )
    assert not hasattr(traversal_recovery, "find_aom_actionable_locator")


def test_dead_checkpoint_parameters_are_retired() -> None:
    assert "checkpoint" not in _function_parameter_names(
        "crawl/pipeline/extraction_loop.py",
        "process_single_url",
    )
    assert "checkpoint" not in _function_parameter_names(
        "acquisition/browser_detail.py",
        "expand_all_interactive_elements",
    )


@pytest.mark.parametrize(
    ("class_name", "allowed"),
    (
        ("AcquisitionPlan", {"acquisition/contracts.py"}),
        ("AcquisitionIntent", {"acquisition/runtime_plan.py"}),
        ("AcquisitionResult", {"acquisition/contracts.py"}),
        ("PageAcquisitionResult", {"acquisition/acquirer.py"}),
        ("AttemptSpec", {"acquisition/contracts.py"}),
        ("AttemptResult", {"acquisition/contracts.py"}),
        ("CapabilityRequest", {"extraction/contracts.py"}),
        ("UrlResult", {"crawl/contracts.py"}),
        ("RunSummary", {"crawl/contracts.py"}),
    ),
)
def test_canonical_contract_owner_allowlist(
    class_name: str,
    allowed: set[str],
) -> None:
    owners = _class_owners(class_name)
    assert owners
    assert owners <= allowed
