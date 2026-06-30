"""The single per-URL artifact writer.

One writer, exactly three files per URL result under
``runs/{run_id}/results/{url_result_id}/``:

- ``page.html`` — the acquired HTML, written once.
- ``record.json`` — the public record(s) (shape unchanged from the records API).
- ``diagnose.json`` — self-contained, bounded root-cause artifact (see
  :mod:`app.observability.diagnose`).

The result-root relative path *is* the contract: the reader opens these three
files by fixed name. No ``manifest.json`` indirection, no second copy of the
HTML, no ``records.json``/``summary.json``/``debug.json`` (record provenance is
authoritative in the DB; root-cause lives in ``diagnose.json``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config.extraction_rules import MAX_DIAGNOSE_ARTIFACT_BYTES
from app.core.config import settings
from app.observability.diagnose import build_diagnosis
from app.persistence.artifacts import ArtifactRepository


@dataclass(frozen=True, slots=True)
class PublishedUrlArtifacts:
    result_root: str
    bundle_id: str


def publish_url_result_artifacts(
    *,
    run_id: int,
    url_result_id: int,
    acquisition_result: Any,
    extraction_result: Any,
    record_count: int,
    record_provenance: Sequence[Mapping[str, object]] = (),
    root_dir: Path | None = None,
) -> PublishedUrlArtifacts:
    repository = ArtifactRepository(root_dir=root_dir or settings.artifacts_dir)

    html = str(getattr(acquisition_result, "html", "") or "")
    _persist_text(
        repository,
        run_id=run_id,
        url_result_id=url_result_id,
        name="page.html",
        content=html,
    )

    records = _records_for_record_json(record_provenance, extraction_result)
    _persist_json(
        repository,
        run_id=run_id,
        url_result_id=url_result_id,
        name="record.json",
        payload={"records": records, "record_count": int(record_count or 0)},
    )

    rejected_public_fields = _merged_rejected_public_fields(record_provenance)
    variant_drops = _collected_variant_drops(record_provenance)
    _persist_json(
        repository,
        run_id=run_id,
        url_result_id=url_result_id,
        name="diagnose.json",
        payload=build_diagnosis(
            acquisition_result=acquisition_result,
            extraction_result=extraction_result,
            rejected_public_fields=rejected_public_fields,
            variant_drops=variant_drops,
        ),
    )

    bundle_id = str(getattr(extraction_result, "bundle_id", "") or "").strip()
    if not bundle_id:
        bundle_id = f"run-{max(int(run_id or 0), 0)}-result-{int(url_result_id)}"
    return PublishedUrlArtifacts(
        result_root=_result_root(run_id, url_result_id),
        bundle_id=bundle_id,
    )


def _result_root(run_id: int, url_result_id: int) -> str:
    return (
        Path("runs")
        / str(max(int(run_id or 0), 0))
        / "results"
        / str(int(url_result_id))
    ).as_posix()


def _merged_rejected_public_fields(
    record_provenance: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    # Page-level diagnose: the first non-empty publication-policy reason per
    # field wins.
    merged: dict[str, object] = {}
    for row in record_provenance:
        discovered = _mapping(row.get("discovered_data"))
        rejected = _mapping(discovered.get("rejected_public_fields"))
        for field_name, reason in rejected.items():
            if reason in (None, "", [], {}):
                continue
            merged.setdefault(str(field_name), reason)
    return merged


def _records_for_record_json(
    record_provenance: Sequence[Mapping[str, object]],
    extraction_result: Any,
) -> list[dict[str, object]]:
    # Prefer the persisted public DB view (record_provenance[*]["data"]) so
    # record.json never drifts from the canonical records API. Fall back to
    # extraction_result only when nothing was persisted.
    persisted = [
        dict(data)
        for row in record_provenance
        for data in (_mapping(row.get("data")),)
        if data
    ]
    if persisted:
        return persisted
    return [
        dict(row)
        for row in (extraction_result.model_dump(mode="json").get("records") or [])
        if isinstance(row, Mapping)
    ]


def _collected_variant_drops(
    record_provenance: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    drops: list[Mapping[str, object]] = []
    for row in record_provenance:
        source_trace = _mapping(row.get("source_trace"))
        raw_drops = source_trace.get("variant_drops")
        if not isinstance(raw_drops, (list, tuple)):
            continue
        for drop in raw_drops:
            if isinstance(drop, Mapping):
                drops.append(dict(drop))
    return drops


def _persist_text(
    repository: ArtifactRepository,
    *,
    run_id: int,
    url_result_id: int,
    name: str,
    content: str,
) -> None:
    repository.persist_bytes(
        run_id=run_id,
        url_result_id=url_result_id,
        name=name,
        content=content.encode("utf-8"),
    )


def _persist_json(
    repository: ArtifactRepository,
    *,
    run_id: int,
    url_result_id: int,
    name: str,
    payload: object,
) -> None:
    safe_payload = _json_safe(payload)
    content = _json_bytes(safe_payload)
    if name == "diagnose.json" and len(content) > MAX_DIAGNOSE_ARTIFACT_BYTES:
        safe_payload = _shrink_diagnose_payload(
            safe_payload,
            original_bytes=len(content),
            limit=MAX_DIAGNOSE_ARTIFACT_BYTES,
        )
        content = _json_bytes(safe_payload)
    repository.persist_bytes(
        run_id=run_id,
        url_result_id=url_result_id,
        name=name,
        content=content,
    )


def _json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")


def _shrink_diagnose_payload(
    payload: object,
    *,
    original_bytes: int,
    limit: int,
) -> object:
    if not isinstance(payload, Mapping):
        return payload
    shrunk: dict[str, object] = dict(payload)
    truncated = dict(_mapping(shrunk.get("truncated")))
    truncated["artifact_size"] = {
        "original_bytes": original_bytes,
        "limit_bytes": limit,
    }
    shrunk["truncated"] = truncated
    shrink_steps = (
        lambda row: _truncate_nested(row, "evidence_dispositions", "examples", 50),
        lambda row: _truncate_list(row, "findings", 50),
        lambda row: _truncate_list(row, "fields", 50),
        lambda row: _truncate_nested(row, "variants", "dropped", 50),
        lambda row: _truncate_nested(row, "evidence_dispositions", "examples", 10),
        lambda row: _truncate_list(row, "findings", 10),
        lambda row: _truncate_list(row, "fields", 10),
        lambda row: _truncate_nested(row, "variants", "dropped", 10),
        lambda row: _truncate_nested(row, "evidence_dispositions", "examples", 0),
        lambda row: _truncate_list(row, "findings", 0),
        lambda row: _truncate_list(row, "fields", 0),
        lambda row: _truncate_nested(row, "variants", "dropped", 0),
    )
    for step in shrink_steps:
        if len(_json_bytes(shrunk)) <= limit:
            return shrunk
        step(shrunk)
    if len(_json_bytes(shrunk)) <= limit:
        return shrunk
    return {
        "schema_version": shrunk.get("schema_version"),
        "verdict": shrunk.get("verdict"),
        "data_integrity": shrunk.get("data_integrity"),
        "metrics": shrunk.get("metrics"),
        "truncated": truncated,
    }


def _truncate_list(payload: dict[str, object], key: str, limit: int) -> None:
    value = payload.get(key)
    if isinstance(value, list):
        payload[key] = value[:limit]


def _truncate_nested(
    payload: dict[str, object],
    parent_key: str,
    child_key: str,
    limit: int,
) -> None:
    parent = payload.get(parent_key)
    if not isinstance(parent, Mapping):
        return
    copied = dict(parent)
    value = copied.get(child_key)
    if isinstance(value, list):
        copied[child_key] = value[:limit]
    payload[parent_key] = copied


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(mode="json", exclude_none=True))
    return str(value)
