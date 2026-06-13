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
from app.services.crawl.access_service import (
    AccessDeniedError,
    RUN_NOT_FOUND_DETAIL,
    require_accessible_run,
)
from app.services.crawl.record_reconciliation import load_records_with_reconciliation
from app.services.record_export_service import (
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
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["records"])


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


@router.get("/api/crawls/{run_id}/records", responses=_route_responses(RUN_NOT_FOUND_RESPONSE))
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
    serialized_rows = await asyncio.to_thread(serialize_crawl_record_responses, rows)
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


@router.get("/api/crawls/{run_id}/export/json", responses=_route_responses(RUN_NOT_FOUND_RESPONSE))
async def export_json(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    await _require_run_access(session, run_id=run_id, user=current_user)
    return await build_json_export_response(session, run_id=run_id)


@router.get("/api/crawls/{run_id}/export/csv", responses=_route_responses(RUN_NOT_FOUND_RESPONSE))
async def export_csv(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    await _require_run_access(session, run_id=run_id, user=current_user)
    return await build_csv_export_response(session, run_id=run_id)


@router.get(
    "/api/crawls/{run_id}/export/tables.csv",
    responses=_route_responses(RUN_NOT_FOUND_RESPONSE),
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
    responses=_route_responses(RUN_NOT_FOUND_RESPONSE),
)
async def export_discoverist(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    await _require_run_access(session, run_id=run_id, user=current_user)
    return await build_discoverist_export_response(session, run_id=run_id)
