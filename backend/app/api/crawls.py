# Crawl run route handlers.
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Annotated, Any, cast

from app.api.run_access import (
    get_accessible_run_or_404 as _get_accessible_run_or_404,
    raise_http_from_exception as _raise_http_from_exception,
)
from app.core.dependencies import get_current_user, get_db
from app.models.crawl_run import CrawlRun
from app.models.user import User
from app.schemas.common import PaginatedResponse, PaginationMeta, RunEventResponse
from app.schemas.crawl import (
    CategoryDiscoveryRequest,
    CategoryDiscoveryResponse,
    CrawlCreate,
    CrawlRunResponse,
    FieldCommitRequest,
    FieldCommitResponse,
)
from app.crawl.access_service import (
    RUN_NOT_FOUND_DETAIL,
    require_accessible_run,
)
from app.crawl.category_discovery import discover_category_urls
from app.crawl.crud import (
    commit_selected_fields,
    delete_run,
    list_runs,
)
from app.crawl.run_events import run_event_timeline
from app.crawl.ingestion_service import (
    create_crawl_run_from_csv,
    create_crawl_run_from_payload,
)
from app.crawl.run_event_stream import (
    load_accessible_run_event_run,
    load_run_event_stream_snapshot,
    resolve_run_event_stream_user,
)
from app.crawl.service import kill_run, pause_run, resume_run
from app.crawl.state import TERMINAL_STATUSES
from app.core.config import get_frontend_origins, settings
from app.core.config.runtime_settings import crawler_runtime_settings
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/crawls", tags=["crawls"])

logger = logging.getLogger("app.api.crawls")

RUN_CONFLICT_DETAIL = "Run cannot be cancelled in its current state"
ResponseSpec = dict[int | str, dict[str, Any]]

# Max accepted size for CSV run-upload payloads; read at import time so tests can
# monkeypatch the module constant (value sourced from core config settings).
CSV_UPLOAD_MAX_BYTES = settings.csv_upload_max_bytes

RUN_NOT_FOUND_RESPONSE: ResponseSpec = {
    status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
}
RUN_CONFLICT_RESPONSE: ResponseSpec = {
    **RUN_NOT_FOUND_RESPONSE,
    status.HTTP_409_CONFLICT: {"description": RUN_CONFLICT_DETAIL},
}
_WEBSOCKET_PROTOCOL_TRANSFER_TASK_ATTR = "transfer_data_task"


def _run_event_stream_sleep_seconds() -> float:
    try:
        return max(
            0.001,
            float(crawler_runtime_settings.cooperative_sleep_poll_ms) / 1000,
        )
    except (TypeError, ValueError):
        logger.warning(
            "Invalid cooperative_sleep_poll_ms=%r; using 0.001s Run Event stream poll interval",
            crawler_runtime_settings.cooperative_sleep_poll_ms,
        )
        return 0.001


def _run_event_stream_max_poll_seconds() -> float:
    try:
        return max(
            0.001,
            float(crawler_runtime_settings.run_event_stream_max_poll_ms) / 1000,
        )
    except (TypeError, ValueError):
        logger.warning(
            "Invalid run_event_stream_max_poll_ms=%r; using 5s Run Event stream max poll interval",
            crawler_runtime_settings.run_event_stream_max_poll_ms,
        )
        return 5.0


def _websocket_token(websocket: WebSocket) -> str | None:
    token = websocket.cookies.get("access_token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        scheme, _, credentials = auth_header.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            token = credentials.strip()
    return token


def _websocket_origin_allowed(websocket: WebSocket) -> bool:
    # Browser clients always send Origin; cross-origin browser connections are
    # rejected because the cookie-authenticated handshake is otherwise a CSWSH
    # vector. Absent Origin means a non-browser client — the token still gates.
    origin = str(websocket.headers.get("origin") or "").strip()
    if not origin:
        return True
    return origin in get_frontend_origins()


# WebSocket disconnect compatibility: Some WebSocket implementations raise
# AttributeError for transfer_data_task when client disconnects abruptly
def _is_websocket_disconnect_compat_error(exc: Exception) -> bool:
    if not isinstance(exc, AttributeError):
        return False
    message = str(exc)
    return (
        "WebSocketProtocol" in message
        and _WEBSOCKET_PROTOCOL_TRANSFER_TASK_ATTR in message
    )


async def _mutate_run_status(
    session: AsyncSession,
    *,
    run_id: int,
    user: User,
    action: Callable[[AsyncSession, CrawlRun], Any],
) -> dict[str, object]:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    try:
        updated = await action(session, run)
    except ValueError as exc:
        _raise_http_from_exception(
            status_code=status.HTTP_409_CONFLICT,
            exc=exc,
        )
    return {"run_id": updated.id, "status": updated.status}


async def _close_websocket_safely(
    websocket: WebSocket, *, code: int, reason: str
) -> None:
    """Reject unauthenticated websocket handshakes without accepting the client."""
    await websocket.close(code=code, reason=reason)


@router.post(
    "",
    responses={status.HTTP_400_BAD_REQUEST: {"description": "Invalid crawl request"}},
)
async def crawls_create(
    payload: CrawlCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    try:
        run = await create_crawl_run_from_payload(
            session, user.id, payload.model_dump()
        )
    except ValueError as exc:
        _raise_http_from_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            exc=exc,
        )
    return {"run_id": run.id}


@router.post("/category-discovery")
async def crawls_category_discovery(
    payload: CategoryDiscoveryRequest,
    _user: Annotated[User, Depends(get_current_user)],
) -> CategoryDiscoveryResponse:
    result = await discover_category_urls(
        payload.selected_urls(),
        limit=payload.limit,
        max_depth=payload.max_depth,
        max_pages=payload.max_pages,
        strategy=payload.strategy,
        validate_candidates=payload.validate_candidates,
    )
    return CategoryDiscoveryResponse.model_validate(result)


@router.post(
    "/csv",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid CSV crawl request or no valid URLs found"
        }
    },
)
async def crawls_create_csv(
    file: Annotated[UploadFile, File(...)],
    surface: Annotated[str, Form(...)],
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    additional_fields: Annotated[str, Form()] = "",
    settings_json: Annotated[str, Form()] = "{}",
) -> dict:
    """Create a crawl run from an uploaded CSV file."""
    # Bounded read: reject oversized uploads with 413 instead of buffering the
    # entire request body in API-process memory.
    raw = await file.read(CSV_UPLOAD_MAX_BYTES + 1)
    if len(raw) > CSV_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(f"CSV upload exceeds the {CSV_UPLOAD_MAX_BYTES}-byte size limit"),
        )
    content = raw.decode("utf-8", errors="ignore")
    try:
        run, url_count = await create_crawl_run_from_csv(
            session,
            user.id,
            csv_content=content,
            surface=surface,
            additional_fields=additional_fields,
            settings_json=settings_json,
        )
    except ValueError as exc:
        _raise_http_from_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            exc=exc,
        )
    return {"run_id": run.id, "url_count": url_count}


@router.get("")
async def crawls_list(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    run_type: str = "",
    status_value: Annotated[str, Query(alias="status")] = "",
    url_search: str = "",
) -> PaginatedResponse[CrawlRunResponse]:
    user_id = None
    if user.role != "admin":
        user_id = user.id
    rows, total = await list_runs(
        session, page, limit, status_value, run_type, url_search, user_id=user_id
    )
    return PaginatedResponse(
        items=[
            CrawlRunResponse.model_validate(row, from_attributes=True) for row in rows
        ],
        meta=PaginationMeta(page=page, limit=limit, total=total),
    )


@router.get("/{run_id:int}", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_detail(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> CrawlRunResponse:
    try:
        run = await require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return CrawlRunResponse.model_validate(run, from_attributes=True)


@router.delete(
    "/{run_id:int}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=RUN_CONFLICT_RESPONSE,
)
async def crawls_delete(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    try:
        run = await require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    try:
        await delete_run(session, run)
    except ValueError as exc:
        _raise_http_from_exception(
            status_code=status.HTTP_409_CONFLICT,
            exc=exc,
        )


@router.post("/{run_id:int}/pause", responses=RUN_CONFLICT_RESPONSE)
async def crawls_pause(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return await _mutate_run_status(
        session,
        run_id=run_id,
        user=user,
        action=pause_run,
    )


@router.post("/{run_id:int}/commit-fields", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_commit_fields(
    run_id: int,
    payload: FieldCommitRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> FieldCommitResponse:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    updated_records, updated_fields = await commit_selected_fields(
        session,
        run=run,
        items=[item.model_dump() for item in payload.items],
    )
    return FieldCommitResponse(
        run_id=run.id, updated_records=updated_records, updated_fields=updated_fields
    )


@router.post("/{run_id:int}/resume", responses=RUN_CONFLICT_RESPONSE)
async def crawls_resume(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return await _mutate_run_status(
        session,
        run_id=run_id,
        user=user,
        action=resume_run,
    )


@router.post(
    "/{run_id:int}/kill",
    responses=cast(
        ResponseSpec,
        {
            status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
            status.HTTP_409_CONFLICT: {
                "description": "Run cannot be killed in its current state"
            },
        },
    ),
)
async def crawls_kill(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return await _mutate_run_status(
        session,
        run_id=run_id,
        user=user,
        action=kill_run,
    )


@router.get("/{run_id:int}/events", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_events(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    after_sequence: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> list[RunEventResponse]:
    try:
        await require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    rows = await run_event_timeline.list_after(
        run_id=run_id, after_sequence=after_sequence, limit=limit
    )
    return [RunEventResponse.model_validate(row, from_attributes=True) for row in rows]


@router.websocket("/{run_id:int}/events/ws")
async def crawls_events_ws(
    websocket: WebSocket, run_id: int, after_sequence: int | None = None
) -> None:
    if not _websocket_origin_allowed(websocket):
        await _close_websocket_safely(websocket, code=1008, reason="Origin not allowed")
        return
    if after_sequence is not None and after_sequence < 0:
        await _close_websocket_safely(websocket, code=1008, reason="Invalid cursor")
        return
    user = await resolve_run_event_stream_user(_websocket_token(websocket))
    if user is None:
        await _close_websocket_safely(websocket, code=1008, reason="Not authenticated")
        return

    try:
        run = await load_accessible_run_event_run(run_id=run_id, user=user)
    except ValueError:
        await _close_websocket_safely(websocket, code=1008, reason=RUN_NOT_FOUND_DETAIL)
        return

    await websocket.accept()
    cursor = after_sequence
    base_poll_interval_seconds = _run_event_stream_sleep_seconds()
    max_poll_interval_seconds = max(
        base_poll_interval_seconds, _run_event_stream_max_poll_seconds()
    )
    poll_interval_seconds = base_poll_interval_seconds
    missing_run_snapshots = 0
    event_run_id = int(run_id)
    try:
        await _stream_run_event_snapshots(
            websocket,
            run_id=run_id,
            cursor=cursor,
            run=run,
            base_poll_interval_seconds=base_poll_interval_seconds,
            max_poll_interval_seconds=max_poll_interval_seconds,
            poll_interval_seconds=poll_interval_seconds,
            missing_run_snapshots=missing_run_snapshots,
        )

    except WebSocketDisconnect:
        return
    except Exception as exc:
        if _is_websocket_disconnect_compat_error(exc):
            return
        logger.exception(
            "Run Event websocket stream failed",
            extra={"run_id": event_run_id},
        )
        try:
            await websocket.close(
                code=1011, reason=f"stream_error: {type(exc).__name__}"
            )
        except Exception:
            logger.debug("Failed to close websocket after stream error", exc_info=True)


async def _stream_run_event_snapshots(
    websocket: WebSocket,
    *,
    run_id: int,
    cursor: int | None,
    run: CrawlRun,
    base_poll_interval_seconds: float,
    max_poll_interval_seconds: float,
    poll_interval_seconds: float,
    missing_run_snapshots: int,
) -> None:
    last_status_value = run.status_value
    while True:
        rows, next_run = await load_run_event_stream_snapshot(
            run_id=run_id, after_sequence=cursor
        )
        for row in rows:
            payload = RunEventResponse.model_validate(
                row, from_attributes=True
            ).model_dump(mode="json")
            await websocket.send_json(payload)
            cursor = row.sequence
        status_changed = False
        if next_run is None:
            missing_run_snapshots += 1
            logger.warning(
                "Run Event snapshot did not reload run; retrying",
                extra={"run_id": int(run_id)},
            )
            if missing_run_snapshots >= 3:
                await websocket.close(code=1011, reason="Run snapshot unavailable")
                return
        else:
            missing_run_snapshots = 0
            status_changed = (
                next_run.status_value != last_status_value
                and next_run.status_value not in TERMINAL_STATUSES
            )
            run = next_run
            last_status_value = run.status_value
        if run.status_value in TERMINAL_STATUSES and not rows:
            await websocket.close(code=1000, reason="Run completed")
            return
        await asyncio.sleep(poll_interval_seconds)
        poll_interval_seconds = (
            base_poll_interval_seconds
            if rows or status_changed
            else min(poll_interval_seconds * 2, max_poll_interval_seconds)
        )
