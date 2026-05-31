from __future__ import annotations

import pytest

import ast
import tomllib
from pathlib import Path

from app.core.database import Base
import app.models  # noqa: F401


ROOT = Path(__file__).resolve().parents[2]
SERVICES_ROOT = ROOT / "app" / "services"
APP_ROOT = ROOT / "app"
API_ROOT = APP_ROOT / "api"
TESTS_ROOT = ROOT / "tests"
REPO_ROOT = ROOT.parent
ROOT_SUPPORT_LOC_BUDGETS = {
    Path("harness_support.py"): 120,
    Path("run_browser_surface_probe.py"): 120,
}
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
ALLOWED_PRIVATE_SERVICE_IMPORTS = {
    # Existing relative private imports made visible by the audit ratchet.
    # Shrink this set when each owner promotes a real public API.
    "crawl/profile/acquisition_contract.py -> .normalization:_BROWSER_ENGINE_VALUES",
    "crawl/profile/acquisition_contract.py -> .normalization:_coerce_optional_choice",
    "crawl/profile/merge.py -> .normalization:_empty_acquisition_contract",
    "extract/field_candidates/structured_payloads.py -> .structured_values:_coerce_structured_candidate_value",
    "extract/field_candidates/structured_payloads.py -> .structured_values:_structured_alias_allowed",
    "extract/field_candidates/structured_payloads.py -> .structured_values:_structured_alias_value_allowed",
    "extract/field_candidates/structured_payloads.py -> .variant_rows:_structured_offer_variant_rows",
    "extract/field_candidates/structured_payloads.py -> .variant_rows:_structured_variant_rows",
    "extract/field_candidates/structured_payloads.py -> .variant_rows:_structured_variants_from_product_payload",
    "extract/field_candidates/structured_payloads.py -> .variant_rows:_variant_axes_from_rows",
    "extract/field_candidates/variant_rows.py -> .structured_values:_coerce_structured_candidate_value",
    # Package-private split modules behind stable public facades.
    "config/extraction_rules/__init__.py -> ._common:_STATIC_EXPORTS",
    "config/extraction_rules/__init__.py -> ._extra_exports:_EXTRA_EXPORTS",
    "js_state/state_normalizer/__init__.py -> ._common:_VARIANT_FIELD_SPEC",
    "js_state/state_normalizer/_facade.py -> ._identity:_mapped_product_family_matches",
    "js_state/state_normalizer/_facade.py -> ._identity:_mapped_product_identity_matches",
    "js_state/state_normalizer/_facade.py -> ._identity:_mapped_record_matches_page_url",
    "js_state/state_normalizer/_facade.py -> ._identity:_merge_same_product_record",
    "js_state/state_normalizer/_facade.py -> ._identity:_merge_variant_fields",
    "js_state/state_normalizer/_facade.py -> ._payloads:_find_product_payloads",
    "js_state/state_normalizer/_facade.py -> ._payloads:_looks_like_product_payload",
    "js_state/state_normalizer/_facade.py -> ._payloads:_normalized_state_payload",
    "js_state/state_normalizer/_facade.py -> ._product_mapping:_map_product_payload",
    "js_state/state_normalizer/_payloads.py -> ._variant_rows:_product_variant_rows",
    "js_state/state_normalizer/_product_mapping.py -> ._variant_mapping:_connection_nodes",
    "js_state/state_normalizer/_product_mapping.py -> ._variant_mapping:_name_or_value",
    "js_state/state_normalizer/_product_mapping.py -> ._variant_mapping:_normalize_variant",
    "js_state/state_normalizer/_product_mapping.py -> ._variant_mapping:_option_names",
    "js_state/state_normalizer/_product_mapping.py -> ._variant_rows:_product_variant_rows",
    "js_state/state_normalizer/_variant_rows.py -> ._variant_mapping:_option_names",
    "js_state/state_normalizer/_variant_rows.py -> ._variant_mapping:_variant_axis_raw_value",
    "pipeline/extraction_loop.py -> .record_extraction_stage:_best_adapter_result",
    "pipeline/extraction_loop.py -> .record_extraction_stage:_extract_records_for_acquisition",
    "pipeline/extraction_loop.py -> .record_extraction_stage:_update_acquisition_contract_memory",
    "product_intelligence/service.py -> app.services.product_intelligence.discovery:_looks_like_product_detail_url",
}
ALLOWED_PRIVATE_TEST_IMPORTS: set[str] = {
    "tests/component/test_alert_service.py -> app.services.alert_service:_rules_payload",
    "tests/regression/test_listing_identity_regressions.py -> app.services.extract.detail.identity.core:_detail_model_number_sets_compatible",
    "tests/component/test_public_api.py -> app.main:_public_auth_session",
    "tests/component/test_public_api.py -> app.api.public.rate_limit:_retry_after",
    "tests/component/test_public_api.py -> app.api.public.rate_limit:_trim",
    "tests/component/test_sitemap_resolver.py -> app.services.crawl.sitemap_resolver:_normalize_sitemap_url",
    "tests/component/test_playground_service.py -> app.services.playground_service:_classify_input_url",
    "tests/component/test_playground_service.py -> app.services.playground_service:_merge_seed_detail_products",
    "tests/unit/test_content_article_forum_surfaces.py -> app.services.pipeline.retry.stage:_apply_detail_rejection_guard",
    "tests/unit/test_detail_image_cleanup.py -> app.services.extract.detail.images.cleanup:_detail_image_candidate_is_usable",
    "tests/unit/test_materials_sanitizer.py -> app.services.extract.detail.text.sanitizer:_clean_materials_pollution",
    "tests/unit/test_normalizers.py -> app.services.extract.variant_choice_traversal:_variant_choice_container_is_overbroad",
    "tests/component/test_product_intelligence.py -> app.services.product_intelligence.discovery:_candidate_dedupe_key",
    "tests/component/test_public_api.py -> app.main:_crawler_app_state",
    "tests/services/observability/test_extraction_trace_projection.py -> app.services.pipeline.extraction_loop:_record_extraction_trace",
}
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
    ("playground_service.py", "SITEMAP_DISPLAY_LIMIT"),
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


@pytest.mark.regression
def test_detail_package_keeps_public_reexports() -> None:
    from app.services.extract import detail

    assert callable(detail.backfill_detail_price_from_html)
    assert callable(detail.repair_ecommerce_detail_record_quality)
    assert callable(detail.currency_hint_from_page_url)
    assert callable(detail.drop_low_signal_zero_detail_price)


@pytest.mark.regression
def test_variant_normalization_common_keeps_compatibility_reexports() -> None:
    from app.services.extract.variant_normalization import common
    from app.services.extract.variant_normalization.contract import (
        flatten_variants_for_public_output,
    )

    assert (
        common.flatten_variants_for_public_output is flatten_variants_for_public_output
    )


# Keep explicit budgets for coherent large owners. Budgets are set to roughly the
# current LOC plus 10% so growth requires a conscious update instead of a blanket
# threshold increase.
FILE_LOC_BUDGETS = {
    # Browser identity owns native Playwright context spec construction.
    Path("app/services/acquisition/browser_identity.py"): 175,
    # Browser runtime owns fetch orchestration; pooled lifecycle lives in browser_pool.py.
    Path("app/services/acquisition/browser_runtime.py"): 1050,
    # Page flow owns navigation/readiness; final result shaping lives in browser_result_builder.py.
    Path("app/services/acquisition/browser_page_flow.py"): 1000,
    # Traversal owns mode orchestration; helper/recovery mechanics live beside it.
    Path("app/services/acquisition/traversal.py"): 1000,
    # Config extraction rules are split by concern behind a stable package facade.
    Path("app/services/config/extraction_rules/__init__.py"): 80,
    Path("app/services/config/extraction_rules/_common.py"): 330,
    Path("app/services/config/extraction_rules/_detail.py"): 560,
    Path("app/services/config/extraction_rules/_detail_sections.py"): 80,
    Path("app/services/config/extraction_rules/_extra_exports.py"): 280,
    Path("app/services/config/extraction_rules/_images.py"): 100,
    Path("app/services/config/extraction_rules/_jobs.py"): 80,
    Path("app/services/config/extraction_rules/_listing_structured.py"): 650,
    Path("app/services/config/extraction_rules/_variants.py"): 340,
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
    Path("app/services/extract/detail/price/core.py"): 1085,
    Path("app/services/extract/detail/identity/core.py"): 1305,
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
    Path("app/services/extract/variant_identity_merge.py"): 500,
    # Listing extraction is the orchestration facade; card/title/image/brand
    # signal ownership lives in extract/listing_signals.py.
    Path("app/services/listing_extractor.py"): 900,
    Path("app/services/extract/listing_signals.py"): 650,
    # Canonical field coercion remains centralized here instead of scattering value policy.
    # Shrunk after removing stranded URL helpers and duplicate output schema checks.
    Path("app/services/dom/selector_engine.py"): 1000,
    Path("app/services/extract/detail_candidate_collection.py"): 610,
    Path("app/services/extract/detail_structured_pruning.py"): 300,
    Path("app/services/extract/detail_dom_completion.py"): 360,
    Path("app/services/extract/detail_image_materialize.py"): 130,
    Path("app/services/extract/detail_record_assembly.py"): 495,
    # Ratcheted for explicit typed fetch_page API compatibility.
    Path("app/services/fetch/fetch_context.py"): 1150,
    Path("app/services/js_state/state_normalizer/__init__.py"): 80,
    Path("app/services/js_state/state_normalizer/_common.py"): 120,
    Path("app/services/js_state/state_normalizer/_facade.py"): 180,
    Path("app/services/js_state/state_normalizer/_identity.py"): 240,
    Path("app/services/js_state/state_normalizer/_payloads.py"): 260,
    Path("app/services/js_state/state_normalizer/_product_mapping.py"): 460,
    Path("app/services/js_state/state_normalizer/_variant_mapping.py"): 280,
    Path("app/services/js_state/state_normalizer/_variant_rows.py"): 390,
    Path("app/services/product_intelligence/discovery.py"): 1320,
    Path("app/services/extract/detail/variants/dom_extraction.py"): 1150,
    # Extraction loop owns stage orchestration; retry and record extraction stages are split out.
    Path("app/services/pipeline/extraction_loop.py"): 1000,
    # Run progress owns batch-level summary/merge/quality aggregation, evicted
    # from the ORM layer so business logic does not live in models/crawl.py.
    Path("app/services/pipeline/run_progress.py"): 365,
    Path("app/services/shared/field_coerce.py"): 1080,
    Path("app/services/selectors_runtime.py"): 600,
    Path("app/services/selector_suggestions.py"): 250,
    # Enrichment service owns job orchestration and delegates deterministic normalization.
    # Data enrichment quality plan added prompt-context validation and optional semantic tags.
    Path("app/services/data_enrichment/service.py"): 825,
    Path("app/services/data_enrichment/deterministic.py"): 890,
    # LLM task runtime now only orchestrates task execution. Prompt rendering,
    # payload validation, provider calls, budget/cache, and cost logging have
    # separate owners.
    # Ratcheted for config_snapshot-aware LLM task runtime.
    Path("app/services/llm/tasks.py"): 460,
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
        if node.module.startswith("app.services."):
            module_name = node.module
        elif node.level and node.module:
            module_name = "." * node.level + node.module
        else:
            continue
        for alias in node.names:
            if alias.name.startswith("_"):
                imports.add(f"{rel} -> {module_name}:{alias.name}")
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


@pytest.mark.regression
def test_service_files_stay_under_loc_budget() -> None:
    oversized: list[str] = []
    for path in SERVICES_ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        budget = _loc_budget_for(rel)
        if line_count > budget:
            oversized.append(f"{rel} has {line_count} LOC (budget {budget})")
    assert oversized == []


@pytest.mark.regression
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


@pytest.mark.regression
def test_root_support_facades_stay_thin() -> None:
    oversized: list[str] = []
    for rel, budget in ROOT_SUPPORT_LOC_BUDGETS.items():
        path = ROOT / rel
        assert path.exists()
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > budget:
            oversized.append(f"{rel} has {line_count} LOC (budget {budget})")
    assert oversized == []


@pytest.mark.regression
def test_api_routes_do_not_own_session_factory() -> None:
    offenders: list[str] = []
    for path in API_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "app.core.database":
                continue
            if any(alias.name == "SessionLocal" for alias in node.names):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


@pytest.mark.regression
def test_removed_architecture_audit_files_do_not_return() -> None:
    forbidden = [
        SERVICES_ROOT / "config" / "browser_init_scripts.py",
        SERVICES_ROOT / "pipeline" / "extraction_retry_stage.py",
    ]
    assert [str(path.relative_to(ROOT)) for path in forbidden if path.exists()] == []


@pytest.mark.regression
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


@pytest.mark.regression
def test_root_extraction_services_are_explicitly_owned() -> None:
    root_extraction_modules = {
        path.relative_to(ROOT)
        for path in SERVICES_ROOT.glob("*.py")
        if path.name.endswith("_extractor.py")
        or path.name in {"extraction_context.py", "structured_sources.py"}
    }
    assert root_extraction_modules == ALLOWED_ROOT_EXTRACTION_MODULES


@pytest.mark.regression
def test_xpath_service_lives_under_dom_bucket() -> None:
    assert not (SERVICES_ROOT / "xpath_service.py").exists()
    assert (SERVICES_ROOT / "dom" / "xpath_service.py").exists()


@pytest.mark.regression
def test_extraction_modules_do_not_import_llm_runtime_layers() -> None:
    offenders: list[str] = []
    for path in EXTRACTION_MODULES:
        imports = _module_imports(path)
        if any(module.startswith("app.services.llm") for module in imports):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


@pytest.mark.regression
def test_generic_extraction_modules_do_not_import_site_adapters() -> None:
    offenders: list[str] = []
    for path in GENERIC_EXTRACTION_MODULES:
        imports = _module_imports(path)
        if any(module.startswith("app.services.adapters.") for module in imports):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


@pytest.mark.regression
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


@pytest.mark.regression
def test_new_config_like_modules_stay_under_services_config() -> None:
    offenders = [
        _service_rel(path)
        for path in SERVICES_ROOT.rglob("*.py")
        if "config" not in path.relative_to(SERVICES_ROOT).parts
        if path.name in {"config.py", "settings.py", "constants.py"}
        or path.name.endswith("_constants.py")
    ]
    assert offenders == []


@pytest.mark.regression
def test_root_binary_assets_are_not_committed_without_context() -> None:
    forbidden = [
        path.name
        for path in REPO_ROOT.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    ]
    assert forbidden == []
    logo_path = REPO_ROOT / "docs" / "assets" / "crawlerai-logo.png"
    if logo_path.parent.exists():
        assert logo_path.exists()


@pytest.mark.regression
def test_config_modules_do_not_mutate_globals_from_export_data() -> None:
    offenders: list[str] = []
    for path in (SERVICES_ROOT / "config").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "globals":
                offenders.append(str(path.relative_to(ROOT)))
    assert sorted(offenders) == []


@pytest.mark.regression
def test_pylint_useful_checks_are_not_blanket_disabled() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    disabled = set(
        pyproject.get("tool", {})
        .get("pylint", {})
        .get("messages_control", {})
        .get("disable", [])
    )
    forbidden = {
        "duplicate-code",
        "missing-function-docstring",
        "too-many-arguments",
        "too-many-branches",
        "too-many-lines",
        "too-many-locals",
        "too-many-return-statements",
        "too-many-statements",
    }
    assert disabled & forbidden == set()


@pytest.mark.regression
def test_high_risk_services_do_not_use_broad_exception_catches() -> None:
    high_risk_paths = [
        SERVICES_ROOT / "alert_service.py",
        SERVICES_ROOT / "acquisition" / "traversal_helpers.py",
        SERVICES_ROOT / "acquisition" / "traversal_recovery.py",
        SERVICES_ROOT / "listing_extractor.py",
        SERVICES_ROOT / "llm" / "provider_client.py",
    ]
    offenders: list[str] = []
    for path in high_risk_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


@pytest.mark.regression
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


@pytest.mark.regression
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


@pytest.mark.regression
def test_flat_detail_modules_are_removed_after_decomposition() -> None:
    flat_detail_modules = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (SERVICES_ROOT / "extract").glob("detail_*.py")
    )
    assert flat_detail_modules == []


@pytest.mark.regression
def test_legacy_dispatcher_fallback_flag_is_removed() -> None:
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        if "legacy_inprocess_runner_enabled" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


@pytest.mark.regression
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


@pytest.mark.regression
def test_model_bootstrap_registers_domain_memory_tables() -> None:
    expected = {
        "domain_memory",
        "domain_run_profiles",
        "domain_cookie_memory",
        "domain_field_feedback",
        "host_protection_memory",
    }
    assert expected.issubset(Base.metadata.tables)


@pytest.mark.regression
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


@pytest.mark.regression
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


@pytest.mark.regression
def test_private_service_imports_do_not_drift() -> None:
    offenders: set[str] = set()
    for path in SERVICES_ROOT.rglob("*.py"):
        offenders.update(_private_service_imports(path))
    assert offenders == ALLOWED_PRIVATE_SERVICE_IMPORTS


@pytest.mark.regression
def test_private_test_imports_do_not_drift() -> None:
    offenders: set[str] = set()
    for path in TESTS_ROOT.rglob("*.py"):
        offenders.update(_private_app_imports(path))
    assert offenders == ALLOWED_PRIVATE_TEST_IMPORTS
