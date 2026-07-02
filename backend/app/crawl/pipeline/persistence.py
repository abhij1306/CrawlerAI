from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from app.models.crawl_run import CrawlRecord, CrawlRun
from app.core.records.confidence import score_record_confidence
from app.core.records.field_url_normalization import canonical_public_record_url
from app.extraction.contracts import VariantDrop
from app.core.db_utils import mapping_or_empty
from app.core.shared.field_coerce import object_list as _object_list
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class PersistedRecordBatch:
    changed_count: int
    records: tuple[CrawlRecord, ...]
    provenance: tuple[Mapping[str, object], ...] = ()

    @property
    def record_count(self) -> int:
        return len(self.records)


@dataclass(slots=True)
class _RecordPersistenceState:
    session: AsyncSession
    run: CrawlRun
    acquisition_result: Any
    url_result_id: int | None
    existing_by_identity: dict[str, CrawlRecord]
    seen_identities: set[str]
    changed_count: int = 0
    records: list[CrawlRecord] = field(default_factory=list)
    provenance: list[Mapping[str, object]] = field(default_factory=list)


def _record_identity_key(source_url: str, *, surface: str | None = None) -> str | None:
    canonical = canonical_public_record_url(
        source_url, surface=surface, field_name="url"
    )
    text = str(canonical or source_url or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record_content_fingerprint(
    data: dict[str, object],
    *,
    identity_source_url: str,
) -> str | None:
    identity_fields = ("gtin", "barcode", "sku", "mpn", "brand", "title")
    values = {
        field_name: _fingerprint_value(data.get(field_name))
        for field_name in identity_fields
        if _fingerprint_value(data.get(field_name)) not in (None, "", [], {})
    }
    if not values:
        values = {"url": _fingerprint_value(identity_source_url)}
    payload = json.dumps(
        values, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fingerprint_value(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    if isinstance(value, list):
        return [
            item
            for item in (_fingerprint_value(item) for item in value)
            if item not in (None, "", [], {})
        ]
    if isinstance(value, dict):
        return {
            str(key): item
            for key, raw_item in sorted(value.items())
            if (item := _fingerprint_value(raw_item)) not in (None, "", [], {})
        }
    return value


def _stored_record_matches(
    row: CrawlRecord,
    *,
    url_result_id: int | None,
    source_url: str,
    data: dict[str, object],
    raw_data: dict[str, object],
    discovered_data: dict[str, object],
    content_fingerprint: str | None,
) -> bool:
    # source_trace is intentionally excluded: it carries volatile acquisition
    # diagnostics (phase timings, status codes, browser_diagnostics) that
    # would otherwise inflate changed_count on every refresh even when the
    # public record and its discovered_data are unchanged.
    return (
        row.url_result_id == url_result_id
        and row.source_url == source_url
        and row.data == data
        and row.raw_data == raw_data
        and row.discovered_data == discovered_data
        and row.content_fingerprint == content_fingerprint
    )


def _update_stored_record(
    row: CrawlRecord,
    *,
    url_result_id: int | None,
    source_url: str,
    data: dict[str, object],
    raw_data: dict[str, object],
    discovered_data: dict[str, object],
    source_trace: dict[str, object],
    content_fingerprint: str | None,
) -> None:
    row.url_result_id = url_result_id
    row.source_url = source_url
    row.data = data
    row.raw_data = raw_data
    row.discovered_data = discovered_data
    row.source_trace = source_trace
    row.content_fingerprint = content_fingerprint


async def persist_extracted_records(
    session: AsyncSession,
    run: CrawlRun,
    records: list[dict[str, object]],
    *,
    acquisition_result,
    url_result_id: int | None = None,
) -> PersistedRecordBatch:
    existing_records_by_identity = await _load_existing_records_by_identity(
        session,
        run_id=run.id,
        identity_keys=_candidate_identity_keys(
            records,
            acquisition_result,
            surface=str(run.surface or ""),
        ),
    )
    state = _RecordPersistenceState(
        session=session,
        run=run,
        acquisition_result=acquisition_result,
        url_result_id=url_result_id,
        existing_by_identity=existing_records_by_identity,
        seen_identities=set(existing_records_by_identity),
    )
    for record in records:
        await _persist_extracted_record(state, dict(record))
    return PersistedRecordBatch(
        changed_count=state.changed_count,
        records=tuple(state.records),
        provenance=tuple(state.provenance),
    )


async def _persist_extracted_record(
    state: _RecordPersistenceState,
    raw_record: dict[str, object],
) -> None:
    acquisition_result = state.acquisition_result
    preliminary_source_url = str(
        raw_record.get("source_url") or acquisition_result.final_url
    )
    data, rejected_public_fields, variant_drops = _public_data_for_record(
        raw_record,
        run=state.run,
        acquisition_result=acquisition_result,
        preliminary_source_url=preliminary_source_url,
    )
    if not data or ("listing" in str(state.run.surface or "") and not data.get("url")):
        return
    record_source_url = str(data.get("source_url") or acquisition_result.final_url)
    identity_source_url = str(data.get("url") or record_source_url)
    identity_key = _record_identity_key(
        identity_source_url,
        surface=str(state.run.surface or ""),
    )
    content_fingerprint = _record_content_fingerprint(
        data,
        identity_source_url=identity_source_url,
    )
    discovered_data = _discovered_data_for_record(
        raw_record,
        data=data,
        run=state.run,
        rejected_public_fields=rejected_public_fields,
    )
    lineage = _record_lineage(
        raw_record,
        data=data,
        acquisition_result=acquisition_result,
        preliminary_source_url=preliminary_source_url,
    )
    source_trace = _source_trace_for_record(
        raw_record,
        data=data,
        acquisition_result=acquisition_result,
        lineage=lineage,
        variant_drops=variant_drops,
    )
    existing_record = state.existing_by_identity.get(identity_key or "")
    if identity_key and identity_key in state.seen_identities:
        await _update_existing_record(
            state,
            existing_record=existing_record,
            source_url=record_source_url,
            data=data,
            raw_data=raw_record,
            discovered_data=dict(discovered_data),
            source_trace=source_trace,
            content_fingerprint=content_fingerprint or "",
        )
        return
    if identity_key is not None:
        state.seen_identities.add(identity_key)
    crawl_record = CrawlRecord(
        url_result_id=state.url_result_id,
        run_id=state.run.id,
        source_url=record_source_url,
        url_identity_key=identity_key,
        content_fingerprint=content_fingerprint,
        data=data,
        raw_data=dict(raw_record),
        discovered_data=dict(discovered_data),
        source_trace=dict(source_trace),
    )
    state.session.add(crawl_record)
    await state.session.flush()
    state.changed_count += 1
    state.records.append(crawl_record)
    state.provenance.append(
        _record_provenance_payload(
            crawl_record,
            raw_data=raw_record,
            discovered_data=discovered_data,
            source_trace=source_trace,
        )
    )


async def _update_existing_record(
    state: _RecordPersistenceState,
    *,
    existing_record: CrawlRecord | None,
    source_url: str,
    data: dict[str, object],
    raw_data: dict[str, object],
    discovered_data: dict[str, object],
    source_trace: dict[str, object],
    content_fingerprint: str,
) -> None:
    if existing_record is None:
        return
    public_changed = not _stored_record_matches(
        existing_record,
        url_result_id=state.url_result_id,
        source_url=source_url,
        data=data,
        raw_data=raw_data,
        discovered_data=discovered_data,
        content_fingerprint=content_fingerprint,
    )
    if public_changed:
        _update_stored_record(
            existing_record,
            url_result_id=state.url_result_id,
            source_url=source_url,
            data=data,
            raw_data=raw_data,
            discovered_data=discovered_data,
            source_trace=source_trace,
            content_fingerprint=content_fingerprint,
        )
        await state.session.flush()
        state.changed_count += 1
    elif existing_record.source_trace != source_trace:
        # Refresh the volatile diagnostic trace without bumping changed_count.
        existing_record.source_trace = source_trace
        await state.session.flush()
    state.records.append(existing_record)
    state.provenance.append(
        _record_provenance_payload(
            existing_record,
            raw_data=raw_data,
            discovered_data=discovered_data,
            source_trace=source_trace,
        )
    )


def _record_provenance_payload(
    record: CrawlRecord,
    *,
    raw_data: Mapping[str, object],
    discovered_data: Mapping[str, object],
    source_trace: Mapping[str, object],
) -> Mapping[str, object]:
    values = {
        "record_id": getattr(record, "id", None),
        "url_result_id": record.url_result_id,
        "source_url": record.source_url,
        "url_identity_key": record.url_identity_key,
        "content_fingerprint": record.content_fingerprint,
        "data": dict(record.data or {}),
        "raw_data": dict(raw_data),
        "discovered_data": dict(discovered_data),
        "source_trace": dict(source_trace),
    }
    return MappingProxyType(
        {key: value for key, value in values.items() if value not in (None, "", [], {})}
    )


def _candidate_identity_keys(
    records: list[dict[str, object]],
    acquisition_result,
    *,
    surface: str | None = None,
) -> set[str]:
    return {
        identity_key
        for record in records
        for identity_key in (
            _record_identity_key(
                str(
                    dict(record).get("url")
                    or dict(record).get("source_url")
                    or acquisition_result.final_url
                ),
                surface=surface,
            ),
        )
        if identity_key
    }


async def _load_existing_records_by_identity(
    session: AsyncSession,
    *,
    run_id: int,
    identity_keys: set[str],
) -> dict[str, CrawlRecord]:
    if not identity_keys:
        return {}
    return {
        str(row.url_identity_key): row
        for row in (
            await session.scalars(
                select(CrawlRecord).where(
                    CrawlRecord.run_id == run_id,
                    CrawlRecord.url_identity_key.in_(identity_keys),
                )
            )
        )
        if row.url_identity_key
    }


def _public_data_for_record(
    raw_record: dict[str, object],
    *,
    run: CrawlRun,
    acquisition_result,
    preliminary_source_url: str,
) -> tuple[dict[str, object], dict[str, object], tuple[VariantDrop, ...]]:
    unfiltered_data = {
        str(key): value
        for key, value in raw_record.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    return unfiltered_data, {}, ()


def _discovered_data_for_record(
    raw_record: dict[str, object],
    *,
    data: dict[str, object],
    run: CrawlRun,
    rejected_public_fields: dict[str, object],
) -> dict[str, object]:
    confidence = score_record_confidence(
        {**data, "_field_sources": mapping_or_empty(raw_record.get("_field_sources"))},
        surface=str(run.surface or ""),
        requested_fields=list(run.requested_fields or []),
    )
    return {
        key: value
        for key, value in {
            "confidence": confidence,
            "manifest_trace": mapping_or_empty(raw_record.get("_manifest_trace")),
            "semantic": mapping_or_empty(raw_record.get("_semantic")),
            "review_bucket": _object_list(raw_record.get("_review_bucket")),
            "rejected_public_fields": rejected_public_fields,
        }.items()
        if value not in (None, "", [], {})
    }


def _source_trace_for_record(
    raw_record: dict[str, object],
    *,
    data: dict[str, object],
    acquisition_result,
    lineage: dict[str, object],
    variant_drops: tuple[VariantDrop, ...] = (),
) -> dict[str, object]:
    selector_traces = mapping_or_empty(raw_record.get("_selector_traces"))
    trace: dict[str, object] = {
        "acquisition": {
            "method": str(getattr(acquisition_result, "method", "") or ""),
            "final_url": str(getattr(acquisition_result, "final_url", "") or ""),
            "status_code": getattr(acquisition_result, "status_code", None),
            "browser_diagnostics": mapping_or_empty(
                getattr(acquisition_result, "browser_diagnostics", {})
            ),
        },
        "lineage": lineage,
        "field_sources": mapping_or_empty(raw_record.get("_field_sources")),
        "field_discovery": {
            field_name: {
                "status": "found",
                "value": value,
                "sources": [
                    str(
                        mapping_or_empty(selector_traces.get(field_name)).get(
                            "selector_source"
                        )
                        or mapping_or_empty(lineage.get(field_name)).get("rule_id")
                        or "extraction"
                    )
                ],
                "selector_trace": mapping_or_empty(selector_traces.get(field_name)),
            }
            for field_name, value in data.items()
        },
    }
    if variant_drops:
        trace["variant_drops"] = [drop.model_dump() for drop in variant_drops]
    return trace


def _record_lineage(
    raw_record: dict[str, object],
    *,
    data: dict[str, object],
    acquisition_result,
    preliminary_source_url: str,
) -> dict[str, object]:
    del data, acquisition_result, preliminary_source_url
    return mapping_or_empty(raw_record.get("_lineage"))
