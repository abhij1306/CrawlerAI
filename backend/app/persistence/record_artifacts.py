from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.crawl_run import CrawlRecord, CrawlUrlResult
from app.persistence.artifacts import ArtifactRepository


@dataclass(frozen=True, slots=True)
class RecordArtifacts:
    status: str
    html: str = ""
    raw_html_path: str | None = None
    data: Mapping[str, object] = field(default_factory=dict)
    raw_data: Mapping[str, object] = field(default_factory=dict)
    discovered_data: Mapping[str, object] = field(default_factory=dict)
    source_trace: Mapping[str, object] = field(default_factory=dict)


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
    """Resolve a record's data + provenance + page HTML.

    Record provenance (``data``/``raw_data``/``discovered_data``/``source_trace``)
    is authoritative in the DB columns. The canonical branch reads them straight
    off the row and loads ``page.html`` by fixed name from the result-root path
    stored in ``CrawlUrlResult.manifest_uri``. Records without a URL result fall
    back to the legacy on-disk HTML path.
    """

    repository = ArtifactRepository(root_dir=root_dir or settings.artifacts_dir)
    url_result_id = getattr(record, "url_result_id", None)
    if url_result_id is None:
        return _legacy_record_artifacts(record, repository=repository)
    url_result = await session.get(CrawlUrlResult, int(url_result_id))
    result_root = str(getattr(url_result, "manifest_uri", "") or "").strip()
    if not result_root:
        return _legacy_record_artifacts(record, repository=repository)
    return RecordArtifacts(
        status="canonical",
        html=_read_result_html(repository, result_root),
        data=_mapping(getattr(record, "data", {})),
        raw_data=_mapping(getattr(record, "raw_data", {})),
        discovered_data=_mapping(getattr(record, "discovered_data", {})),
        source_trace=_mapping(getattr(record, "source_trace", {})),
    )


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


def _read_result_html(repository: ArtifactRepository, result_root: str) -> str:
    uri = (Path(result_root) / "page.html").as_posix()
    try:
        return repository.read_text(uri)
    except (OSError, ValueError):
        return ""


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


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
