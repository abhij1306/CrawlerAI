from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
OVERSIZED_MODULE_DEBT: set[str] = set()
LONG_FUNCTION_DEBT: set[tuple[str, str]] = set()

LEGACY_RECORD_FIELD_COMPATIBILITY_OWNERS = {
    "core response shaping": "schemas/crawl.py",
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


def _canonical_line_count(node: ast.AST) -> int:
    return len(ast.unparse(node).splitlines())


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
    "acquisition": 15_400,
    "crawl": 9_250,
    "core": 14_500,
    "enrichment": 2_150,
    "connectors": 2_700,
    "intelligence": 3_250,
    "extraction": 5_500,
}
TOTAL_APP_LOC_BUDGET = 62_600


def test_production_package_loc_budgets() -> None:
    app_trees = {
        path: _parse_module(path)
        for path in APP_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    assert sum(_canonical_line_count(tree) for tree in app_trees.values()) <= TOTAL_APP_LOC_BUDGET
    for package, budget in PACKAGE_LOC_BUDGETS.items():
        package_root = APP_ROOT / package
        package_total = sum(
            _canonical_line_count(tree)
            for path, tree in app_trees.items()
            if package_root in path.parents
        )
        assert package_total <= budget, (package, package_total, budget)


def test_no_new_oversized_modules() -> None:
    oversized = {
        path.relative_to(APP_ROOT).as_posix()
        for path in APP_ROOT.rglob("*.py")
        if _canonical_line_count(_parse_module(path)) > 700
    }
    assert oversized <= OVERSIZED_MODULE_DEBT


def test_no_new_long_functions() -> None:
    long_functions: set[tuple[str, str]] = set()
    for path in APP_ROOT.rglob("*.py"):
        tree = _parse_module(path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _canonical_line_count(node) > 100:
                long_functions.add((path.relative_to(APP_ROOT).as_posix(), node.name))
    assert long_functions <= LONG_FUNCTION_DEBT


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
        ("observability/run_audit.py", "load_canonical_record_views"),
        ("observability/run_llm_diagnosis.py", "load_record_artifacts"),
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
