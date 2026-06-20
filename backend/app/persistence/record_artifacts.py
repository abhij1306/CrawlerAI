from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.crawl_run import CrawlRecord, CrawlUrlResult
from app.persistence.artifacts import ArtifactRepository
from app.persistence.contracts import ArtifactManifest, ArtifactReference


@dataclass(frozen=True, slots=True)
class RecordArtifacts:
    status: str
    html: str = ""
    raw_html_path: str | None = None
    data: Mapping[str, object] = field(default_factory=dict)
    raw_data: Mapping[str, object] = field(default_factory=dict)
    discovered_data: Mapping[str, object] = field(default_factory=dict)
    source_trace: Mapping[str, object] = field(default_factory=dict)
    acquisition: Mapping[str, object] = field(default_factory=dict)
    extraction: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CanonicalRecordView:
    record: CrawlRecord
    artifacts: RecordArtifacts

    @property
    def data(self) -> Mapping[str, object]:
        return self.artifacts.data

    @property
    def raw_data(self) -> Mapping[str, object]:
        return self.artifacts.raw_data

    @property
    def discovered_data(self) -> Mapping[str, object]:
        return self.artifacts.discovered_data

    @property
    def source_trace(self) -> Mapping[str, object]:
        return self.artifacts.source_trace

    @property
    def raw_html_path(self) -> str | None:
        if self.artifacts.status == "legacy":
            return getattr(self.record, "raw_html_path", None)
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self.record, name)


async def load_record_artifacts(
    session: AsyncSession,
    record: CrawlRecord,
    *,
    root_dir: Path | None = None,
) -> RecordArtifacts:
    repository = ArtifactRepository(root_dir=root_dir or settings.artifacts_dir)
    url_result_id = getattr(record, "url_result_id", None)
    if url_result_id is None:
        return _legacy_record_artifacts(record, repository=repository)
    url_result = await session.get(CrawlUrlResult, int(url_result_id))
    manifest_uri = str(getattr(url_result, "manifest_uri", "") or "").strip()
    if not manifest_uri:
        return _legacy_record_artifacts(record, repository=repository)
    try:
        manifest = repository.load_manifest(manifest_uri)
        if manifest.url_result_id != int(url_result_id):
            raise ValueError("artifact manifest URL-result identity mismatch")
        references = _references_by_name(manifest)
        provenance = _read_json_list(repository, references.get("record-provenance.json"))
        row = _match_provenance_row(record, provenance)
        return RecordArtifacts(
            status="canonical",
            html=_read_text(repository, references.get("page.html")),
            data=_mapping(row.get("data")),
            raw_data=_mapping(row.get("raw_data")),
            discovered_data=_mapping(row.get("discovered_data")),
            source_trace=_mapping(row.get("source_trace")),
            acquisition=_read_json_mapping(
                repository,
                references.get("acquisition.json"),
            ),
            extraction=_read_json_mapping(
                repository,
                references.get("extraction.json"),
            ),
        )
    except (OSError, TypeError, ValueError):
        return RecordArtifacts(status="invalid")


async def load_canonical_record_views(
    session: AsyncSession,
    records: list[CrawlRecord],
    *,
    root_dir: Path | None = None,
) -> list[CanonicalRecordView]:
    return [
        CanonicalRecordView(
            record=record,
            artifacts=await load_record_artifacts(
                session,
                record,
                root_dir=root_dir,
            ),
        )
        for record in records
    ]


def _references_by_name(
    manifest: ArtifactManifest,
) -> dict[str, ArtifactReference]:
    references = [
        artifact
        for attempt in manifest.attempts
        for artifact in attempt.artifacts
    ]
    references.extend(manifest.extraction.artifacts)
    by_name: dict[str, ArtifactReference] = {}
    for reference in references:
        if reference.name in by_name:
            raise ValueError(f"duplicate artifact name: {reference.name}")
        by_name[reference.name] = reference
    return by_name


def _match_provenance_row(
    record: CrawlRecord,
    rows: list[Mapping[str, object]],
) -> Mapping[str, object]:
    match_keys = (
        ("record_id", getattr(record, "id", None)),
        ("url_identity_key", getattr(record, "url_identity_key", None)),
        ("source_url", getattr(record, "source_url", None)),
    )
    for key, expected in match_keys:
        if expected in (None, ""):
            continue
        matches = [row for row in rows if row.get(key) == expected]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"ambiguous record provenance match: {key}")
    return {}


def _legacy_record_artifacts(
    record: CrawlRecord,
    *,
    repository: ArtifactRepository,
) -> RecordArtifacts:
    return RecordArtifacts(
        status="legacy",
        html=_read_legacy_html(record, repository=repository),
        raw_html_path=str(getattr(record, "raw_html_path", "") or "") or None,
        data=_mapping(getattr(record, "data", {})),
        raw_data=_mapping(getattr(record, "raw_data", {})),
        discovered_data=_mapping(getattr(record, "discovered_data", {})),
        source_trace=_mapping(getattr(record, "source_trace", {})),
    )


def _read_legacy_html(
    record: CrawlRecord,
    *,
    repository: ArtifactRepository,
) -> str:
    raw_path = str(getattr(record, "raw_html_path", "") or "").strip()
    if not raw_path:
        return ""
    try:
        root = repository.root_dir.resolve()
        path = Path(raw_path)
        resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
        if not resolved.is_relative_to(root):
            return ""
        return resolved.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_text(
    repository: ArtifactRepository,
    reference: ArtifactReference | None,
) -> str:
    return repository.read_text(reference.uri) if reference is not None else ""


def _read_json_list(
    repository: ArtifactRepository,
    reference: ArtifactReference | None,
) -> list[Mapping[str, object]]:
    if reference is None:
        return []
    payload = repository.read_json(reference.uri)
    if not isinstance(payload, list):
        raise ValueError("artifact payload must be a list")
    return [item for item in payload if isinstance(item, Mapping)]


def _read_json_mapping(
    repository: ArtifactRepository,
    reference: ArtifactReference | None,
) -> Mapping[str, object]:
    if reference is None:
        return {}
    payload = repository.read_json(reference.uri)
    if not isinstance(payload, Mapping):
        raise ValueError("artifact payload must be an object")
    return payload


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
