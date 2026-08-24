from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from radon.complexity import cc_visit

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
IMMUTABLE_MIGRATION_ROOT = BACKEND_ROOT / "alembic" / "versions"
TEST_TOOL_COMPLEXITY_LIMIT = 15
# SLICE-6 closeout reconciliation: measured against the working tree after the
# cascade refactor/reformat. Net ratchet-DOWN — seven modules (browser_capture,
# browser_pool, cookie_store, browser_attempt_runner, intelligence/discovery,
# intelligence/matching, schemas/crawl) dropped below the 700-line threshold
# and left the ledger; most survivors shrank.
OVERSIZED_MODULE_DEBT = {
    # Extraction runtime simplification (2026-08-22): _detail.py left the
    # ledger; field_mappings.py and publication.py entered after rules and
    # projection steps moved to their canonical owners. Extraction entries
    # are reconciled to the readable CC<=15 implementation authorized in #48.
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
    # Audit-debt Stream B commit 5 (2026-07-22): browser_recovery.py left the
    # ledger (723 -> 681 after the type_text_like_human smoke-symbol deletion,
    # 3.14).
    # Stream B commit 10 (same day): browser_recovery.py re-entered (681 ->
    # 728) and browser_capture.py entered (699 -> 704) with the silent-except
    # diagnostics (4.8); browser_readiness +13, collectors/dom +7 — all raised
    # to measured.
    "acquisition/browser_capture.py": 704,
    "acquisition/browser_recovery.py": 728,
    "core/config/field_mappings.py": 704,
    "crawl/batch_runtime.py": 709,
    # Services/tooling simplification: LLM payload application moved to the
    # diagnostics owner and product execution was flattened; the cohesive job
    # lifecycle owner shrank from 905 to 708 nonblank lines.
    "enrichment/service.py": 708,
    "extraction/collectors/dom.py": 1115,
    "extraction/collectors/js_state.py": 996,
    # Stream B commit 14 (same day): jsonld.py re-keyed (783 -> 871) and
    # result_building.py re-keyed (738 -> 824) with the >150-line function
    # decompositions (4.15) — raised to measured.
    "extraction/collectors/jsonld.py": 919,
    "extraction/contracts.py": 787,
    "extraction/engine.py": 1067,
    "extraction/entities.py": 927,
    "extraction/pipeline.py": 893,
    "extraction/publication.py": 726,
    "extraction/result_building.py": 863,
    "extraction/validation.py": 777,
    # Services/tooling simplification: release compilation/loading, knowledge
    # projections, source preference shaping, and Sentinel observations moved
    # to named extraction-memory persistence owners. Transaction/lock/write
    # orchestration remains here and shrank from 1,394 to 752 nonblank lines.
    "persistence/extraction_memory.py": 752,
}
# Core/acquisition simplification (2026-08-23): every scoped callable is now
# CC<=15. Browser readiness state assembly moved to the existing page-helper
# owner; browser_readiness and browser_result_builder also left the size ledger.
# Extraction, core/acquisition, and services/tooling simplification have cleared
# every production callable above the legacy-debt threshold.
COMPLEX_FUNCTION_DEBT = {}

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


def _test_python_files() -> list[Path]:
    return sorted((BACKEND_ROOT / "tests").rglob("*.py"))


def _tool_python_files() -> list[Path]:
    return sorted(
        [
            *BACKEND_ROOT.glob("*.py"),
            *(BACKEND_ROOT / "browser_surface_probe").rglob("*.py"),
        ]
    )


def _maintainability_loc_excluded(path: Path) -> bool:
    return path == IMMUTABLE_MIGRATION_ROOT or IMMUTABLE_MIGRATION_ROOT in path.parents


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


def test_test_and_tool_callables_stay_within_complexity_limit() -> None:
    violations: list[tuple[str, str, int]] = []
    for path in [*_test_python_files(), *_tool_python_files()]:
        for block in cc_visit(path.read_text(encoding="utf-8")):
            if block.complexity > TEST_TOOL_COMPLEXITY_LIMIT:
                relative_path = path.relative_to(BACKEND_ROOT).as_posix()
                violations.append((relative_path, block.name, block.complexity))
    assert violations == []


def test_maintainability_loc_excludes_only_immutable_migrations() -> None:
    migration = IMMUTABLE_MIGRATION_ROOT / "20260703_0001_greenfield_schema.py"
    assert _maintainability_loc_excluded(migration)
    assert not _maintainability_loc_excluded(BACKEND_ROOT / "tests" / "conftest.py")
    assert not _maintainability_loc_excluded(BACKEND_ROOT / "run_extraction_smoke.py")
    assert not _maintainability_loc_excluded(APP_ROOT / "main.py")


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
