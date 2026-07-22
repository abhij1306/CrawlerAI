from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, TypedDict

from app.models.crawl_run import CrawlRecord, CrawlRun
from app.core.records.confidence import score_record_confidence
from app.core.records.field_url_normalization import canonical_public_record_url
from app.extraction.contracts import VariantDrop
from app.core.db_utils import mapping_or_empty
from app.core.shared.field_coerce import object_list as _object_list
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PersistedRecordBatch:
    changed_count: int
    records: tuple[CrawlRecord, ...]
    provenance: tuple[Mapping[str, object], ...] = ()

    @property
    def record_count(self) -> int:
        return len(self.records)


class _StoredRecordUpdate(TypedDict):
    """Full column payload applied when a stored record's data changed."""

    url_result_id: int | None
    source_url: str
    data: dict[str, object]
    raw_data: dict[str, object]
    discovered_data: dict[str, object]
    source_trace: dict[str, object]
    content_fingerprint: str | None


@dataclass(slots=True)
class _StagedRecordWrite:
    """One record write staged for the URL's single batched flush.

    ``full_update`` carries every column value for a changed existing row;
    ``trace_refresh`` carries only the volatile diagnostic trace refresh;
    both are ``None`` for a no-change row or a brand-new record.
    """

    record: CrawlRecord
    raw_data: dict[str, object]
    discovered_data: dict[str, object]
    source_trace: dict[str, object]
    counts_as_change: bool
    is_new: bool
    full_update: _StoredRecordUpdate | None = None
    trace_refresh: dict[str, object] | None = None


@dataclass(slots=True)
class _RecordPersistenceState:
    session: AsyncSession
    run: CrawlRun
    acquisition_result: Any
    url_result_id: int | None
    existing_by_identity: dict[str, CrawlRecord]
    seen_identities: set[str]
    changed_count: int = 0
    pending: list[_StagedRecordWrite] = field(default_factory=list)
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
        _stage_extracted_record(state, dict(record))
    # Per-URL DB budget: one flush for the URL's whole record batch instead of
    # one INSERT/UPDATE round trip per record.
    await _flush_staged_writes(state)
    return PersistedRecordBatch(
        changed_count=state.changed_count,
        records=tuple(state.records),
        provenance=tuple(state.provenance),
    )


def _stage_extracted_record(
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
        _stage_existing_record_update(
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
    state.pending.append(
        _StagedRecordWrite(
            record=crawl_record,
            raw_data=raw_record,
            discovered_data=discovered_data,
            source_trace=source_trace,
            counts_as_change=True,
            is_new=True,
        )
    )


def _stage_existing_record_update(
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
    full_update: _StoredRecordUpdate | None = None
    trace_refresh: dict[str, object] | None = None
    if public_changed:
        full_update = {
            "url_result_id": state.url_result_id,
            "source_url": source_url,
            "data": data,
            "raw_data": raw_data,
            "discovered_data": discovered_data,
            "source_trace": source_trace,
            "content_fingerprint": content_fingerprint,
        }
    elif existing_record.source_trace != source_trace:
        # Refresh the volatile diagnostic trace without bumping changed_count.
        trace_refresh = source_trace
    state.pending.append(
        _StagedRecordWrite(
            record=existing_record,
            raw_data=raw_data,
            discovered_data=discovered_data,
            source_trace=source_trace,
            counts_as_change=public_changed,
            is_new=False,
            full_update=full_update,
            trace_refresh=trace_refresh,
        )
    )


def _apply_staged_write(session: AsyncSession, write: _StagedRecordWrite) -> None:
    if write.is_new:
        session.add(write.record)
    elif write.full_update is not None:
        _update_stored_record(write.record, **write.full_update)
    elif write.trace_refresh is not None:
        write.record.source_trace = write.trace_refresh


def _finalize_staged_write(
    state: _RecordPersistenceState, write: _StagedRecordWrite
) -> None:
    if write.counts_as_change:
        state.changed_count += 1
    state.records.append(write.record)
    state.provenance.append(
        _record_provenance_payload(
            write.record,
            raw_data=write.raw_data,
            discovered_data=write.discovered_data,
            source_trace=write.source_trace,
        )
    )


@asynccontextmanager
async def _null_savepoint():
    yield


def _flush_savepoint(session: AsyncSession):
    """Savepoint guard around a flush.

    Duck-typed session doubles without ``begin_nested`` get a no-op guard;
    real sessions get a SAVEPOINT so a failed flush never poisons the URL's
    outer transaction.
    """

    begin_nested = getattr(session, "begin_nested", None)
    if callable(begin_nested):
        return begin_nested()
    return _null_savepoint()


async def _flush_staged_writes(state: _RecordPersistenceState) -> None:
    if not state.pending:
        return
    try:
        async with _flush_savepoint(state.session):
            for write in state.pending:
                _apply_staged_write(state.session, write)
            await state.session.flush()
    except Exception:
        # Per-record error semantics: retry each write under its own savepoint
        # so one bad record skips with a warning instead of failing the URL's
        # whole batch.
        logger.warning(
            "Batched CrawlRecord flush failed; retrying %d record(s) individually",
            len(state.pending),
            exc_info=True,
        )
        await _flush_staged_writes_individually(state)
        return
    for write in state.pending:
        _finalize_staged_write(state, write)


async def _flush_staged_writes_individually(state: _RecordPersistenceState) -> None:
    session = state.session
    # After the batch savepoint rolled back, every staged new row reverts to
    # pending; detach them all so each retry flush involves exactly one record.
    # A server-assigned PK from the failed flush is cleared so retries INSERT
    # cleanly.
    for write in state.pending:
        if write.is_new:
            if write.record in session:
                session.expunge(write.record)
            # Clear any server-assigned PK so the retry INSERTs cleanly.
            write.record.id = None  # type: ignore[assignment]
    for write in state.pending:
        try:
            async with _flush_savepoint(session):
                _apply_staged_write(session, write)
                await session.flush()
        except Exception:
            logger.warning(
                "CrawlRecord persistence failed for source_url=%s; record skipped",
                getattr(write.record, "source_url", ""),
                exc_info=True,
            )
            if write.is_new:
                # Keep the failed row from poisoning the next record's flush.
                if write.record in session:
                    session.expunge(write.record)
                # Clear any server-assigned PK so the retry INSERTs cleanly.
                write.record.id = None  # type: ignore[assignment]
            continue
        _finalize_staged_write(state, write)


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
