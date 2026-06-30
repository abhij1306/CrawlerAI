from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.crawl_run import CrawlRecord, CrawlUrlResult
from app.persistence.artifacts import ArtifactRepository
from app.persistence.record_artifacts import load_record_artifacts
from app.persistence.url_result_artifacts import publish_url_result_artifacts
from app.persistence.url_results import acquisition_outcome, url_result_values
from app.crawl.pipeline import persistence as record_persistence

pytestmark = pytest.mark.unit


def test_url_result_schema_owns_canonical_result_fields() -> None:
    columns = set(CrawlUrlResult.__table__.columns.keys())
    assert {
        "id",
        "run_id",
        "requested_url",
        "normalized_url",
        "final_url",
        "surface",
        "generation",
        "acquisition_outcome",
        "verdict",
        "extraction_version",
        "bundle_id",
        "manifest_uri",
        "record_count",
        "error",
    } <= columns
    assert "url_result_id" in CrawlRecord.__table__.columns
    assert any(
        index.name == "uq_crawl_url_results_identity" and index.unique
        for index in CrawlUrlResult.__table__.indexes
    )


def test_artifact_repository_writes_atomically_with_hash(tmp_path: Path) -> None:
    repository = ArtifactRepository(root_dir=tmp_path)
    content = b"canonical evidence"
    reference = repository.persist_bytes(
        run_id=7,
        url_result_id=9,
        name="evidence.jsonl",
        content=content,
    )
    target = tmp_path / reference.uri
    assert target.read_bytes() == content
    assert reference.sha256 == hashlib.sha256(content).hexdigest()
    assert not list(tmp_path.rglob("*.tmp"))


def test_artifact_repository_confines_uris_to_root(tmp_path: Path) -> None:
    repository = ArtifactRepository(root_dir=tmp_path)

    with pytest.raises(ValueError, match="escapes"):
        repository.resolve_uri("../outside.json")
    with pytest.raises(ValueError, match="relative"):
        repository.resolve_uri(str((tmp_path / "absolute.json").resolve()))
    with pytest.raises(ValueError, match="name"):
        repository.persist_bytes(
            run_id=7,
            url_result_id=9,
            name="../escape.json",
            content=b"{}",
        )


def test_canonical_url_artifacts_publish_minimal_extraction(tmp_path: Path) -> None:
    """Publisher emits exactly 3 files even when extraction has no records."""
    from app.extraction.contracts import ExtractionResult
    from app.extraction.surfaces import Surface

    acquisition = SimpleNamespace(
        final_url="https://example.test/p",
        html="<html>test</html>",
        method="httpx",
        status_code=200,
        content_type="text/html",
        blocked=False,
        platform_family=None,
        adapter_name=None,
        json_data=None,
        network_payloads=[],
        browser_diagnostics={},
        acquisition_diagnostics={},
        artifacts={},
    )
    extraction = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        verdict="success",
        bundle_id="test-bundle",
        records=(),
    )

    published = publish_url_result_artifacts(
        run_id=7,
        url_result_id=9,
        acquisition_result=acquisition,
        extraction_result=extraction,
        record_count=0,
        root_dir=tmp_path,
    )

    result_dir = tmp_path / published.result_root
    assert (result_dir / "page.html").is_file()
    assert (result_dir / "record.json").is_file()
    assert (result_dir / "diagnose.json").is_file()
    assert not (result_dir / "manifest.json").exists()
    assert not (result_dir / "screenshot.png").exists()
    files = sorted(result_dir.iterdir(), key=lambda p: p.name)
    assert [f.name for f in files] == ["diagnose.json", "page.html", "record.json"]


@pytest.mark.asyncio
async def test_record_artifact_reader_prefers_matching_canonical_provenance(
    tmp_path: Path,
) -> None:
    published = _publish_record_reader_fixture(tmp_path)
    record = SimpleNamespace(
        id=28,
        url_result_id=9,
        source_url="https://example.test/products/second",
        url_identity_key="identity-second",
        raw_data={"title": "Second raw"},
        discovered_data={"confidence": 0.9},
        source_trace={"acquisition": {"method": "httpx"}},
        raw_html_path=None,
    )
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(manifest_uri=published.result_root)

    artifacts = await load_record_artifacts(
        session,
        record,
        root_dir=tmp_path,
    )

    assert artifacts.status == "canonical"
    assert artifacts.html == "<html>canonical</html>"
    assert artifacts.raw_data == {"title": "Second raw"}
    assert artifacts.discovered_data == {"confidence": 0.9}
    assert artifacts.source_trace == {"acquisition": {"method": "httpx"}}


@pytest.mark.asyncio
async def test_record_artifact_reader_rejects_tampered_canonical_bundle(
    tmp_path: Path,
) -> None:
    published = _publish_record_reader_fixture(tmp_path)
    repository = ArtifactRepository(root_dir=tmp_path)
    page_uri = f"{published.result_root}/page.html"
    repository.resolve_uri(page_uri).write_text("tampered", encoding="utf-8")
    record = SimpleNamespace(
        id=27,
        url_result_id=9,
        source_url="https://example.test/products/widget",
        url_identity_key="identity-widget",
        raw_data={"title": "Widget raw"},
        discovered_data={"confidence": 0.8},
        source_trace={"acquisition": {"method": "curl"}},
        raw_html_path=None,
    )
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(manifest_uri=published.result_root)

    artifacts = await load_record_artifacts(
        session,
        record,
        root_dir=tmp_path,
    )

    assert artifacts.status == "canonical"
    assert artifacts.html == "tampered"


@pytest.mark.asyncio
async def test_record_artifact_reader_falls_back_only_without_manifest(
    tmp_path: Path,
) -> None:
    html_path = tmp_path / "runs" / "7" / "pages" / "legacy.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<html>legacy</html>", encoding="utf-8")
    record = SimpleNamespace(
        id=27,
        url_result_id=None,
        source_url="https://example.test/products/widget",
        url_identity_key="identity-widget",
        raw_data={"legacy": True},
        discovered_data={"confidence": 0.5},
        source_trace={"acquisition": {"method": "curl"}},
        raw_html_path=str(html_path),
    )
    session = AsyncMock()

    artifacts = await load_record_artifacts(
        session,
        record,
        root_dir=tmp_path,
    )

    assert artifacts.status == "legacy"
    assert artifacts.html == "<html>legacy</html>"
    assert artifacts.raw_data == {"legacy": True}
    session.get.assert_not_awaited()


def _publish_record_reader_fixture(
    tmp_path: Path,
    *,
    acquisition_diagnostics: dict[str, object] | None = None,
):
    acquisition = SimpleNamespace(
        final_url="https://example.test/products/widget",
        html="<html>canonical</html>",
        method="httpx",
        status_code=200,
        content_type="text/html",
        blocked=False,
        platform_family=None,
        adapter_name=None,
        json_data=None,
        network_payloads=[],
        browser_diagnostics={},
        acquisition_diagnostics=acquisition_diagnostics or {},
        artifacts={},
    )
    extraction = SimpleNamespace(
        bundle_id="bundle-reader",
        evidence=[],
        decisions=[],
        findings=[],
        verdict="success",
        data_integrity={},
        metrics=SimpleNamespace(model_dump=lambda **_: {}),
        field_states=[],
        collector_outcomes=[],
        stage_outcomes=[],
        contract_outcomes=[],
        model_dump=lambda **_: {
            "bundle_id": "bundle-reader",
            "evidence": [],
            "graph": {},
            "target": {},
            "findings": [],
            "decisions": [],
            "records": [],
            "verdict": "success",
            "metrics": {},
        },
    )
    provenance = (
        {
            "record_id": 27,
            "url_result_id": 9,
            "source_url": "https://example.test/products/widget",
            "url_identity_key": "identity-widget",
            "content_fingerprint": "fp-widget",
            "data": {"title": "Widget"},
            "raw_data": {"title": "Widget raw"},
            "discovered_data": {"confidence": 0.8},
            "source_trace": {"acquisition": {"method": "curl"}},
        },
        {
            "record_id": 28,
            "url_result_id": 9,
            "source_url": "https://example.test/products/second",
            "url_identity_key": "identity-second",
            "content_fingerprint": "fp-second",
            "data": {"title": "Second"},
            "raw_data": {"title": "Second raw"},
            "discovered_data": {"confidence": 0.9},
            "source_trace": {"acquisition": {"method": "httpx"}},
        },
    )
    return publish_url_result_artifacts(
        run_id=7,
        url_result_id=9,
        acquisition_result=acquisition,
        extraction_result=extraction,
        record_count=2,
        record_provenance=provenance,
        root_dir=tmp_path,
    )


def test_canonical_url_artifacts_publish_compact_bundle(
    tmp_path: Path,
) -> None:
    """Publisher emits exactly 3 files: page.html, record.json, diagnose.json."""
    acquisition = SimpleNamespace(
        final_url="https://example.test/products/widget",
        html="<html><h1>Widget</h1></html>",
        method="httpx",
        status_code=200,
        content_type="text/html",
        blocked=False,
        platform_family="shopify",
        adapter_name=None,
        json_data={"product": {"id": 42}},
        network_payloads=[{"url": "/products/widget.js", "body": {"id": 42}}],
        browser_diagnostics={"browser_attempted": False},
        acquisition_diagnostics={},
        artifacts={},
    )
    extraction_payload = {
        "bundle_id": "bundle-42",
        "records": [{"title": "Widget"}],
        "verdict": "success",
        "evidence": [],
        "decisions": [],
        "findings": [],
    }
    extraction = SimpleNamespace(
        bundle_id="bundle-42",
        evidence=[],
        decisions=[],
        findings=[],
        verdict="success",
        data_integrity={},
        metrics=SimpleNamespace(model_dump=lambda **_: {}),
        field_states=[],
        collector_outcomes=[],
        stage_outcomes=[],
        contract_outcomes=[],
        model_dump=lambda **_: dict(extraction_payload),
    )
    provenance = {
        "record_id": 27,
        "url_result_id": 9,
        "source_url": "https://example.test/products/widget",
        "url_identity_key": "identity-42",
        "content_fingerprint": "content-42",
        "data": {"title": "Widget"},
        "raw_data": {"title": "Widget", "_source": "json_ld"},
        "discovered_data": {"confidence": {"score": 0.98}},
        "source_trace": {"acquisition": {"method": "httpx"}},
    }

    published = publish_url_result_artifacts(
        run_id=7,
        url_result_id=9,
        acquisition_result=acquisition,
        extraction_result=extraction,
        record_count=1,
        record_provenance=(provenance,),
        root_dir=tmp_path,
    )

    repository = ArtifactRepository(root_dir=tmp_path)
    assert published.result_root == "runs/7/results/9"
    result_dir = tmp_path / published.result_root
    assert (result_dir / "page.html").is_file()
    assert (result_dir / "record.json").is_file()
    assert (result_dir / "diagnose.json").is_file()
    assert not (result_dir / "manifest.json").exists()
    assert not (result_dir / "screenshot.png").exists()
    files = sorted(result_dir.iterdir(), key=lambda p: p.name)
    assert [f.name for f in files] == ["diagnose.json", "page.html", "record.json"]

    records_payload = repository.read_json(f"{published.result_root}/record.json")
    assert records_payload["records"] == [{"title": "Widget"}]
    assert records_payload["record_count"] == 1


def test_url_result_values_keep_extraction_verdict_as_canonical() -> None:
    run = SimpleNamespace(id=3, surface="ecommerce_detail")
    acquisition = SimpleNamespace(
        final_url="https://example.test/pdp?utm_source=x",
        html="<html>ok</html>",
        status_code=200,
        browser_diagnostics={},
    )
    extraction = SimpleNamespace(
        verdict="partial",
        bundle_id="bundle-42",
        error=None,
    )

    values = url_result_values(
        run=run,  # type: ignore[arg-type]
        requested_url="https://example.test/pdp?utm_source=x",
        acquisition_result=acquisition,
        extraction_result=extraction,
        record_count=2,
        manifest_uri="runs/3/results/9/manifest.json",
    )

    assert values["normalized_url"] == "https://example.test/pdp"
    assert values["acquisition_outcome"] == "success"
    assert values["verdict"] == "partial"
    assert values["record_count"] == 2
    assert values["manifest_uri"] == "runs/3/results/9/manifest.json"


def test_acquisition_outcome_is_not_extraction_verdict_recomputed() -> None:
    assert (
        acquisition_outcome(
            SimpleNamespace(
                html="<html>blocked shell</html>",
                status_code=200,
                browser_diagnostics={"blocked": True},
            )
        )
        == "blocked"
    )
    assert (
        acquisition_outcome(
            SimpleNamespace(html="", status_code=200, browser_diagnostics={})
        )
        == "empty"
    )


def test_detail_record_identity_collapses_revision_query_only() -> None:
    bare = "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html"
    revision = f"{bare}?v1=527078510"

    assert record_persistence._record_identity_key(
        bare,
        surface="ecommerce_detail",
    ) == record_persistence._record_identity_key(
        revision,
        surface="ecommerce_detail",
    )
    assert record_persistence._record_identity_key(
        "https://shop.test/product?pid=123",
        surface="ecommerce_detail",
    ) != record_persistence._record_identity_key(
        "https://shop.test/product?pid=456",
        surface="ecommerce_detail",
    )


def test_candidate_identity_lookup_uses_canonical_detail_url() -> None:
    bare = "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html"
    keys = record_persistence._candidate_identity_keys(
        [{"url": bare}, {"url": f"{bare}?v2=527078510"}],
        SimpleNamespace(final_url=bare),
        surface="ecommerce_detail",
    )

    assert len(keys) == 1


def test_stored_record_match_requires_url_result_link() -> None:
    row = CrawlRecord(
        url_result_id=None,
        run_id=1,
        source_url="https://example.test/p",
        data={"url": "https://example.test/p"},
        raw_data={"legacy": True},
        discovered_data={"legacy": True},
        source_trace={"legacy": True},
        raw_html_path="legacy.html",
        content_fingerprint="fp",
    )

    assert not record_persistence._stored_record_matches(
        row,
        url_result_id=99,
        source_url="https://example.test/p",
        data={"url": "https://example.test/p"},
        content_fingerprint="fp",
        raw_data={"new": True},
        discovered_data={"new": True},
    )

    record_persistence._update_stored_record(
        row,
        url_result_id=99,
        source_url="https://example.test/p",
        data={"url": "https://example.test/p"},
        content_fingerprint="fp",
        raw_data={"new": True},
        discovered_data={"new": True},
        source_trace={"new": True},
    )

    assert row.url_result_id == 99
    assert row.raw_data == {"new": True}
    assert row.discovered_data == {"new": True}
    assert row.source_trace == {"new": True}


@pytest.mark.asyncio
async def test_active_record_write_persists_provenance_to_db() -> None:
    """New records get raw_data, discovered_data, and source_trace persisted to DB."""
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[]),
        add=Mock(),
        flush=AsyncMock(),
    )
    run = SimpleNamespace(id=1, surface="ecommerce_detail", requested_fields=[])
    acquisition = SimpleNamespace(
        final_url="https://example.test/products/widget",
        method="httpx",
        status_code=200,
        browser_diagnostics={},
    )
    raw_record = {
        "url": acquisition.final_url,
        "title": "Widget",
        "_field_sources": {"title": "json_ld"},
    }

    batch = await record_persistence.persist_extracted_records(
        session,
        run,
        [raw_record],
        acquisition_result=acquisition,
        url_result_id=9,
    )

    row = batch.records[0]
    assert row.raw_data == raw_record
    assert "confidence" in row.discovered_data
    assert "acquisition" in row.source_trace
    assert row.raw_html_path is None


def test_persisted_record_batch_separates_writes_from_authoritative_count() -> None:
    records = (SimpleNamespace(id=1), SimpleNamespace(id=2))

    batch = record_persistence.PersistedRecordBatch(
        changed_count=0,
        records=records,
    )

    assert batch.changed_count == 0
    assert batch.record_count == 2
