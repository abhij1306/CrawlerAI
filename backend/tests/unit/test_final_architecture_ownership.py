from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
OVERSIZED_MODULE_DEBT = {
    "acquisition/browser_detail.py",
    "acquisition/browser_runtime.py",
    "acquisition/fetch/fetch_context.py",
    "acquisition/runtime.py",
    "crawl/batch_runtime.py",
    "enrichment/shopify_catalog.py",
}
LONG_FUNCTION_DEBT = {
    ("acquisition/browser_detail.py", "expand_all_interactive_elements_impl"),
    ("acquisition/browser_detail.py", "expand_interactive_elements_via_accessibility_impl"),
    ("acquisition/browser_page_flow.py", "settle_browser_page_impl"),
    ("acquisition/browser_page_helpers.py", "_capture_listing_visual_elements"),
    ("acquisition/browser_readiness.py", "probe_browser_readiness_impl"),
    ("acquisition/browser_recovery.py", "_emit_challenge_activity"),
    ("acquisition/browser_recovery.py", "recover_browser_challenge"),
    ("acquisition/browser_result_builder.py", "build"),
    ("acquisition/browser_runtime.py", "_maybe_warm_origin_before_navigation"),
    ("acquisition/browser_runtime.py", "browser_fetch"),
    ("acquisition/runtime.py", "classify_blocked_page"),
    ("acquisition/traversal.py", "_run_load_more_traversal"),
    ("acquisition/traversal.py", "_run_paginate_traversal"),
    ("acquisition/traversal.py", "_run_scroll_traversal"),
    ("acquisition/traversal_recovery.py", "click_with_retry"),
    ("acquisition/traversal_recovery.py", "dismiss_overlays_if_needed"),
    ("connectors/llm/tasks.py", "run_prompt_task"),
    ("connectors/public_api/extraction_service.py", "extract_public_product"),
    ("core/config/runtime_settings.py", "_apply_profile_defaults"),
    ("core/records/confidence.py", "score_record_confidence"),
    ("crawl/batch_runtime.py", "_process_run_with_span"),
    ("crawl/batch_runtime.py", "_process_urls_in_parallel"),
    ("crawl/pipeline/run_progress.py", "_merge_run_acquisition_metrics"),
    ("crawl/review/__init__.py", "build_domain_recipe_payload"),
    ("enrichment/shopify_catalog.py", "top_taxonomy_candidates"),
    ("intelligence/matching.py", "score_candidate"),
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


def test_no_new_oversized_modules() -> None:
    oversized = {
        path.relative_to(APP_ROOT).as_posix()
        for path in APP_ROOT.rglob("*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 700
    }
    assert oversized <= OVERSIZED_MODULE_DEBT


def test_no_new_long_functions() -> None:
    long_functions: set[tuple[str, str]] = set()
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            assert node.end_lineno is not None
            if node.end_lineno - node.lineno + 1 > 100:
                long_functions.add((path.relative_to(APP_ROOT).as_posix(), node.name))
    assert long_functions <= LONG_FUNCTION_DEBT


def test_config_is_owned_by_core_package() -> None:
    assert (APP_ROOT / "core" / "config" / "__init__.py").is_file()
    assert not (APP_ROOT / "core" / "config.py").exists()
    assert not (APP_ROOT / "services" / "config").exists()


def test_acquisition_is_owned_by_top_level_package() -> None:
    assert (APP_ROOT / "acquisition" / "planner.py").is_file()
    assert (APP_ROOT / "acquisition" / "executor.py").is_file()
    assert not (APP_ROOT / "services" / "acquisition").exists()
    assert not (APP_ROOT / "services" / "fetch").exists()


def test_requested_fields_do_not_initiate_browser_acquisition() -> None:
    policy_text = (
        APP_ROOT / "acquisition" / "fetch" / "browser_policy.py"
    ).read_text(encoding="utf-8")
    fetch_text = (
        APP_ROOT / "acquisition" / "fetch" / "fetch_context.py"
    ).read_text(encoding="utf-8")
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
    assert (APP_ROOT / "observability" / "run_trace.py").is_file()
    assert not (APP_ROOT / "services" / "observability").exists()


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
    assert (APP_ROOT / "persistence" / "storage" / "local.py").is_file()
    assert (APP_ROOT / "persistence" / "export" / "schema.py").is_file()
    assert (APP_ROOT / "persistence" / "publish" / "verdict.py").is_file()
    assert not (APP_ROOT / "services" / "storage").exists()
    assert not (APP_ROOT / "services" / "export").exists()
    assert not (APP_ROOT / "services" / "publish").exists()


def test_legacy_services_package_is_deleted() -> None:
    assert not (APP_ROOT / "services").exists()


@pytest.mark.parametrize(
    ("class_name", "allowed"),
    (
        (
            "AcquisitionPlan",
            {"acquisition/contracts.py", "acquisition/runtime_plan.py"},
        ),
        (
            "AcquisitionResult",
            {
                "acquisition/contracts.py",
                "acquisition/acquirer.py",
            },
        ),
        ("AttemptSpec", {"acquisition/contracts.py"}),
        ("AttemptResult", {"acquisition/contracts.py"}),
        ("CapabilityRequest", {"extraction/contracts.py"}),
        ("UrlResult", {"crawl/contracts.py"}),
        ("RunSummary", {"crawl/contracts.py"}),
        ("ArtifactManifest", {"persistence/contracts.py"}),
    ),
)
def test_canonical_contract_owner_allowlist(
    class_name: str,
    allowed: set[str],
) -> None:
    owners = _class_owners(class_name)
    assert owners
    assert owners <= allowed
