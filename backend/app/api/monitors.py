from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.monitor import (
    MONITOR_EVENT_TYPES,
    MONITOR_PRIORITIES,
    MONITOR_STATUSES,
    MonitorCreate,
    MonitorEventResponse,
    MonitorJobResponse,
    MonitorRunNowResponse,
    MonitorSnapshotRecordResponse,
    MonitorSnapshotResponse,
    MonitorUpdate,
)
from app.services.config.monitor_settings import MONITOR_STATUS_ARCHIVED, MONITOR_STATUS_PAUSED
from app.services.monitor_scheduler_service import MonitorSchedulerService
from app.services.monitor_service import (
    archive_monitor,
    batch_monitor_change_counts,
    create_monitor,
    current_snapshot_records,
    get_monitor,
    list_events,
    list_monitors,
    list_snapshot_records,
    list_snapshots,
    monitor_change_count_since,
    update_monitor,
    utcnow,
)

router = APIRouter(prefix="/api/monitors", tags=["monitors"])
EXPORT_PAGE_SIZE_MAX = 1_000
EXPORT_HISTORY_RECORD_LIMIT = 10_000


@router.post("", status_code=status.HTTP_201_CREATED)
async def monitor_create(
    payload: MonitorCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> MonitorJobResponse:
    try:
        monitor = await create_monitor(session, user=user, payload=payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _monitor_response(session, monitor)


@router.get("")
async def monitor_list(
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    priority: Annotated[str | None, Query()] = None,
) -> list[MonitorJobResponse]:
    if status_filter and status_filter not in MONITOR_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
    if priority and priority not in MONITOR_PRIORITIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid priority")
    monitors = await list_monitors(session, status=status_filter, priority=priority)
    counts = await batch_monitor_change_counts(
        session,
        [int(monitor.id) for monitor in monitors],
    )
    return [
        MonitorJobResponse.model_validate(monitor, from_attributes=True).model_copy(
            update={"change_count": counts.get(int(monitor.id), 0)}
        )
        for monitor in monitors
    ]


@router.get("/{monitor_id}")
async def monitor_get(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> MonitorJobResponse:
    try:
        monitor = await get_monitor(session, monitor_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await _monitor_response(session, monitor)


@router.patch("/{monitor_id}")
async def monitor_patch(
    monitor_id: int,
    payload: MonitorUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> MonitorJobResponse:
    try:
        monitor = await update_monitor(
            session,
            monitor_id=monitor_id,
            payload=payload.model_dump(exclude_unset=True),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _monitor_response(session, monitor)


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def monitor_delete(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> Response:
    try:
        await archive_monitor(session, monitor_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{monitor_id}/run/now")
async def monitor_run_now(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> MonitorRunNowResponse:
    try:
        monitor = await get_monitor(session, monitor_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if monitor.status == MONITOR_STATUS_ARCHIVED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Monitor is archived")
    if monitor.status == MONITOR_STATUS_PAUSED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Monitor is paused — resume it first")
    urls = list(monitor.urls or [])
    run_ids = await MonitorSchedulerService().dispatch_monitor_run(
        session,
        monitor,
        urls,
    )
    if not run_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Monitor run was not dispatched",
    )
    return MonitorRunNowResponse(
        run_id=run_ids[0],
        run_ids=run_ids,
        dispatched_at=utcnow(),
        url_count=len(urls),
    )


@router.get("/{monitor_id}/events")
async def monitor_events(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    event_type: Annotated[str | None, Query()] = None,
    field_name: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    await _require_monitor(session, monitor_id)
    if event_type and event_type not in MONITOR_EVENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid event_type")
    rows, total = await list_events(
        session,
        monitor_id=monitor_id,
        page=page,
        limit=page_size,
        event_type=event_type,
        field_name=field_name,
    )
    return {
        "items": [MonitorEventResponse.model_validate(row, from_attributes=True) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{monitor_id}/history")
async def monitor_history(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, object]:
    await _require_monitor(session, monitor_id)
    rows, total = await list_snapshots(session, monitor_id=monitor_id, page=page, limit=page_size)
    return {
        "items": [MonitorSnapshotResponse.model_validate(row, from_attributes=True) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{monitor_id}/snapshot/current")
async def monitor_current_snapshot(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> list[MonitorSnapshotRecordResponse]:
    await _require_monitor(session, monitor_id)
    rows = await current_snapshot_records(session, monitor_id=monitor_id)
    return [MonitorSnapshotRecordResponse.model_validate(row, from_attributes=True) for row in rows]


@router.get("/{monitor_id}/export/events.json")
async def monitor_export_events_json(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=EXPORT_PAGE_SIZE_MAX)] = 200,
) -> list[MonitorEventResponse]:
    await _require_monitor(session, monitor_id)
    rows, _ = await list_events(
        session,
        monitor_id=monitor_id,
        page=page,
        limit=page_size,
    )
    return [MonitorEventResponse.model_validate(row, from_attributes=True) for row in rows]


@router.get("/{monitor_id}/export/events.csv")
async def monitor_export_events_csv(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=EXPORT_PAGE_SIZE_MAX)] = 200,
) -> Response:
    await _require_monitor(session, monitor_id)
    rows, _ = await list_events(
        session,
        monitor_id=monitor_id,
        page=page,
        limit=page_size,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "monitor_id",
            "run_id",
            "source_url",
            "event_type",
            "field_name",
            "old_value",
            "new_value",
            "detected_at",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.id,
                row.monitor_id,
                row.run_id,
                row.source_url,
                row.event_type,
                row.field_name or "",
                row.old_value,
                row.new_value,
                row.detected_at.isoformat(),
            ]
        )
    return Response(content=buffer.getvalue(), media_type="text/csv")


@router.get("/{monitor_id}/export/snapshot.json")
async def monitor_export_snapshot_json(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> list[MonitorSnapshotRecordResponse]:
    return await monitor_current_snapshot(monitor_id, session, _user)


@router.get("/{monitor_id}/export/history.json")
async def monitor_export_history_json(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    await _require_monitor(session, monitor_id)
    snapshots, _ = await list_snapshots(
        session,
        monitor_id=monitor_id,
        page=1,
        limit=EXPORT_PAGE_SIZE_MAX,
    )
    records = await list_snapshot_records(
        session,
        monitor_id=monitor_id,
        limit=EXPORT_HISTORY_RECORD_LIMIT,
    )
    return {
        "monitor_id": monitor_id,
        "snapshots": [
            MonitorSnapshotResponse.model_validate(row, from_attributes=True)
            for row in snapshots
        ],
        "records": [
            MonitorSnapshotRecordResponse.model_validate(row, from_attributes=True)
            for row in records
        ],
    }


async def _require_monitor(session: AsyncSession, monitor_id: int):
    try:
        return await get_monitor(session, monitor_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


async def _monitor_response(session: AsyncSession, monitor) -> MonitorJobResponse:
    response = MonitorJobResponse.model_validate(monitor, from_attributes=True)
    response.change_count = await monitor_change_count_since(session, monitor_id=monitor.id)
    return response
