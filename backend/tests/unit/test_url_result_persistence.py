from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.models.crawl_run import CrawlRecord, CrawlUrlResult
from app.persistence.artifacts import ArtifactRepository
from app.persistence.contracts import ArtifactManifest, ExtractionArtifactSet

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
