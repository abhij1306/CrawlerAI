from __future__ import annotations

import csv
import json
from collections.abc import AsyncIterator, Callable
from io import StringIO
from urllib.parse import urlparse

from app.models.crawl_run import CrawlRecord, CrawlRun
from app.models.user import User
from app.crawl.access_service import (
    RECORD_NOT_FOUND_DETAIL,
    RUN_NOT_FOUND_DETAIL,
    require_accessible_record,
)
from app.crawl.crud import get_run_records
from app.core.config.extraction_rules import (
    DISCOVERIST_SCHEMA,
    EXPORT_IMAGE_URL_SUFFIXES,
)
from app.core.config.export_settings import (
    EXPORT_PAGING_HEADER,
    EXPORT_PARTIAL_HEADER,
    EXPORT_TOTAL_HEADER,
    MAX_RECORD_PAGE_SIZE,
)
from app.core.shared.csv_safety import csv_safe_cell, sanitize_csv_row
from app.persistence.export.schema import (
    clean_export_data as _clean_export_data,
    export_record_from_row,
)
from app.persistence.publish.quality_gate import (
    export_quality_headers,
    export_quality_report,
)
from app.persistence.record_artifacts import (
    load_canonical_record_views,
    load_record_artifacts,
)
from app.schemas.crawl import CrawlRecordProvenanceResponse
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

RUN_NOT_FOUND_RESPONSE = {
    404: {"description": RUN_NOT_FOUND_DETAIL},
}
RECORD_PROVENANCE_NOT_FOUND_RESPONSE = {
    404: {"description": f"{RECORD_NOT_FOUND_DETAIL} or {RUN_NOT_FOUND_DETAIL}"},
}
CSV_MEDIA_TYPE = "text/csv"

ExportStreamer = Callable[[AsyncSession, int], AsyncIterator[str]]


async def collect_export_rows(
    session: AsyncSession, run_id: int
) -> tuple[list[CrawlRecord], dict[str, int | bool]]:
    rows = []
    page = 1
    total = 0

    while True:
        page_rows, total = await get_run_records(
            session, run_id, page, MAX_RECORD_PAGE_SIZE
        )
        rows.extend(page_rows)
        if not page_rows or len(rows) >= total:
            break
        page += 1

    return rows, {
        "pages_used": page if rows else 1,
        "total": total,
        "returned": len(rows),
        "truncated": len(rows) < total,
    }


async def build_export_response(
    session: AsyncSession,
    *,
    run_id: int,
    filename: str,
    media_type: str,
    streamer: ExportStreamer,
) -> StreamingResponse:
    rows, metadata = await collect_export_rows(session, run_id)
    run = await session.get(CrawlRun, run_id)
    quality_report = export_quality_report(run, rows)
    return StreamingResponse(
        streamer(session, run_id),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            **export_headers(metadata),
            **export_quality_headers(quality_report),
        },
    )


async def build_json_export_response(
    session: AsyncSession,
    *,
    run_id: int,
) -> StreamingResponse:
    return await build_export_response(
        session,
        run_id=run_id,
        filename=f"run-{run_id}.json",
        media_type="application/json",
        streamer=stream_export_json,
    )


async def build_csv_export_response(
    session: AsyncSession,
    *,
    run_id: int,
) -> StreamingResponse:
    return await build_export_response(
        session,
        run_id=run_id,
        filename=f"run-{run_id}.csv",
        media_type=CSV_MEDIA_TYPE,
        streamer=stream_export_csv,
    )


async def build_discoverist_export_response(
    session: AsyncSession,
    *,
    run_id: int,
) -> StreamingResponse:
    return await build_export_response(
        session,
        run_id=run_id,
        filename=f"run-{run_id}-discoverist.csv",
        media_type=CSV_MEDIA_TYPE,
        streamer=stream_export_discoverist,
    )


async def export_record_provenance(
    session: AsyncSession,
    *,
    record_id: int,
    user: User,
) -> CrawlRecordProvenanceResponse:
    record = await require_accessible_record(session, record_id=record_id, user=user)
    artifacts = await load_record_artifacts(session, record)
    return CrawlRecordProvenanceResponse.model_validate(
        {
            "id": record.id,
            "run_id": record.run_id,
            "source_url": record.source_url,
            "raw_data": dict(artifacts.raw_data),
            "discovered_data": dict(artifacts.discovered_data),
            "source_trace": dict(artifacts.source_trace),
            "enrichment_status": record.enrichment_status,
            "enriched_at": record.enriched_at,
            "raw_html_path": artifacts.raw_html_path,
            "created_at": record.created_at,
        }
    )


async def _stream_export_rows(session: AsyncSession, run_id: int):
    page = 1
    while True:
        page_rows, total = await get_run_records(
            session, run_id, page, MAX_RECORD_PAGE_SIZE
        )
        if not page_rows:
            return
        for row in page_rows:
            yield row
        if page * MAX_RECORD_PAGE_SIZE >= int(total):
            return
        page += 1


async def _stream_export_record_views(session: AsyncSession, run_id: int):
    page = 1
    while True:
        page_rows, total = await get_run_records(
            session, run_id, page, MAX_RECORD_PAGE_SIZE
        )
        if not page_rows:
            return
        for record_view in await load_canonical_record_views(session, page_rows):
            yield record_view
        if page * MAX_RECORD_PAGE_SIZE >= int(total):
            return
        page += 1


async def stream_export_json(session: AsyncSession, run_id: int):
    yield "[\n"
    first = True
    async for record_view in _stream_export_record_views(session, run_id):
        if not first:
            yield ",\n"
        export_record = export_record_from_row(
            record_view,
            data=dict(record_view.data),
            source_trace=dict(record_view.source_trace),
        )
        yield json.dumps(export_record.data, indent=2)
        first = False
    yield "\n]"


async def stream_export_csv(session: AsyncSession, run_id: int):
    fieldnames: set[str] = set()
    async for record_view in _stream_export_record_views(session, run_id):
        export_record = export_record_from_row(
            record_view,
            data=dict(record_view.data),
            source_trace=dict(record_view.source_trace),
        )
        if not export_record.data:
            continue
        fieldnames.update(export_record.data.keys())
    if not fieldnames:
        return
    ordered_fieldnames = [str(csv_safe_cell(name)) for name in sorted(fieldnames)]
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ordered_fieldnames, extrasaction="ignore"
    )
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    async for record_view in _stream_export_record_views(session, run_id):
        export_record = export_record_from_row(
            record_view,
            data=dict(record_view.data),
            source_trace=dict(record_view.source_trace),
        )
        if not export_record.data:
            continue
        writer.writerow(sanitize_csv_row(export_record.data))
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


async def stream_export_discoverist(session: AsyncSession, run_id: int):
    fieldnames = tuple(
        str(field_name) for field_name in DISCOVERIST_SCHEMA if str(field_name).strip()
    )
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(fieldnames)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    async for row in _stream_export_rows(session, run_id):
        writer.writerow(
            [
                csv_safe_cell(
                    row.source_url
                    if field_name == "source_url"
                    else (row.data or {}).get(field_name, "")
                )
                for field_name in fieldnames
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


def clean_export_data(data: dict) -> dict:
    return _clean_export_data(data)


def export_headers(metadata: dict[str, int | bool]) -> dict[str, str]:
    return {
        EXPORT_PAGING_HEADER: str(metadata["pages_used"]),
        EXPORT_TOTAL_HEADER: str(metadata["total"]),
        EXPORT_PARTIAL_HEADER: "true" if metadata["truncated"] else "false",
    }


def _sanitize_export_data(data: dict[str, object]) -> dict[str, object]:
    sanitized = dict(data)
    primary_image = _stringify_export_value(sanitized.get("image_url"))
    additional_images = _dedupe_image_values(
        sanitized.get("additional_images"),
        primary_image=primary_image,
    )
    if additional_images:
        sanitized["additional_images"] = ", ".join(additional_images)
    else:
        sanitized.pop("additional_images", None)
    return sanitized


def _dedupe_image_values(
    value: object,
    *,
    primary_image: str = "",
) -> list[str]:
    parts: list[str] = []
    seen: set[str] = set()
    primary = str(primary_image or "").strip()
    if primary:
        seen.add(primary.lower())
    if isinstance(value, str):
        candidates: list[object] = [part for part in value.split(", ") if part.strip()]
    else:
        candidates = (
            list(value)
            if isinstance(value, (list, tuple, set))
            else [("" if value is None else str(value)).strip()]
        )
    for part in candidates:
        candidate = str(part or "").strip()
        if not candidate:
            continue
        normalized = candidate.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        parts.append(candidate)
    return parts


def _looks_like_image_asset_url(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    path = str(urlparse(text).path or "").strip().lower()
    if not path:
        return False
    return path.endswith(EXPORT_IMAGE_URL_SUFFIXES)


def _stringify_export_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    return text.replace("\r\n", "\n").replace("\u00a0", " ").strip()
