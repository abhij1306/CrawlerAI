from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.crawl_run import CrawlRecord, CrawlUrlResult
from app.persistence.artifacts import ArtifactRepository
from app.persistence.contracts import ArtifactManifest, ExtractionArtifactSet
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
