# Crawl run route handlers.
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Annotated, Any, NoReturn, cast

from app.core.dependencies import get_current_user, get_db
from app.models.crawl_run import CrawlRun
from app.models.user import User
from app.schemas.common import LogEntryResponse, PaginatedResponse, PaginationMeta
from app.schemas.crawl import (
    CrawlCreate,
    CrawlRunResponse,
    FieldCommitRequest,
    FieldCommitResponse,
)
from app.services.crawl.access_service import (
    RUN_NOT_FOUND_DETAIL,
    require_accessible_run,
)
from app.services.crawl.crud import (
    commit_llm_suggestions,
    commit_selected_fields,
    delete_run,
    get_run_logs,
    list_runs,
)
from app.services.crawl.events import serialize_log_event
from app.services.crawl.ingestion_service import (
    create_crawl_run_from_csv,
    create_crawl_run_from_payload,
)
from app.services.crawl.log_stream import (
    load_accessible_log_run,
    load_log_stream_snapshot,
    resolve_log_stream_user,
)
from app.services.crawl.service import kill_run, pause_run, resume_run
from app.services.crawl.state import TERMINAL_STATUSES
from app.services.config.runtime_settings import crawler_runtime_settings
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

RUN_NOT_FOUND_RESPONSE: ResponseSpec = {
    status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
}
RUN_CONFLICT_RESPONSE: ResponseSpec = {
    **RUN_NOT_FOUND_RESPONSE,
    status.HTTP_409_CONFLICT: {"description": RUN_CONFLICT_DETAIL},
}


def _log_stream_sleep_seconds() -> float:
    try:
        return max(
            0.001,
            float(crawler_runtime_settings.cooperative_sleep_poll_ms) / 1000,
        )
    except (TypeError, ValueError):
        logger.warning(
            "Invalid cooperative_sleep_poll_ms=%r; using 0.001s log stream poll interval",
            crawler_runtime_settings.cooperative_sleep_poll_ms,
        )
        return 0.001


def _websocket_token(websocket: WebSocket) -> str | None:
    token = websocket.cookies.get("access_token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        scheme, _, credentials = auth_header.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            token = credentials.strip()
    return token


def _raise_http_from_value_error(*, status_code: int, exc: ValueError) -> NoReturn:
    """Translate validation/business ValueError into HTTPException preserving cause."""
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


async def _get_accessible_run_or_404(
    session: AsyncSession,
    *,
    run_id: int,
    user: User,
) -> CrawlRun:
    try:
        return await require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


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
        _raise_http_from_value_error(
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
        _raise_http_from_value_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            exc=exc,
        )
    return {"run_id": run.id}


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
    content = (await file.read()).decode("utf-8", errors="ignore")
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
        _raise_http_from_value_error(
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
    "/{run_id:int}", status_code=status.HTTP_204_NO_CONTENT, responses=RUN_CONFLICT_RESPONSE
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
        _raise_http_from_value_error(
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


@router.post("/{run_id:int}/llm-commit", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_llm_commit(
    run_id: int,
    payload: FieldCommitRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> FieldCommitResponse:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    updated_records, updated_fields = await commit_llm_suggestions(
        session,
        run=run,
        items=[item.model_dump() for item in payload.items],
    )
    return FieldCommitResponse(
        run_id=run.id, updated_records=updated_records, updated_fields=updated_fields
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
    "/{run_id}/kill",
    responses=cast(ResponseSpec, {
        status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
        status.HTTP_409_CONFLICT: {
            "description": "Run cannot be killed in its current state"
        },
    }),
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


@router.post(
    "/{run_id}/cancel",
    responses=cast(ResponseSpec, {
        status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
        status.HTTP_409_CONFLICT: {"description": RUN_CONFLICT_DETAIL},
    }),
)
async def crawls_cancel(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return await crawls_kill(run_id, session, user)


@router.get("/{run_id:int}/logs", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_logs(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    after_id: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> list[LogEntryResponse]:
    try:
        await require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    rows = await get_run_logs(session, run_id, after_id=after_id, limit=limit)
    return [LogEntryResponse.model_validate(row, from_attributes=True) for row in rows]


@router.websocket("/{run_id}/logs/ws")
async def crawls_logs_ws(
    websocket: WebSocket, run_id: int, after_id: int | None = None
) -> None:
    user = await resolve_log_stream_user(_websocket_token(websocket))
    if user is None:
        await _close_websocket_safely(websocket, code=1008, reason="Not authenticated")
        return

    try:
        run = await load_accessible_log_run(run_id=run_id, user=user)
    except ValueError:
        await _close_websocket_safely(websocket, code=1008, reason=RUN_NOT_FOUND_DETAIL)
        return

    await websocket.accept()
    cursor = after_id
    poll_interval_seconds = _log_stream_sleep_seconds()
    missing_run_snapshots = 0
    try:
        while True:
            rows, next_run = await load_log_stream_snapshot(
                run_id=run_id,
                after_id=cursor,
            )

            for row in rows:
                await websocket.send_json(serialize_log_event(row))
                cursor = row.id

            if next_run is None:
                missing_run_snapshots += 1
                logger.warning(
                    "Run logs snapshot did not reload run %s; retrying",
                    run_id,
                )
                if missing_run_snapshots >= 3:
                    await websocket.close(code=1011, reason="Run snapshot unavailable")
                    return
            else:
                missing_run_snapshots = 0
                run = next_run
            if run.status_value in TERMINAL_STATUSES and not rows:
                await websocket.close(code=1000, reason="Run completed")
                return
            await asyncio.sleep(poll_interval_seconds)

    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.exception("Run logs websocket stream failed for run %s", run_id)
        try:
            await websocket.close(
                code=1011, reason=f"stream_error: {type(exc).__name__}"
            )
        except Exception:
            logger.debug("Failed to close websocket after stream error", exc_info=True)
