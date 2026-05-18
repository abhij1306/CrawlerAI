from __future__ import annotations

import ast
from pathlib import Path

from app.core.database import Base
import app.models  # noqa: F401


ROOT = Path(__file__).resolve().parents[2]
SERVICES_ROOT = ROOT / "app" / "services"
APP_ROOT = ROOT / "app"
API_ROOT = APP_ROOT / "api"
TESTS_ROOT = ROOT / "tests"
EXTRACTION_MODULES = [
    SERVICES_ROOT / "extraction_context.py",
    SERVICES_ROOT / "listing_extractor.py",
    SERVICES_ROOT / "pipeline" / "extract_records.py",
    SERVICES_ROOT / "structured_sources.py",
    SERVICES_ROOT / "extract" / "field_candidates" / "structured_payloads.py",
    SERVICES_ROOT / "extract" / "field_candidates" / "structured_values.py",
    SERVICES_ROOT / "extract" / "field_candidates" / "variant_rows.py",
]
GENERIC_EXTRACTION_MODULES = []
FIELD_POLICY_CONSUMERS = [
    SERVICES_ROOT / "crawl" / "crud.py",
    SERVICES_ROOT / "schema_service.py",
    SERVICES_ROOT / "review" / "__init__.py",
]
ALLOWED_PRIVATE_SERVICE_IMPORTS = set()
ALLOWED_PRIVATE_TEST_IMPORTS: set[str] = set()
ALLOWED_ROOT_EXTRACTION_MODULES = {
    # Slice 2 keeps this as the public listing orchestration facade.
    Path("app/services/listing_extractor.py"),
    # Canonical shared structured-source owner, explicitly out of this plan.
    Path("app/services/structured_sources.py"),
    # Shared extraction context types.
    Path("app/services/extraction_context.py"),
    # Generic script text extraction owner used by structured source parsing.
    Path("app/services/script_text_extractor.py"),
}
CONFIG_CONSTANT_NAME_MARKERS = (
    "SELECTOR",
    "TOKEN",
    "THRESHOLD",
    "TIMEOUT",
    "LIMIT",
    "RETRY",
    "PATH_MARKER",
)
ALLOWED_SERVICE_CONFIG_CONSTANTS = {
    ("acquisition/cookie_store.py", "_CHALLENGE_COOKIE_VALUE_TOKENS"),
    ("acquisition/cookie_store.py", "_CHALLENGE_LOCAL_STORAGE_NAME_TOKENS"),
    ("acquisition/cookie_store.py", "_CHALLENGE_LOCAL_STORAGE_VALUE_TOKENS"),
    ("acquisition/browser_readiness.py", "_ECOMMERCE_READY_CARD_SELECTORS"),
    ("dom/section_extraction.py", "_SECTION_CONTAINER_SELECTORS"),
    ("dom/section_extraction.py", "_SECTION_LABEL_SELECTOR"),
    ("shared/field_coerce.py", "_SIZE_REJECT_TOKENS_NORMALIZED"),
    ("normalizers/__init__.py", "_AVAILABILITY_TOKENS"),
    ("platform_policy.py", "_GENERIC_COMMERCE_TOKENS"),
    ("platform_policy.py", "_GENERIC_JOB_TOKENS"),
}
DEFAULT_LOC_BUDGET = 1000
PLAN_TARGET_LOC_BUDGETS = {
    # Verified Architecture Audit Remediation staged targets. These are not
    # blanket budgets: each matching slice must make the target enforceable.
    Path("app/services/listing_extractor.py"): 900,  # Slice 2 facade target.
    Path("app/services/pipeline/extract_records.py"): 700,  # Slice 3 target.
    Path(
        "app/services/extract/detail_candidate_collection.py"
    ): 1000,  # Slice 6 follow-up target.
    Path(
        "app/services/extract/detail_final_cleanup.py"
    ): 1000,  # Slice 7 follow-up target.
    Path("app/services/extract/detail_price_core.py"): 800,  # Slice 8 follow-up target.
    Path(
        "app/services/extract/detail_identity_core.py"
    ): 800,  # Slice 8 follow-up target.
    Path("app/services/selectors_runtime.py"): 600,  # Slice 12 target.
    Path("app/services/pipeline/extraction_loop.py"): 1000,  # Slice 12 target.
    Path("app/services/dom/selector_engine.py"): 1000,  # Slice 12 target.
    Path("app/services/acquisition/browser_runtime.py"): 1000,  # Slice 12 target.
    Path("app/services/acquisition/traversal.py"): 1000,  # Slice 12 target.
    Path("app/services/acquisition/browser_page_flow.py"): 1000,  # Slice 12 target.
    Path("app/services/fetch/fetch_context.py"): 1000,  # Slice 12 target.
    Path("app/services/data_enrichment/service.py"): 725,  # Slice 12 target.
    Path("app/api/crawls.py"): 500,  # Slice 12 target.
}


def test_detail_package_keeps_public_reexports() -> None:
    from app.services.extract import detail

    assert callable(detail.backfill_detail_price_from_html)
    assert callable(detail.repair_ecommerce_detail_record_quality)
    assert callable(detail.currency_hint_from_page_url)
    assert callable(detail.drop_low_signal_zero_detail_price)


def test_variant_normalization_common_keeps_compatibility_reexports() -> None:
    from app.services.extract.variant_normalization import common
    from app.services.extract.variant_normalization.contract import (
        flatten_variants_for_public_output,
    )

    assert common.flatten_variants_for_public_output is flatten_variants_for_public_output
# Keep explicit budgets for coherent large owners. Budgets are set to roughly the
# current LOC plus 10% so growth requires a conscious update instead of a blanket
# threshold increase.
FILE_LOC_BUDGETS = {
    # Browser identity owns UA/timezone/device/runtime surface shaping.
    Path("app/services/acquisition/browser_identity.py"): 1690,
    # Browser runtime owns fetch orchestration; pooled lifecycle lives in browser_pool.py.
    Path("app/services/acquisition/browser_runtime.py"): 1000,
    # Page flow owns navigation/readiness; final result shaping lives in browser_result_builder.py.
    Path("app/services/acquisition/browser_page_flow.py"): 1000,
    # Traversal owns mode orchestration; helper/recovery mechanics live beside it.
    Path("app/services/acquisition/traversal.py"): 1000,
    # Config owners.
    # Config rules own typed extraction constants and category/nav URL rules.
    Path("app/services/config/extraction_rules.py"): 1910,
    Path("app/services/pipeline/extract_records.py"): 700,
    Path("app/services/extract/detail_dom_section_targets.py"): 160,
    Path("app/services/extract/detail_dom_fallbacks.py"): 360,
    Path("app/services/extract/detail_dom_variant_coercion.py"): 340,
    Path("app/services/extract/detail_dom_variant_extraction.py"): 945,
    Path("app/services/extract/detail_final_cleanup.py"): 205,
    Path("app/services/extract/detail_record_sanitization.py"): 500,
    Path("app/services/extract/detail_money_repair.py"): 355,
    Path("app/services/extract/detail_variant_pruning.py"): 555,
    Path("app/services/extract/detail_image_cleanup.py"): 505,
    Path("app/services/extract/detail_price_core.py"): 1000,
    Path("app/services/extract/detail_identity_core.py"): 1000,
    # Extract decomposition plan Slice 2 follow-up: split stage owners must stay
    # small after variant_record_normalization.py was removed.
    Path("app/services/extract/variant_normalization/contract.py"): 400,
    Path("app/services/extract/variant_normalization/hydration.py"): 400,
    Path("app/services/extract/variant_normalization/sanitization.py"): 400,
    Path("app/services/extract/variant_normalization/deduplication.py"): 400,
    Path("app/services/extract/variant_normalization/backfill.py"): 400,
    Path("app/services/extract/variant_normalization/size_color_extraction.py"): 400,
    Path("app/services/extract/variant_axis.py"): 295,
    Path("app/services/extract/variant_option_value.py"): 260,
    Path("app/services/extract/variant_choice_traversal.py"): 905,
    Path("app/services/extract/variant_identity_merge.py"): 415,
    # Listing extraction is the orchestration facade; card/title/image/brand
    # signal ownership lives in extract/listing_signals.py.
    Path("app/services/listing_extractor.py"): 900,
    Path("app/services/extract/listing_signals.py"): 650,
    # Canonical field coercion remains centralized here instead of scattering value policy.
    # Shrunk after removing stranded URL helpers and duplicate output schema checks.
    # TODO(chore): baseline LOC drift here, then extract canonical_coercion /
    # field_recovery / availability_gate owners when scheduled.
    Path("app/services/dom/selector_engine.py"): 1000,
    Path("app/services/extract/detail_candidate_collection.py"): 610,
    Path("app/services/extract/detail_structured_pruning.py"): 300,
    Path("app/services/extract/detail_dom_completion.py"): 360,
    Path("app/services/extract/detail_image_materialize.py"): 130,
    Path("app/services/extract/detail_record_assembly.py"): 495,
    # Ratcheted for host-policy TTL compatibility and handoff failure isolation.
    Path("app/services/fetch/fetch_context.py"): 1000,
    Path("app/services/js_state/state_normalizer.py"): 1480,
    # Extraction loop owns stage orchestration; retry and record extraction stages are split out.
    Path("app/services/pipeline/extraction_loop.py"): 1000,
    # Run progress owns batch-level summary/merge/quality aggregation, evicted
    # from the ORM layer so business logic does not live in models/crawl.py.
    Path("app/services/pipeline/run_progress.py"): 365,
    Path("app/services/shared/field_coerce.py"): 1080,
    Path("app/services/selectors_runtime.py"): 600,
    Path("app/services/selector_suggestions.py"): 250,
    # Enrichment service owns job orchestration and delegates deterministic normalization.
    Path("app/services/data_enrichment/service.py"): 725,
    Path("app/services/data_enrichment/deterministic.py"): 725,
    # LLM task runtime now only orchestrates task execution. Prompt rendering,
    # payload validation, provider calls, budget/cache, and cost logging have
    # separate owners.
    Path("app/services/llm/tasks.py"): 455,
    # Product Intelligence service owns job + discovery orchestration with brand and enrichment LLM helpers.
    Path("app/services/product_intelligence/service.py"): 1105,
}
API_FILE_LOC_BUDGETS = {
    Path("app/api/crawls.py"): 500,
    Path("app/api/crawl_domain.py"): 250,
}


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _loc_budget_for(path: Path) -> int:
    return FILE_LOC_BUDGETS.get(path, DEFAULT_LOC_BUDGET)


def _service_rel(path: Path) -> str:
    return path.relative_to(SERVICES_ROOT).as_posix()


def _module_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _module_all_names(path: Path) -> tuple[str, ...] | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        value_node: ast.AST | None = None
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                value_node = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
            and node.value is not None
        ):
            value_node = node.value
        if value_node is None:
            continue
        try:
            value = ast.literal_eval(value_node)
        except (TypeError, ValueError, SyntaxError):
            return None
        if not isinstance(value, (tuple, list)):
            return None
        if not all(isinstance(name, str) and name for name in value):
            return None
        return tuple(value)
    return None


def _private_service_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    rel = _service_rel(path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("app.services."):
            continue
        for alias in node.names:
            if alias.name.startswith("_"):
                imports.add(f"{rel} -> {node.module}:{alias.name}")
    return imports


def _private_app_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    rel = path.relative_to(ROOT).as_posix()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("app."):
            continue
        for alias in node.names:
            if alias.name.startswith("_"):
                imports.add(f"{rel} -> {node.module}:{alias.name}")
    return imports


def test_service_files_stay_under_loc_budget() -> None:
    oversized: list[str] = []
    for path in SERVICES_ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        budget = _loc_budget_for(rel)
        if line_count > budget:
            oversized.append(f"{rel} has {line_count} LOC (budget {budget})")
    assert oversized == []


def test_api_files_stay_under_loc_budget() -> None:
    oversized: list[str] = []
    for path in API_ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        budget = API_FILE_LOC_BUDGETS.get(rel)
        if budget is None:
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > budget:
            oversized.append(f"{rel} has {line_count} LOC (budget {budget})")
    assert oversized == []


def test_audit_plan_targets_are_tracked_by_current_budgets() -> None:
    missing = set(PLAN_TARGET_LOC_BUDGETS) - set(FILE_LOC_BUDGETS)
    missing = {
        path
        for path in missing
        if (ROOT / path).exists()
        and len((ROOT / path).read_text(encoding="utf-8").splitlines())
        > DEFAULT_LOC_BUDGET
    }
    missing -= {Path("app/api/crawls.py")}
    assert missing == set()


def test_root_extraction_services_are_explicitly_owned() -> None:
    root_extraction_modules = {
        path.relative_to(ROOT)
        for path in SERVICES_ROOT.glob("*.py")
        if path.name.endswith("_extractor.py")
        or path.name in {"extraction_context.py", "structured_sources.py"}
    }
    assert root_extraction_modules == ALLOWED_ROOT_EXTRACTION_MODULES


def test_xpath_service_lives_under_dom_bucket() -> None:
    assert not (SERVICES_ROOT / "xpath_service.py").exists()
    assert (SERVICES_ROOT / "dom" / "xpath_service.py").exists()


def test_extraction_modules_do_not_import_llm_runtime_layers() -> None:
    offenders: list[str] = []
    for path in EXTRACTION_MODULES:
        imports = _module_imports(path)
        if any(module.startswith("app.services.llm") for module in imports):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_generic_extraction_modules_do_not_import_site_adapters() -> None:
    offenders: list[str] = []
    for path in GENERIC_EXTRACTION_MODULES:
        imports = _module_imports(path)
        if any(module.startswith("app.services.adapters.") for module in imports):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_field_policy_is_the_only_field_rule_entrypoint() -> None:
    assert not (SERVICES_ROOT / "field_alias_policy.py").exists()
    assert not (SERVICES_ROOT / "requested_field_policy.py").exists()
    assert not (SERVICES_ROOT / "simple_crawler.py").exists()

    missing_imports: list[str] = []
    for path in FIELD_POLICY_CONSUMERS:
        imports = _module_imports(path)
        if "app.services.field_policy" not in imports:
            missing_imports.append(str(path.relative_to(ROOT)))
    assert missing_imports == []


def test_new_config_like_modules_stay_under_services_config() -> None:
    offenders = [
        _service_rel(path)
        for path in SERVICES_ROOT.rglob("*.py")
        if "config" not in path.relative_to(SERVICES_ROOT).parts
        if path.name in {"config.py", "settings.py", "constants.py"}
        or path.name.endswith("_constants.py")
    ]
    assert offenders == []


def test_deleted_facades_do_not_return() -> None:
    def deleted_extract_module(*stem_parts: str) -> Path:
        return SERVICES_ROOT / "extract" / ("_".join(stem_parts) + ".py")

    stale_facades = [
        SERVICES_ROOT / "pipeline" / "core.py",
        deleted_extract_module("shared", "variant", "logic"),
        deleted_extract_module("variant", "grouping"),
        deleted_extract_module("detail", "materializer"),
        deleted_extract_module("detail", "dom", "extractor"),
        deleted_extract_module("detail", "dom", "context"),
        deleted_extract_module("detail", "record", "finalizer"),
        deleted_extract_module("detail", "identity"),
        deleted_extract_module("detail", "price", "extractor"),
    ]
    assert [
        str(path.relative_to(ROOT)) for path in stale_facades if path.exists()
    ] == []


def test_extract_modules_declare_public_surface() -> None:
    missing: set[str] = set()
    for path in (SERVICES_ROOT / "extract").rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        if "field_candidates" in path.relative_to(SERVICES_ROOT).parts:
            continue
        if not _module_all_names(path):
            missing.add(rel)
    assert missing == set()


def test_flat_detail_modules_are_removed_after_decomposition() -> None:
    flat_detail_modules = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (SERVICES_ROOT / "extract").glob("detail_*.py")
    )
    assert flat_detail_modules == []


def test_legacy_dispatcher_fallback_flag_is_removed() -> None:
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        if "legacy_inprocess_runner_enabled" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_retired_legacy_shims_do_not_return() -> None:
    forbidden = (
        "_LEGACY_PROMPTS_DIR",
        "_legacy_artifact_paths",
        "legacy_artifacts_removed",
        "legacy_keys",
        "legacy_aliases",
    )
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)}:{token}")
    assert offenders == []


def test_model_bootstrap_registers_domain_memory_tables() -> None:
    expected = {
        "domain_memory",
        "domain_run_profiles",
        "domain_cookie_memory",
        "domain_field_feedback",
        "host_protection_memory",
    }
    assert expected.issubset(Base.metadata.tables)


def test_new_service_level_config_constants_are_not_added_outside_config() -> None:
    offenders: list[str] = []
    for path in SERVICES_ROOT.rglob("*.py"):
        rel_parts = path.relative_to(SERVICES_ROOT).parts
        if "config" in rel_parts:
            continue
        rel = _service_rel(path)
        for name in _module_level_names(path):
            if not name.isupper():
                continue
            if not any(marker in name for marker in CONFIG_CONSTANT_NAME_MARKERS):
                continue
            if (rel, name) not in ALLOWED_SERVICE_CONFIG_CONSTANTS:
                offenders.append(f"{rel}:{name}")
    assert sorted(offenders) == []


def test_data_enrichment_taxonomy_matching_does_not_use_manual_category_alias_maps() -> (
    None
):
    config_text = (SERVICES_ROOT / "config" / "data_enrichment.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "DATA_ENRICHMENT_TAXONOMY_TOKEN_ALIASES",
        "DATA_ENRICHMENT_TAXONOMY_CONTEXTUAL_TOKEN_ALIASES",
    )
    assert [name for name in forbidden if name in config_text] == []


def test_private_service_imports_do_not_drift() -> None:
    offenders: set[str] = set()
    for path in SERVICES_ROOT.rglob("*.py"):
        offenders.update(_private_service_imports(path))
    assert offenders == ALLOWED_PRIVATE_SERVICE_IMPORTS


def test_private_test_imports_do_not_drift() -> None:
    offenders: set[str] = set()
    for path in TESTS_ROOT.rglob("*.py"):
        offenders.update(_private_app_imports(path))
    assert offenders == ALLOWED_PRIVATE_TEST_IMPORTS
