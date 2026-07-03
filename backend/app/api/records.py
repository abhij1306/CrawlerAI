# Crawl record and export route handlers.
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Annotated

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.schemas.crawl import (
    CrawlRecordProvenanceResponse,
    CrawlRecordResponse,
    serialize_crawl_record_responses,
)
from app.crawl.access_service import (
    AccessDeniedError,
    RUN_NOT_FOUND_DETAIL,
    require_accessible_run,
)
from app.crawl.record_reconciliation import load_records_with_reconciliation
from app.persistence.record_export_service import (
    CSV_MEDIA_TYPE,
    MAX_RECORD_PAGE_SIZE,
    RECORD_PROVENANCE_NOT_FOUND_RESPONSE,
    RUN_NOT_FOUND_RESPONSE,
    build_artifacts_json_export_response,
    build_csv_export_response,
    build_discoverist_export_response,
    build_json_export_response,
    build_tables_csv_export_response,
    export_record_provenance,
)
from app.persistence.record_artifacts import load_canonical_record_views
from app.persistence.diagnostics_artifacts import (
    load_result_diagnosis,
    load_run_report,
)
from app.models.crawl_run import CrawlUrlResult
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["records"])


class CsvStreamingResponse(StreamingResponse):
    media_type = CSV_MEDIA_TYPE


def _route_responses(
    responses: object,
) -> dict[int | str, dict[str, object]]:
    if not isinstance(responses, Mapping):
        return {}
    normalized: dict[int | str, dict[str, object]] = {}
    for key, value in responses.items():
        if not isinstance(value, Mapping):
            continue
        normalized_key: int | str = key if isinstance(key, (int, str)) else str(key)
        normalized[normalized_key] = dict(value)
    return normalized


def _stream_route_responses(
    responses: object, *, media_type: str
) -> dict[int | str, dict[str, object]]:
    normalized = _route_responses(responses)
    normalized[200] = {
        "content": {media_type: {"schema": {"type": "string"}}},
        "description": "Streaming export",
    }
    return normalized


@router.get(
    "/api/crawls/{run_id}/records", responses=_route_responses(RUN_NOT_FOUND_RESPONSE)
)
async def records_list(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=MAX_RECORD_PAGE_SIZE)] = 20,
) -> PaginatedResponse[CrawlRecordResponse]:
    try:
        run = await require_accessible_run(session, run_id=run_id, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL) from exc

    rows, total = await load_records_with_reconciliation(
        session,
        run_id=run_id,
        run_summary=getattr(run, "result_summary", {}),
        page=page,
        limit=limit,
    )
    record_views = await load_canonical_record_views(session, rows)
    serialized_rows = await asyncio.to_thread(
        serialize_crawl_record_responses,
        record_views,
    )
    return PaginatedResponse(
        items=serialized_rows,
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )


@router.get(
    "/api/records/{record_id}/provenance",
    responses=_route_responses(RECORD_PROVENANCE_NOT_FOUND_RESPONSE),
)
async def record_provenance(
    record_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CrawlRecordProvenanceResponse:
    try:
        return await export_record_provenance(
            session,
            record_id=record_id,
            user=current_user,
        )
    except (LookupError, AccessDeniedError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL) from exc


async def _require_run_access(
    session: AsyncSession, *, run_id: int, user: User
) -> None:
    """Shared access check for export endpoints. Raises 404 if run not found."""
    try:
        await require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL) from exc


@router.get(
    "/api/crawls/{run_id}/export/json",
    responses=_route_responses(RUN_NOT_FOUND_RESPONSE),
)
async def export_json(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    await _require_run_access(session, run_id=run_id, user=current_user)
    return await build_json_export_response(session, run_id=run_id)


@router.get(
    "/api/crawls/{run_id}/export/csv",
    responses=_stream_route_responses(
        RUN_NOT_FOUND_RESPONSE, media_type=CSV_MEDIA_TYPE
    ),
    response_class=CsvStreamingResponse,
)
async def export_csv(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    await _require_run_access(session, run_id=run_id, user=current_user)
    return await build_csv_export_response(session, run_id=run_id)


@router.get(
    "/api/crawls/{run_id}/export/tables.csv",
    responses=_stream_route_responses(
        RUN_NOT_FOUND_RESPONSE, media_type=CSV_MEDIA_TYPE
    ),
    response_class=CsvStreamingResponse,
)
async def export_tables_csv(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    await _require_run_access(session, run_id=run_id, user=current_user)
    return await build_tables_csv_export_response(session, run_id=run_id)


@router.get(
    "/api/crawls/{run_id}/export/artifacts.json",
    responses=_route_responses(RUN_NOT_FOUND_RESPONSE),
)
async def export_artifacts_json(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    await _require_run_access(session, run_id=run_id, user=current_user)
    return await build_artifacts_json_export_response(session, run_id=run_id)


@router.get(
    "/api/crawls/{run_id}/export/discoverist",
    responses=_stream_route_responses(
        RUN_NOT_FOUND_RESPONSE, media_type=CSV_MEDIA_TYPE
    ),
    response_class=CsvStreamingResponse,
)
async def export_discoverist(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    await _require_run_access(session, run_id=run_id, user=current_user)
    return await build_discoverist_export_response(session, run_id=run_id)


@router.get(
    "/api/crawls/{run_id}/report.json",
    responses=_route_responses(RUN_NOT_FOUND_RESPONSE),
)
async def run_report(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    """Run-level root-cause report (``runs/{run_id}/report.json``).

    Reads the persisted artifact, recomputing the deterministic fold on-demand
    when the run-complete callback has not yet written it.
    """
    await _require_run_access(session, run_id=run_id, user=current_user)
    return await asyncio.to_thread(load_run_report, run_id=run_id)


@router.get(
    "/api/crawls/{run_id}/results/{url_result_id}/diagnose.json",
    responses=_route_responses(RUN_NOT_FOUND_RESPONSE),
)
async def result_diagnosis(
    run_id: int,
    url_result_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    """Self-contained per-URL root-cause artifact (``diagnose.json``)."""
    await _require_run_access(session, run_id=run_id, user=current_user)
    url_result = await session.get(CrawlUrlResult, url_result_id)
    if url_result is None or url_result.run_id != run_id:
        raise HTTPException(status_code=404, detail="URL result not found")
    diagnosis = await asyncio.to_thread(
        load_result_diagnosis, run_id=run_id, url_result_id=url_result_id
    )
    if diagnosis is None:
        raise HTTPException(status_code=404, detail="Diagnose artifact not found")
    return diagnosis
