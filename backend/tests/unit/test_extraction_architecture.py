from __future__ import annotations

import ast
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
pytestmark = pytest.mark.unit


def _python_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


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


def test_legacy_record_producing_adapters_are_deleted() -> None:
    adapter_dir = APP_ROOT / "connectors" / "adapters"
    assert not any(adapter_dir.glob("*.py"))


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


def test_extraction_package_stays_within_architecture_limits() -> None:
    files = _python_files(EXTRACTION_ROOT)
    assert len(files) <= 24
    assert sum(len(path.read_text(encoding="utf-8").splitlines()) for path in files) <= 5500
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 400, path
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno is not None
                assert node.end_lineno - node.lineno + 1 <= 60, (
                    path,
                    node.name,
                )


def test_obsolete_pipeline_semantic_owners_are_deleted() -> None:
    forbidden_files = {
        APP_ROOT / "crawl" / "pipeline" / "direct_record_fallback.py",
        APP_ROOT / "crawl" / "pipeline" / "extraction_retry_decision.py",
        APP_ROOT / "crawl" / "pipeline" / "listing_escalation_decision.py",
        APP_ROOT / "crawl" / "pipeline" / "raw_json.py",
        APP_ROOT / "crawl" / "pipeline" / "sitemap.py",
    }
    assert not any(path.exists() for path in forbidden_files)
    pipeline_text = (
        APP_ROOT / "crawl" / "pipeline" / "extraction_loop.py"
    ).read_text(encoding="utf-8")
    for term in (
        "validate_record_for_surface",
        "_quality_verdict",
        "extraction_replay",
        "apply_direct_record_llm_fallback",
    ):
        assert term not in pipeline_text
