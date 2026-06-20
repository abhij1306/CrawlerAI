from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Mapping, Sequence

from app.models.crawl_run import CrawlRecord, CrawlRun
from app.core.records.confidence import score_record_confidence
from app.extraction.contracts import ExtractionResult
from app.core.db_utils import mapping_or_empty
from app.core.records.public_record_firewall import (
    flatten_variants_for_public_output,
    public_record_data_for_surface,
)
from app.core.shared.field_coerce import object_list as _object_list
from app.observability.browser_artifact import shape_browser_artifact
from app.observability.run_trace import RunTrace
from app.core.config import observability as obs_config
from app.persistence.artifact_store import (
    persist_html_artifact,
    persist_json_artifact,
    persist_png_artifact,
    persist_png_artifact_from_file,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _merge_browser_diagnostics(
    acquisition_result,
    diagnostics: dict[str, object],
) -> None:
    merged = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    merged.update(dict(diagnostics or {}))
    acquisition_result.browser_diagnostics = merged


def _merge_browser_artifact_path(
    acquisition_result,
    *,
    key: str,
    path: str,
) -> None:
    if not path:
        return
    diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    artifact_paths = mapping_or_empty(diagnostics.get("artifact_paths"))
    artifact_paths[str(key)] = path
    diagnostics["artifact_paths"] = artifact_paths
    acquisition_result.browser_diagnostics = diagnostics


def _record_identity_key(source_url: str) -> str | None:
    text = str(source_url or "").strip()
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
    payload = json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
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
    source_trace: dict[str, object],
    raw_html_path: str | None,
    content_fingerprint: str | None,
) -> bool:
    return (
        row.url_result_id == url_result_id
        and
        row.source_url == source_url
        and row.data == data
        and row.raw_data == raw_data
        and row.source_trace == source_trace
        and row.raw_html_path == raw_html_path
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
    raw_html_path: str | None,
    content_fingerprint: str | None,
) -> None:
    row.url_result_id = url_result_id
    row.source_url = source_url
    row.data = data
    row.raw_data = raw_data
    row.discovered_data = discovered_data
    row.source_trace = source_trace
    row.raw_html_path = raw_html_path
    row.content_fingerprint = content_fingerprint


async def persist_run_trace(
    *,
    run_id: int,
    source_url: str,
    trace: RunTrace,
    flagged: bool = False,
) -> str:
    """Persist the per-URL RunTrace as a JSON artifact (observe-only).

    Written next to the page's other artifacts as ``<hash>.trace.json``. No-op
    when tracing is disabled (NullRunTrace serializes an empty timeline) or when
    the run id is missing.
    """
    if not obs_config.RUN_TRACE_ENABLED:
        return ""
    payload = trace.to_dict(flagged=flagged)
    return await asyncio.to_thread(
        persist_json_artifact,
        run_id=run_id,
        source_url=source_url,
        suffix="trace",
        payload=payload,
    )


def build_extraction_decision_payload(
    *,
    result: ExtractionResult,
    persisted_count: int,
) -> dict[str, Any]:
    payload = result.model_dump(mode="json", exclude_none=True)
    payload["persisted_count"] = int(persisted_count or 0)
    return payload


async def persist_extraction_decision_artifact(
    *,
    run_id: int,
    source_url: str,
    persisted_count: int,
    result: ExtractionResult,
    acquisition_result=None,
) -> str:
    payload = build_extraction_decision_payload(
        result=result,
        persisted_count=persisted_count,
    )
    component_payloads = {
        "capture": result.bundle_id,
        "evidence": payload.get("evidence", []),
        "graph": payload.get("graph", {}),
        "target": payload.get("target", {}),
        "findings": payload.get("findings", []),
        "decisions": payload.get("decisions", []),
        "records": payload.get("records", []),
        "verdict": {
            "verdict": result.verdict,
            "retry_request": payload.get("retry_request"),
            "metrics": payload.get("metrics", {}),
            "persisted_count": int(persisted_count or 0),
        },
    }
    paths: dict[str, str] = {}
    for suffix, component in component_payloads.items():
        paths[suffix] = await asyncio.to_thread(
            persist_json_artifact,
            run_id=run_id,
            source_url=source_url,
            suffix=suffix,
            payload=component,
        )
    path = await asyncio.to_thread(
        persist_json_artifact,
        run_id=run_id,
        source_url=source_url,
        suffix="extraction",
        payload=payload,
    )
    if acquisition_result is not None:
        _merge_browser_artifact_path(
            acquisition_result,
            key="extraction_decision",
            path=path,
        )
        for key, component_path in paths.items():
            _merge_browser_artifact_path(
                acquisition_result,
                key=f"extraction_{key}",
                path=component_path,
            )
    return path


def _extraction_decision_record(record: Mapping[str, Any]) -> dict[str, Any]:
    public_fields = {
        str(key): _json_safe(value)
        for key, value in record.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    payload: dict[str, Any] = {"public_fields": public_fields}
    for key in (
        "_source",
        "_confidence",
        "_field_sources",
        "_evidence_graph",
        "_validation_findings",
        "_review_bucket",
        "_rejected_public_fields",
    ):
        value = record.get(key)
        if value not in (None, "", [], {}):
            payload[key.removeprefix("_")] = _json_safe(value)
    return payload


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


async def persist_acquisition_artifacts(
    *,
    run_id: int,
    acquisition_result,
    browser_attempted: bool,
    screenshot_required: bool,
    surface: str | None = None,
    blocked: bool = False,
) -> str:
    raw_html_path = await asyncio.to_thread(
        persist_html_artifact,
        run_id=run_id,
        source_url=acquisition_result.final_url,
        html=acquisition_result.html,
    )
    if browser_attempted:
        await _persist_browser_artifacts(
            run_id=run_id,
            acquisition_result=acquisition_result,
            screenshot_required=screenshot_required,
            raw_html_path=raw_html_path,
            surface=surface,
            blocked=blocked,
        )
    return raw_html_path


async def _persist_browser_artifacts(
    *,
    run_id: int,
    acquisition_result,
    screenshot_required: bool,
    raw_html_path: str,
    surface: str | None = None,
    blocked: bool = False,
) -> None:

    diagnostics = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    artifacts = dict(mapping_or_empty(getattr(acquisition_result, "artifacts", {})))
    screenshot_path_source = str(artifacts.pop("browser_screenshot_path", "") or "").strip()
    screenshot_bytes = artifacts.pop("browser_screenshot_png", b"")
    screenshot_path = ""
    if screenshot_required:
        if screenshot_path_source:
            screenshot_path = await asyncio.to_thread(
                persist_png_artifact_from_file,
                run_id=run_id,
                source_url=acquisition_result.final_url,
                suffix="browser",
                file_path=screenshot_path_source,
            )
        elif isinstance(screenshot_bytes, (bytes, bytearray)):
            screenshot_path = await asyncio.to_thread(
                persist_png_artifact,
                run_id=run_id,
                source_url=acquisition_result.final_url,
                suffix="browser",
                content=bytes(screenshot_bytes),
            )

    # Shape only the *saved* artifact (honest + lean). The in-memory diagnostics
    # dict is left untouched for downstream runtime consumers.
    diagnostics_payload = shape_browser_artifact(
        diagnostics,
        surface=surface,
        blocked=blocked,
    )
    diagnostics_payload["artifact_paths"] = {
        "html": raw_html_path or None,
        "screenshot": screenshot_path or None,
    }
    diagnostics_path = await asyncio.to_thread(
        persist_json_artifact,
        run_id=run_id,
        source_url=acquisition_result.final_url,
        suffix="browser",
        payload=diagnostics_payload,
    )
    _merge_browser_diagnostics(
        acquisition_result,
        {
            "artifact_paths": {
                "html": raw_html_path or None,
                "diagnostics": diagnostics_path or None,
                "screenshot": screenshot_path or None,
            }
        },
    )


async def persist_extracted_records(
    session: AsyncSession,
    run: CrawlRun,
    records: list[dict[str, object]],
    *,
    acquisition_result,
    url_result_id: int | None = None,
    raw_html_path: str | None = None,
) -> int:
    persisted = 0
    existing_records_by_identity = await _load_existing_records_by_identity(
        session,
        run_id=run.id,
        identity_keys=_candidate_identity_keys(records, acquisition_result),
    )
    seen_identities: set[str] = set(existing_records_by_identity)
    for record in records:
        raw_record = dict(record)
        preliminary_source_url = str(raw_record.get("source_url") or acquisition_result.final_url)
        data, rejected_public_fields = _public_data_for_record(
            raw_record,
            run=run,
            acquisition_result=acquisition_result,
            preliminary_source_url=preliminary_source_url,
        )
        if not data:
            continue
        if "listing" in str(run.surface or "") and not data.get("url"):
            continue
        record_source_url = str(data.get("source_url") or acquisition_result.final_url)
        identity_source_url = str(data.get("url") or record_source_url)
        identity_key = _record_identity_key(identity_source_url)
        content_fingerprint = _record_content_fingerprint(data, identity_source_url=identity_source_url)
        discovered_data = _discovered_data_for_record(
            raw_record,
            data=data,
            run=run,
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
        )
        existing_record = existing_records_by_identity.get(identity_key or "")
        if identity_key and identity_key in seen_identities:
            if existing_record and not _stored_record_matches(
                existing_record,
                url_result_id=url_result_id,
                source_url=record_source_url,
                data=data,
                raw_data=raw_record,
                source_trace=source_trace,
                raw_html_path=raw_html_path,
                content_fingerprint=content_fingerprint,
            ):
                _update_stored_record(
                    existing_record,
                    url_result_id=url_result_id,
                    source_url=record_source_url,
                    data=data,
                    raw_data=raw_record,
                    discovered_data=dict(discovered_data),
                    source_trace=source_trace,
                    raw_html_path=raw_html_path,
                    content_fingerprint=content_fingerprint,
                )
                await session.flush()
                persisted += 1
            continue
        if identity_key is not None:
            seen_identities.add(identity_key)
        crawl_record = CrawlRecord(
            url_result_id=url_result_id,
            run_id=run.id,
            source_url=record_source_url,
            url_identity_key=identity_key,
            content_fingerprint=content_fingerprint,
            data=data,
            raw_data=raw_record,
            discovered_data=discovered_data,
            source_trace=source_trace,
            raw_html_path=raw_html_path,
        )
        session.add(crawl_record)
        await session.flush()
        persisted += 1
    return persisted


def _candidate_identity_keys(
    records: list[dict[str, object]],
    acquisition_result,
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
                )
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
) -> tuple[dict[str, object], dict[str, object]]:
    unfiltered_data = {
        str(key): value
        for key, value in raw_record.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    return public_record_data_for_surface(
        unfiltered_data,
        surface=str(run.surface or ""),
        page_url=str(getattr(acquisition_result, "final_url", "") or preliminary_source_url),
        requested_fields=list(run.requested_fields or []),
    )


def _discovered_data_for_record(
    raw_record: dict[str, object],
    *,
    data: dict[str, object],
    run: CrawlRun,
    rejected_public_fields: dict[str, object],
) -> dict[str, object]:
    confidence = mapping_or_empty(
        raw_record.get("_confidence")
    ) or score_record_confidence(
        {**data, "_field_sources": mapping_or_empty(raw_record.get("_field_sources"))},
        surface=str(run.surface or ""),
        requested_fields=list(run.requested_fields or []),
    )
    return {
        key: value
        for key, value in {
            "confidence": confidence,
            "field_repair": mapping_or_empty(raw_record.get("_field_repair")),
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
) -> dict[str, object]:
    selector_traces = mapping_or_empty(raw_record.get("_selector_traces"))
    return {
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


def _record_lineage(
    raw_record: dict[str, object],
    *,
    data: dict[str, object],
    acquisition_result,
    preliminary_source_url: str,
) -> dict[str, object]:
    return _public_lineage_for_data(
        mapping_or_empty(raw_record.get("_lineage")),
        raw_record=raw_record,
        public_data=data,
        page_url=str(getattr(acquisition_result, "final_url", "") or preliminary_source_url),
    )


def _public_lineage_for_data(
    lineage: dict[str, object],
    *,
    raw_record: dict[str, object],
    public_data: dict[str, object],
    page_url: str,
) -> dict[str, object]:
    if "variants" not in lineage:
        return lineage
    cleaned = dict(lineage)
    if "variants" not in public_data:
        cleaned.pop("variants", None)
        return cleaned
    raw_variants = _object_list(raw_record.get("variants"))
    raw_variant_lineage = _object_list(lineage.get("variants"))
    kept_lineage = [
        raw_variant_lineage[index]
        for index, row in enumerate(raw_variants)
        if index < len(raw_variant_lineage)
        and isinstance(row, dict)
        and flatten_variants_for_public_output([row], page_url=page_url)
    ]
    if kept_lineage:
        cleaned["variants"] = kept_lineage
    else:
        cleaned.pop("variants", None)
    return cleaned
