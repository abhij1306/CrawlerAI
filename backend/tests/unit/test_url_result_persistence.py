from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.crawl_run import CrawlRecord, CrawlUrlResult
from app.persistence.artifacts import ArtifactRepository
from app.persistence.record_artifacts import load_record_artifacts
from app.persistence.contracts import (
    ArtifactManifest,
    ExtractionArtifactSet,
)
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


def test_manifest_is_published_after_referenced_artifacts(tmp_path: Path) -> None:
    repository = ArtifactRepository(root_dir=tmp_path)
    artifact = repository.persist_bytes(
        run_id=7,
        url_result_id=9,
        name="records.json",
        content=b"[]",
    )
    manifest = ArtifactManifest(
        run_id=7,
        url_result_id=9,
        bundle_id="bundle-1",
        extraction=ExtractionArtifactSet(artifacts=(artifact,)),
    )
    reference = repository.persist_manifest(manifest)
    payload = json.loads((tmp_path / reference.uri).read_text(encoding="utf-8"))
    assert payload["extraction"]["artifacts"][0]["sha256"] == artifact.sha256
    assert (tmp_path / artifact.uri).is_file()


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


def test_manifest_rejects_modified_referenced_artifact(tmp_path: Path) -> None:
    repository = ArtifactRepository(root_dir=tmp_path)
    artifact = repository.persist_bytes(
        run_id=7,
        url_result_id=9,
        name="records.json",
        content=b"[]",
    )
    (tmp_path / artifact.uri).write_bytes(b"tampered")
    manifest = ArtifactManifest(
        run_id=7,
        url_result_id=9,
        bundle_id="bundle-1",
        extraction=ExtractionArtifactSet(artifacts=(artifact,)),
    )

    with pytest.raises(ValueError, match="missing or modified"):
        repository.persist_manifest(manifest)


def test_manifest_rejects_reference_owned_by_another_result(tmp_path: Path) -> None:
    repository = ArtifactRepository(root_dir=tmp_path)
    artifact = repository.persist_bytes(
        run_id=7,
        url_result_id=10,
        name="records.json",
        content=b"[]",
    )
    manifest = ArtifactManifest(
        run_id=7,
        url_result_id=9,
        bundle_id="bundle-1",
        extraction=ExtractionArtifactSet(artifacts=(artifact,)),
    )

    with pytest.raises(ValueError, match="outside URL-result directory"):
        repository.persist_manifest(manifest)


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
        raw_data={"legacy": True},
        discovered_data={"legacy": True},
        source_trace={"legacy": True},
        raw_html_path=None,
    )
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(manifest_uri=published.reference.uri)

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
    manifest = repository.load_manifest(published.reference.uri)
    page = next(
        artifact
        for attempt in manifest.attempts
        for artifact in attempt.artifacts
        if artifact.name == "page.html"
    )
    repository.resolve_uri(page.uri).write_text("tampered", encoding="utf-8")
    record = SimpleNamespace(
        id=27,
        url_result_id=9,
        source_url="https://example.test/products/widget",
        url_identity_key="identity-widget",
        raw_data={"legacy": True},
        discovered_data={"legacy": True},
        source_trace={"legacy": True},
        raw_html_path=None,
    )
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(manifest_uri=published.reference.uri)

    artifacts = await load_record_artifacts(
        session,
        record,
        root_dir=tmp_path,
    )

    assert artifacts.status == "invalid"
    assert artifacts.html == ""
    assert artifacts.raw_data == {}


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


@pytest.mark.parametrize(
    "diagnostics, message",
    (
        (
            {
                "result": {
                    "selected_attempt_id": "missing",
                    "attempts": [{"attempt_id": "attempt-1"}],
                }
            },
            "selected acquisition attempt",
        ),
        (
            {
                "result": {
                    "selected_attempt_id": "attempt-1",
                    "attempts": [
                        {"attempt_id": "attempt-1"},
                        {"attempt_id": "attempt-1"},
                    ],
                }
            },
            "duplicate acquisition attempt",
        ),
    ),
)
def test_url_artifact_publisher_rejects_inconsistent_attempt_identity(
    tmp_path: Path,
    diagnostics: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _publish_record_reader_fixture(
            tmp_path,
            acquisition_diagnostics=diagnostics,
        )


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
    records = (
        SimpleNamespace(
            id=27,
            url_result_id=9,
            source_url="https://example.test/products/widget",
            url_identity_key="identity-widget",
            content_fingerprint="fp-widget",
            data={"title": "Widget"},
            raw_data={"title": "Widget raw"},
            discovered_data={"confidence": 0.8},
            source_trace={"acquisition": {"method": "curl"}},
        ),
        SimpleNamespace(
            id=28,
            url_result_id=9,
            source_url="https://example.test/products/second",
            url_identity_key="identity-second",
            content_fingerprint="fp-second",
            data={"title": "Second"},
            raw_data={"title": "Second raw"},
            discovered_data={"confidence": 0.9},
            source_trace={"acquisition": {"method": "httpx"}},
        ),
    )
    return publish_url_result_artifacts(
        run_id=7,
        url_result_id=9,
        acquisition_result=acquisition,
        extraction_result=extraction,
        record_count=2,
        persisted_records=records,
        root_dir=tmp_path,
    )


def test_canonical_url_artifacts_publish_attempts_and_extraction_components(
    tmp_path: Path,
) -> None:
    screenshot = tmp_path / "browser.png"
    screenshot.write_bytes(b"png")
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
        acquisition_diagnostics={
            "result": {
                "selected_attempt_id": "attempt-2",
                "attempts": [
                    {"attempt_id": "attempt-1", "outcome": "error"},
                    {"attempt_id": "attempt-2", "outcome": "success"},
                ],
            }
        },
        artifacts={
            "browser_screenshot_path": str(screenshot),
            "full_rendered_html": "<html><h1>Rendered Widget</h1></html>",
            "listing_visual_elements": [{"text": "Widget"}],
        },
    )
    extraction_payload = {
        "bundle_id": "bundle-42",
        "evidence": [{"evidence_id": "ev-1"}],
        "graph": {"nodes": []},
        "target": {"selected_entity_id": "product-1"},
        "findings": [{"code": "title_found"}],
        "decisions": [{"field": "title", "value": "Widget"}],
        "records": [{"title": "Widget"}],
        "verdict": "success",
        "retry_request": None,
        "metrics": {"evidence_count": 1},
    }
    extraction = SimpleNamespace(
        bundle_id="bundle-42",
        model_dump=lambda **_: dict(extraction_payload),
    )
    persisted_record = SimpleNamespace(
        id=27,
        url_result_id=9,
        source_url="https://example.test/products/widget",
        url_identity_key="identity-42",
        content_fingerprint="content-42",
        data={"title": "Widget"},
        raw_data={"title": "Widget", "_source": "json_ld"},
        discovered_data={"confidence": {"score": 0.98}},
        source_trace={"acquisition": {"method": "httpx"}},
    )

    published = publish_url_result_artifacts(
        run_id=7,
        url_result_id=9,
        acquisition_result=acquisition,
        extraction_result=extraction,
        record_count=1,
        persisted_records=(persisted_record,),
        root_dir=tmp_path,
    )

    repository = ArtifactRepository(root_dir=tmp_path)
    manifest = repository.load_manifest(published.reference.uri)
    assert published.reference.uri == "runs/7/results/9/manifest.json"
    assert manifest.bundle_id == "bundle-42"
    assert [attempt.attempt_id for attempt in manifest.attempts] == [
        "attempt-1",
        "attempt-2",
    ]
    first_names = {item.name for item in manifest.attempts[0].artifacts}
    selected_names = {item.name for item in manifest.attempts[1].artifacts}
    assert first_names == {"attempt-01-attempt-1.json"}
    assert {
        "attempt-02-attempt-2.json",
        "page.html",
        "acquisition.json",
        "response.json",
        "network.json",
        "rendered.html",
        "listing-visual-elements.json",
        "screenshot.png",
    } <= selected_names
    extraction_names = {item.name for item in manifest.extraction.artifacts}
    assert extraction_names == {
        "capture.json",
        "evidence.json",
        "graph.json",
        "target.json",
        "findings.json",
        "decisions.json",
        "records.json",
        "record-provenance.json",
        "verdict.json",
        "extraction.json",
    }
    provenance_reference = next(
        item
        for item in manifest.extraction.artifacts
        if item.name == "record-provenance.json"
    )
    provenance = repository.read_json(provenance_reference.uri)
    assert provenance == [
        {
            "content_fingerprint": "content-42",
            "data": {"title": "Widget"},
            "discovered_data": {"confidence": {"score": 0.98}},
            "raw_data": {"_source": "json_ld", "title": "Widget"},
            "record_id": 27,
            "source_trace": {"acquisition": {"method": "httpx"}},
            "source_url": "https://example.test/products/widget",
            "url_identity_key": "identity-42",
            "url_result_id": 9,
        }
    ]
    references = [
        artifact
        for attempt in manifest.attempts
        for artifact in attempt.artifacts
    ] + list(manifest.extraction.artifacts)
    assert all(repository.reference_exists(reference) for reference in references)


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


def test_stored_record_match_requires_url_result_link() -> None:
    row = CrawlRecord(
        url_result_id=None,
        run_id=1,
        source_url="https://example.test/p",
        data={"url": "https://example.test/p"},
        raw_data={"url": "https://example.test/p"},
        source_trace={},
        raw_html_path="artifact.html",
        content_fingerprint="fp",
    )

    assert not record_persistence._stored_record_matches(
        row,
        url_result_id=99,
        source_url="https://example.test/p",
        data={"url": "https://example.test/p"},
        raw_data={"url": "https://example.test/p"},
        source_trace={},
        raw_html_path="artifact.html",
        content_fingerprint="fp",
    )

    record_persistence._update_stored_record(
        row,
        url_result_id=99,
        source_url="https://example.test/p",
        data={"url": "https://example.test/p"},
        raw_data={"url": "https://example.test/p"},
        discovered_data={},
        source_trace={},
        raw_html_path="artifact.html",
        content_fingerprint="fp",
    )

    assert row.url_result_id == 99


def test_persisted_record_batch_separates_writes_from_authoritative_count() -> None:
    records = (SimpleNamespace(id=1), SimpleNamespace(id=2))

    batch = record_persistence.PersistedRecordBatch(
        changed_count=0,
        records=records,
    )

    assert batch.changed_count == 0
    assert batch.record_count == 2
