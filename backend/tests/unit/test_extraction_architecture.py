from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.crawl import CrawlCreate
from app.connectors.public_api.extraction_service import _internal_surface
from app.extraction.contracts import (
    CommerceDetailRecord,
    Evidence,
    ExtractionResult,
    PublicRecord,
)
from app.extraction.documents import DocumentStore, HtmlDocument
from app.extraction.json_walk import walk_json
from app.extraction.replay import request_from_acquisition_result
from app.extraction.surfaces import Surface, parse_surface


ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "app"
EXTRACTION_ROOT = ROOT / "app" / "extraction"
SEMANTIC_SURFACE_MANIFEST = (
    ROOT / "app" / "core" / "config" / "extraction_semantic_surface.toml"
)
pytestmark = pytest.mark.unit


def _python_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if "__pycache__" not in path.parts]


def _parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _assigned_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
    names: set[str] = set()
    targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
    for target in targets:
        for assigned in ast.walk(target):
            if isinstance(assigned, ast.Name):
                names.add(assigned.id)
            elif isinstance(assigned, ast.Attribute):
                names.add(assigned.attr)
            elif isinstance(assigned, ast.Constant) and isinstance(assigned.value, str):
                names.add(assigned.value)
    if node.value is not None:
        for assigned in ast.walk(node.value):
            if isinstance(assigned, ast.Dict):
                names.update(
                    key.value
                    for key in assigned.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )
    return names


def _publish_function_names(trees: tuple[ast.Module, ...]) -> set[str]:
    names = {"_publish"}
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name in names or node.name.startswith("serialize_")
            ):
                names.update(
                    call.func.id
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                )
    return names


def _forbidden_publish_parameters(
    trees: tuple[ast.Module, ...], publish_functions: set[str]
) -> list[tuple[str, str]]:
    offenders: list[tuple[str, str]] = []
    forbidden_arguments = {"evidence", "entity_set", "entity_graph"}
    forbidden_types = {"Evidence", "EntitySet"}
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in publish_functions:
                continue
            for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                annotation = ast.unparse(arg.annotation) if arg.annotation else ""
                if arg.arg.lower() in forbidden_arguments or any(
                    name in annotation for name in forbidden_types
                ):
                    offenders.append((node.name, f"{arg.arg}:{annotation}"))
    return offenders


def _absolute_import_from(path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    module_parts = list(path.relative_to(ROOT).with_suffix("").parts)
    package_parts = module_parts if path.name == "__init__.py" else module_parts[:-1]
    keep = max(0, len(package_parts) - (node.level - 1))
    suffix = tuple(node.module.split(".")) if node.module else ()
    return ".".join((*package_parts[:keep], *suffix))


def test_surface_enum_is_exact_contract() -> None:
    assert {surface.value for surface in Surface} == {
        "ecommerce_listing",
        "ecommerce_detail",
        "job_listing",
        "job_detail",
    }
    with pytest.raises(ValueError):
        parse_surface("auto")
    with pytest.raises(ValueError):
        CrawlCreate(run_type="crawl", url="https://example.com", surface="auto")
    with pytest.raises(Exception):
        _internal_surface("ecommerce")


def test_extraction_result_owns_typed_records_without_parallel_replay() -> None:
    annotation = ExtractionResult.model_fields["records"].annotation
    assert "PublicRecord" in str(annotation)
    assert "replay" not in ExtractionResult.model_fields
    assert issubclass(CommerceDetailRecord, PublicRecord)


def test_extraction_result_exposes_phase1_contract_diagnostics() -> None:
    assert "manifest_context" in ExtractionResult.model_fields
    assert "failure_classifications" in ExtractionResult.model_fields
    assert "diagnostics" in ExtractionResult.model_fields


def test_new_extraction_imports_forbidden_parser_stack_only_in_document_store() -> None:
    forbidden = {"bs4", "lxml", "extruct", "glom", "jmespath"}
    for path in _python_files(EXTRACTION_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        assert imports.isdisjoint(forbidden), path
        if path.name != "documents.py":
            assert "selectolax" not in imports, path


def test_current_ecommerce_detail_path_uses_document_store_parser_only() -> None:
    forbidden = {"bs4", "lxml", "extruct", "glom", "jmespath", "selectolax"}
    for path in _python_files(EXTRACTION_ROOT):
        if path.name == "documents.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        assert imports.isdisjoint(forbidden), path


def test_document_store_parses_each_html_artifact_once() -> None:
    store = DocumentStore({"page": "<html><body><h1>One</h1></body></html>"})
    first = store.html("page")
    second = store.html("page")
    assert first is second
    assert first.css_first("h1").text() == "One"


def test_document_store_reuses_matching_canonical_document_only() -> None:
    html = "<html><body><h1>One</h1></body></html>"
    document = HtmlDocument("page", html)
    matching = DocumentStore(
        {"page": html},
        html_documents={"page": document},
    )
    changed = DocumentStore(
        {"page": html.replace("One", "Two")},
        html_documents={"page": document},
    )

    assert matching.html("page") is document
    assert changed.html("page") is not document
    assert changed.html("page").css_first("h1").text() == "Two"


def test_runtime_replay_reuses_matching_browser_document() -> None:
    html = "<html><body><h1>Trail Shoe</h1></body></html>"
    document = HtmlDocument("html", html)
    acquisition = SimpleNamespace(
        html=html,
        html_document=document,
        final_url="https://shop.test/products/trail-shoe",
        request=SimpleNamespace(run_id=7),
        status_code=200,
        method="browser",
        blocked=False,
        network_payloads=[],
        artifacts={},
    )

    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=acquisition.final_url,
        max_records=1,
    )

    assert request.artifact_reader.document_store.html("html") is document


def test_json_walker_emits_json_pointer_paths() -> None:
    nodes = list(walk_json({"@type": "Product", "offers": [{"price": "10"}]}))
    by_pointer = {node.pointer: node for node in nodes}
    assert "/offers/0/price" in by_pointer
    assert by_pointer["/offers/0/price"].ancestor_schema_types == ("Product",)


def test_evidence_requires_subject_id() -> None:
    assert Evidence.model_fields["subject_id"].is_required()


def test_platform_adapters_cannot_bypass_evidence_publication() -> None:
    legacy_adapter_dir = APP_ROOT / "services" / "adapters"
    assert not any(legacy_adapter_dir.glob("*.py"))

    adapter_dir = APP_ROOT / "connectors" / "adapters"
    for path in adapter_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "app.persistence" not in source
        assert "app.extraction.publication" not in source


def test_surface_inference_modules_are_deleted() -> None:
    forbidden_files = {
        APP_ROOT / "services" / "surface_resolver.py",
        APP_ROOT / "services" / "config" / "surface_detection.py",
        APP_ROOT / "services" / "config" / "surface_hints.py",
        APP_ROOT / "services" / "extract" / "detail",
        APP_ROOT / "services" / "listing_extractor.py",
        APP_ROOT / "services" / "extract" / "listing_candidate_ranking.py",
        APP_ROOT / "services" / "extract" / "listing_card_fragments.py",
        APP_ROOT / "services" / "extract" / "listing_integrity_gate.py",
        APP_ROOT / "services" / "extract" / "network_listing_mapper.py",
        APP_ROOT / "services" / "extract" / "structured_listing_handler.py",
    }
    assert not any(path.exists() for path in forbidden_files)
    forbidden_terms = {
        "resolve_auto_surface",
        "resolve_surface",
        "infer_surface_from_body",
        "AUTO_SURFACE",
        "surface_group",
    }
    for path in _python_files(APP_ROOT):
        text = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text, path


# Domains that may legitimately appear as string constants in extraction
# (test/example hosts, never a real retailer). Keep this set as small as
# possible — a growing allow-set means site-specific logic is creeping back in.
_ALLOWED_DOMAIN_LITERALS = frozenset({"example.com", "example.in"})

# Hostname-like literal ending in a commercial TLD. `.org` is intentionally
# excluded so schema.org / w3.org vocabulary URLs never trip the ratchet.
_RETAILER_DOMAIN_RE = re.compile(
    r"\b[a-z0-9][a-z0-9-]*\.(?:com|in|net|io|shop|store|co)\b"
)


def test_extraction_carries_no_retailer_domain_literals() -> None:
    """Extraction must stay site-agnostic: no hardcoded retailer hostnames.

    Site-specific behaviour belongs in operator-promoted extraction contracts
    (feature spec §5/§6.1), never in `if host == "somestore.com"` branches.
    This scans *string constants only* — comments (e.g. the `firstcry.com →
    INR` note in pipeline.py) describe intent and are allowed.
    """
    offenders: list[tuple[Path, int, str]] = []
    for path in _python_files(EXTRACTION_ROOT):
        tree = _parse_module(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for match in _RETAILER_DOMAIN_RE.findall(node.value.lower()):
                if match not in _ALLOWED_DOMAIN_LITERALS:
                    offenders.append((path, node.lineno, match))
    assert not offenders, offenders


# Distinctive proper nouns from the 90-URL accuracy audit sample (brands,
# retailers, product codes). Rule tables are tuned on *evidence shape*, never on
# the audit corpus — so none of these may appear as a string constant in the
# extraction rule tables. Tokens are deliberately distinctive (not common web
# vocabulary like "target"/"image") so a whole-word match cannot false-positive
# on structural attribute names. A failure means matrix-tuned, site-specific
# vocabulary has leaked into the generic rules.
_MATRIX_TUNED_TOKENS = frozenset(
    {
        "rolex",
        "brooklinen",
        "backmarket",
        "shoepalace",
        "playstation",
        "nordstrom",
        "firstcry",
        "ilce",
    }
)
_MATRIX_TUNED_RE = re.compile(
    r"\b(?:" + "|".join(sorted(_MATRIX_TUNED_TOKENS)) + r")\b"
)
_EXTRACTION_RULES_ROOT = APP_ROOT / "core" / "config" / "extraction_rules"
_EXTRACTION_PRICE_RULES = APP_ROOT / "core" / "config" / "extraction_price_rules.py"


def test_extraction_rules_have_no_matrix_tuned_constants() -> None:
    """Generic rule tables must not encode audit-sample-specific vocabulary.

    The extraction rules key on structural signals only (schema.org enums, ISO
    currencies, generic UI tokens). This ratchet scans *string constants* in the
    rule-table modules for distinctive brand/retailer/product proper nouns from
    the accuracy-audit corpus; any hit means a rule was tuned to the sample
    rather than to evidence shape. Comments (intent notes) are not scanned.
    """
    rule_files = list(_python_files(_EXTRACTION_RULES_ROOT))
    if _EXTRACTION_PRICE_RULES.exists():
        rule_files.append(_EXTRACTION_PRICE_RULES)
    offenders: list[tuple[Path, int, str]] = []
    for path in rule_files:
        tree = _parse_module(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for match in _MATRIX_TUNED_RE.findall(node.value.lower()):
                offenders.append((path, node.lineno, match))
    assert not offenders, offenders


def test_extraction_hot_path_never_imports_grounded_llm_repair() -> None:
    """Phase 7: the LLM may propose grounded repairs offline, never in the hot path.

    Extraction must not import any LLM connector, so a model can never publish or
    activate a value inside a live extraction run.
    """
    forbidden_prefixes = ("app.connectors.llm",)
    offenders: list[tuple[Path, str]] = []
    for path in _python_files(EXTRACTION_ROOT):
        tree = _parse_module(path)
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = _absolute_import_from(path, node)
                modules.add(module)
                modules.update(f"{module}.{alias.name}" for alias in node.names)
        for module in modules:
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            ):
                offenders.append((path, module))
    assert not offenders, offenders


def test_relative_import_resolution_uses_extraction_package_context() -> None:
    node = ast.parse("from ..connectors import llm").body[0]
    assert isinstance(node, ast.ImportFrom)
    assert _absolute_import_from(EXTRACTION_ROOT / "probe.py", node) == "app.connectors"


def test_extraction_does_not_import_extraction_memory_storage() -> None:
    """Extraction reads frozen pure contracts, never mutable memory storage."""
    forbidden_prefixes = (
        "app.persistence.extraction_memory",
        "app.models.extraction_memory",
    )
    offenders: list[tuple[Path, str]] = []
    for path in _python_files(EXTRACTION_ROOT):
        for module in _imported_modules(_parse_module(path)):
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            ):
                offenders.append((path, module))
    assert not offenders, offenders


def test_phase4_evaluation_modules_are_offline_only() -> None:
    import app.evaluation as evaluation_package

    package_exports = set(getattr(evaluation_package, "__all__", ()))
    for runtime_alias in (
        "CompactPageRepresentation",
        "ModelPrediction",
        "OfflineHarnessResult",
        "benchmark_universal_model",
    ):
        assert not hasattr(evaluation_package, runtime_alias)
        assert runtime_alias not in package_exports

    forbidden_prefixes = (
        "app.evaluation.compact_representation",
        "app.evaluation.model_harness",
        "app.evaluation.partitions",
        "app.evaluation.benchmark",
    )
    evaluation_root = APP_ROOT / "evaluation"
    offenders: list[tuple[Path, str]] = []
    for path in _python_files(APP_ROOT):
        if evaluation_root in path.parents:
            continue
        for module in _imported_modules(_parse_module(path)):
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            ):
                offenders.append((path, module))
    assert not offenders, offenders


def test_runtime_model_fallback_cannot_resolve_publish_or_persist() -> None:
    path = APP_ROOT / "extraction" / "model_runtime.py"
    tree = _parse_module(path)
    forbidden_prefixes = (
        "app.extraction.resolution",
        "app.extraction.publication",
        "app.persistence",
    )
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    offenders = tuple(
        sorted(
            module
            for module in imports
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            )
        )
    )
    assert offenders == ()


def test_universal_model_config_does_not_live_in_extraction_service_code() -> None:
    service_paths = (
        APP_ROOT / "extraction" / "engine.py",
        APP_ROOT / "extraction" / "model_runtime.py",
    )
    forbidden_assignment_names = {
        "timeout_ms",
        "confidence_threshold",
        "max_memory_mb",
        "max_cost_per_page_usd",
    }
    offenders: list[tuple[Path, int, str]] = []
    for path in service_paths:
        assignments = (
            node
            for node in ast.walk(_parse_module(path))
            if isinstance(node, (ast.Assign, ast.AnnAssign))
        )
        for node in assignments:
            offenders.extend(
                (path, node.lineno, name)
                for name in sorted(_assigned_names(node) & forbidden_assignment_names)
            )
    assert offenders == []


def test_obsolete_pipeline_semantic_owners_are_deleted() -> None:
    forbidden_files = {
        APP_ROOT / "crawl" / "pipeline" / "direct_record_fallback.py",
        APP_ROOT / "crawl" / "pipeline" / "extraction_retry_decision.py",
        APP_ROOT / "crawl" / "pipeline" / "listing_escalation_decision.py",
        APP_ROOT / "crawl" / "pipeline" / "raw_json.py",
        APP_ROOT / "crawl" / "pipeline" / "sitemap.py",
    }
    assert not any(path.exists() for path in forbidden_files)
    pipeline_text = (APP_ROOT / "crawl" / "pipeline" / "extraction_loop.py").read_text(
        encoding="utf-8"
    )
    for term in (
        "validate_record_for_surface",
        "_quality_verdict",
        "extraction_replay",
        "apply_direct_record_llm_fallback",
    ):
        assert term not in pipeline_text


def test_extraction_semantic_surface_manifest_is_current() -> None:
    manifest = tomllib.loads(SEMANTIC_SURFACE_MANIFEST.read_text(encoding="utf-8"))
    paths = tuple(manifest["extraction_semantic_surface"]["paths"])
    assert paths == (
        "app/extraction",
        "app/core/records/divergence.py",
        "app/core/records/output_safety.py",
        "app/core/extraction_memory/contract_runtime.py",
        "app/core/shared/field_coerce*.py",
        "app/core/config/extraction_rules",
        "app/core/config/extraction_price_rules.py",
        "app/core/config/locale_format_rules.py",
        "app/core/config/variant_policy.py",
    )
    for raw_path in paths:
        matches = tuple(APP_ROOT.parent.glob(raw_path))
        assert matches, raw_path
    ratchets = manifest["ratchets"]
    assert (
        ratchets["semantic_derivation_owner"] == "app/extraction/resolution/__init__.py"
    )
    assert (
        ratchets["variant_eligibility_owner"] == "app/extraction/resolution/__init__.py"
    )
    assert ratchets["asset_selection_owner"] == "app/extraction/resolution/assets.py"
    assert ratchets["publication_owner"] == "app/extraction/publication.py"
    assert ratchets["post_resolution_mutation_allowed"] is False
    assert ratchets["contracts_bypass_ownership_allowed"] is False
    assert ratchets["persistence_extraction_repair_allowed"] is False
    assert ratchets["publish_receives_evidence_or_entity_graph"] is False


def test_publish_surface_does_not_receive_raw_evidence_or_entity_graph() -> None:
    modules = {
        "adapters": _parse_module(EXTRACTION_ROOT / "adapters.py"),
        "publication": _parse_module(EXTRACTION_ROOT / "publication.py"),
    }
    trees = tuple(modules.values())
    publish_functions = _publish_function_names(trees)
    offenders = _forbidden_publish_parameters(trees, publish_functions)
    assert not offenders


def test_publication_is_the_only_typed_record_producer() -> None:
    # Every surface record type must be instantiated in exactly one module:
    # publication.py. LEARN-ONCE recipe replay only produces Evidence and flows
    # through the normal adapter resolve -> publish path, so publication.py
    # remains the sole typed-record producer for recipe-tier output too.
    surface_models = {
        "CommerceDetailRecord",
        "CommerceListingRecord",
        "JobDetailRecord",
        "JobListingRecord",
        "CommerceVariantRecord",
    }
    producers: set[str] = set()
    for path in _python_files(EXTRACTION_ROOT):
        tree = _parse_module(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Match both `Model(...)` and `Model.model_validate(...)` forms.
            if isinstance(func, ast.Name) and func.id in surface_models:
                producers.add(path.relative_to(EXTRACTION_ROOT).as_posix())
            elif (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in surface_models
            ):
                producers.add(path.relative_to(EXTRACTION_ROOT).as_posix())
    assert producers == {"publication.py"}, producers


def test_persistence_performs_no_extraction_repair() -> None:
    persistence = _parse_module(APP_ROOT / "crawl" / "pipeline" / "persistence.py")
    forbidden = {
        "public_record_firewall",
        "sanitize_materialized_record",
        "materialize_product_assets",
        "drop_unusable_variants",
        "variant_not_publicly_sellable",
        "variant_not_actionable",
    }
    referenced = {
        node.id for node in ast.walk(persistence) if isinstance(node, ast.Name)
    }
    referenced.update(
        node.attr for node in ast.walk(persistence) if isinstance(node, ast.Attribute)
    )
    referenced.update(
        alias.name.rsplit(".", 1)[-1]
        for node in ast.walk(persistence)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    )
    assert not forbidden.intersection(referenced)


def test_no_post_resolution_repair_scaffolding_remains() -> None:
    # The post-extraction repair era left `field_repair`/`self_heal` conduits in
    # persistence + the export projection with no producer anywhere. They were
    # deleted in Phase 0 / Slice 0.4; this proves they cannot silently return.
    # `resolution.py`'s legitimate in-authority price repair uses the distinct
    # `repair_price_unit` / `_price_unit_repairs` names, which do not match.
    forbidden_tokens = ("field_repair", "self_heal")
    offenders = {
        path.relative_to(APP_ROOT).as_posix()
        for path in APP_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and any(token in path.read_text(encoding="utf-8") for token in forbidden_tokens)
    }
    assert not offenders
