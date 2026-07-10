"""The single per-URL artifact writer.

One writer persists the canonical three files per URL result under
``runs/{run_id}/results/{url_result_id}/``:

- ``page.html`` — the acquired HTML, written once.
- ``record.json`` — the public record(s) (shape unchanged from the records API).
- ``diagnose.json`` — self-contained, bounded root-cause artifact (see
  :mod:`app.observability.diagnose`).

When browser capture has admitted payloads, ``network_exchanges.json`` is a
bounded response artifact with optional sanitized GraphQL request metadata. It
is omitted for HTTP-only pages.

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
from typing import Any, cast

from app.core.config.extraction_rules import MAX_DIAGNOSE_ARTIFACT_BYTES
from app.core.config import settings
from app.core.config.runtime_settings import browser_capture_total_network_payload_bytes
from app.core.config.network_capture import (
    NETWORK_ARTIFACT_INDEX_MAX_DEPTH,
    NETWORK_ARTIFACT_INDEX_MAX_KEYS,
    NETWORK_ARTIFACT_INDEX_ROW_KEYS,
)
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

    exchanges = _network_exchanges_for_artifact(
        getattr(acquisition_result, "network_payloads", ())
    )
    if exchanges:
        _persist_json(
            repository,
            run_id=run_id,
            url_result_id=url_result_id,
            name="network_exchanges.json",
            payload={"schema_version": "network_exchanges.v1", "exchanges": exchanges},
        )
        _persist_json(
            repository,
            run_id=run_id,
            url_result_id=url_result_id,
            name="network_exchanges.index.json",
            payload={
                "schema_version": "network_exchange_index.v1",
                "exchanges": _network_exchange_index(exchanges),
            },
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


def _network_exchanges_for_artifact(value: object) -> list[dict[str, object]]:
    """Persist bounded evidence without request headers or frame URLs."""
    rows = value if isinstance(value, (list, tuple)) else ()
    exchanges: list[dict[str, object]] = []
    limit = max(1, browser_capture_total_network_payload_bytes())
    used = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        exchange = {
            key: row[key]
            for key in (
                "url",
                "method",
                "status",
                "content_type",
                "endpoint_type",
                "endpoint_family",
                "body_sha256",
                "request_json",
                "body",
            )
            if key in row
        }
        encoded = _json_bytes(_json_safe(exchange))
        if used + len(encoded) > limit:
            break
        exchanges.append(cast(dict[str, object], _json_safe(exchange)))
        used += len(encoded)
    return exchanges


def _network_exchange_index(
    exchanges: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "ordinal": ordinal,
            **{
                key: exchange[key]
                for key in (
                    "url",
                    "method",
                    "status",
                    "content_type",
                    "endpoint_type",
                    "endpoint_family",
                    "body_sha256",
                )
                if key in exchange
            },
            "body_shape": _network_body_shape(exchange.get("body")),
        }
        for ordinal, exchange in enumerate(exchanges)
    ]


def _network_body_shape(value: object, *, depth: int = 0) -> dict[str, object]:
    if isinstance(value, Mapping):
        keys = sorted(str(key) for key in value)[:NETWORK_ARTIFACT_INDEX_MAX_KEYS]
        summary: dict[str, object] = {"kind": "object", "keys": keys}
        rows = {
            str(key): len(item)
            for key, item in value.items()
            if str(key).casefold() in NETWORK_ARTIFACT_INDEX_ROW_KEYS
            and isinstance(item, (list, tuple))
        }
        if rows:
            summary["candidate_row_counts"] = rows
        if depth < NETWORK_ARTIFACT_INDEX_MAX_DEPTH:
            children = {
                str(key): _network_body_shape(item, depth=depth + 1)
                for key, item in value.items()
                if isinstance(item, Mapping)
            }
            if children:
                summary["objects"] = children
        return summary
    if isinstance(value, (list, tuple)):
        return {"kind": "array", "count": len(value)}
    return {"kind": type(value).__name__}


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
        ("evidence_dispositions.examples", 50),
        ("findings", 50),
        ("fields", 50),
        ("variants.dropped", 50),
        ("evidence_dispositions.examples", 10),
        ("findings", 10),
        ("fields", 10),
        ("variants.dropped", 10),
        ("evidence_dispositions.examples", 0),
        ("findings", 0),
        ("fields", 0),
        ("variants.dropped", 0),
    )
    for path, item_limit in shrink_steps:
        if len(_json_bytes(shrunk)) <= limit:
            return shrunk
        _truncate_diagnose_list(shrunk, truncated, path=path, limit=item_limit)
    if len(_json_bytes(shrunk)) <= limit:
        return shrunk
    return {
        "schema_version": shrunk.get("schema_version"),
        "verdict": shrunk.get("verdict"),
        "data_integrity": shrunk.get("data_integrity"),
        "metrics": shrunk.get("metrics"),
        "truncated": truncated,
    }


def _truncate_diagnose_list(
    payload: dict[str, object],
    truncated: dict[str, object],
    *,
    path: str,
    limit: int,
) -> None:
    segments = path.split(".")
    owner = payload
    for segment in segments[:-1]:
        nested = owner.get(segment)
        if not isinstance(nested, Mapping):
            return
        copied = dict(nested)
        owner[segment] = copied
        owner = copied
    key = segments[-1]
    value = owner.get(key)
    if not isinstance(value, list) or len(value) <= limit:
        return
    previous = _mapping(truncated.get(path))
    previous_total = previous.get("total")
    total = previous_total if isinstance(previous_total, int) else len(value)
    truncated_value = value[:limit]
    owner[key] = truncated_value
    truncated[path] = {"included": len(truncated_value), "total": total}


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
