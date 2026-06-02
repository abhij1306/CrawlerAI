"""Playground API — guided pipeline for non-technical users."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.playground import (
    PlaygroundDiscoverResponse,
    PlaygroundExtractResponse,
    PlaygroundPipelineRequest,
    PlaygroundPipelineResponse,
    PlaygroundSelectCategoryRequest,
    PlaygroundSelectRequest,
    PlaygroundSessionCreate,
    PlaygroundSessionResponse,
)
from app.services.playground_service import (
    create_session,
    get_results,
    get_session,
    list_sessions,
    select_category,
    select_products,
    start_discover,
    start_extract,
    start_pipeline,
)

router = APIRouter(prefix="/api/playground", tags=["playground"])


def _session_response(playground) -> PlaygroundSessionResponse:
    return PlaygroundSessionResponse(
        id=playground.id,
        input_url=playground.input_url,
        state=playground.state,
        step_data=playground.step_data,
        created_at=playground.created_at,
        updated_at=playground.updated_at,
    )


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def playground_create_session(
    payload: PlaygroundSessionCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlaygroundSessionResponse:
    """Create a new playground session with a starting URL."""
    try:
        playground = await create_session(
            session,
            user=user,
            url=None,
            urls=payload.selected_urls(),
            category_limit=payload.category_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    response = _session_response(playground)
    await session.commit()
    return response


@router.get("/sessions")
async def playground_list_sessions(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[PlaygroundSessionResponse]:
    """List recent playground sessions."""
    items = await list_sessions(session, user=user, limit=limit)
    return [
        _session_response(item)
        for item in items
    ]


@router.get("/sessions/{session_id}")
async def playground_get_session(
    session_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlaygroundSessionResponse:
    """Get playground session state."""
    try:
        playground = await get_session(session, session_id=session_id, user=user)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    response = _session_response(playground)
    await session.commit()
    return response


@router.post("/sessions/{session_id}/discover")
async def playground_discover(
    session_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlaygroundDiscoverResponse:
    """Route the input URL into the right entry stage (sitemap, listing, or detail)."""
    try:
        playground = await get_session(session, session_id=session_id, user=user)
        result = await start_discover(session, playground=playground, user=user)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    stage = str(result.get("stage", ""))
    if stage == "sitemap":
        message = (
            f"Sitemap returned {result.get('url_count', 0)} URL(s) — pick a category to crawl."
        )
    elif stage == "detail":
        message = "Detail URL detected — extracting directly."
    else:
        message = "Category crawl started — poll session for results."
    response = PlaygroundDiscoverResponse(
        session_id=playground.id,
        state=playground.state,
        stage=stage,
        run_id=result.get("run_id") if isinstance(result.get("run_id"), int) else None,
        sitemap_url_count=result.get("url_count") if stage == "sitemap" else None,
        message=message,
    )
    await session.commit()
    return response


@router.post("/sessions/{session_id}/select-category")
async def playground_select_category(
    session_id: int,
    payload: PlaygroundSelectCategoryRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlaygroundSessionResponse:
    """User picked a category URL from the sitemap; start a category crawl."""
    try:
        playground = await get_session(session, session_id=session_id, user=user)
        await select_category(
            session,
            playground=playground,
            user=user,
            urls=payload.selected_urls(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.refresh(playground)
    response = _session_response(playground)
    await session.commit()
    return response


@router.post("/sessions/{session_id}/select")
async def playground_select(
    session_id: int,
    payload: PlaygroundSelectRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlaygroundSessionResponse:
    """Select products to extract (max 50)."""
    try:
        playground = await get_session(session, session_id=session_id, user=user)
        await select_products(session, playground=playground, urls=payload.urls)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.refresh(playground)
    response = _session_response(playground)
    await session.commit()
    return response


@router.post("/sessions/{session_id}/extract")
async def playground_extract(
    session_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlaygroundExtractResponse:
    """Start PDP extraction for selected products."""
    try:
        playground = await get_session(session, session_id=session_id, user=user)
        run_ids = await start_extract(session, playground=playground, user=user)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    url_count = len(playground.step_data.get("selected_urls", []))
    response = PlaygroundExtractResponse(
        session_id=playground.id,
        state=playground.state,
        run_ids=run_ids,
        url_count=url_count,
    )
    await session.commit()
    return response


@router.post("/sessions/{session_id}/pipeline")
async def playground_pipeline(
    session_id: int,
    payload: PlaygroundPipelineRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlaygroundPipelineResponse:
    """Run selected downstream operations (enrich, compare, monitor, audit)."""
    try:
        playground = await get_session(session, session_id=session_id, user=user)
        launched, dispatch_specs = await start_pipeline(
            session,
            playground=playground,
            user=user,
            enrich=payload.enrich,
            compare=payload.compare,
            monitor=payload.monitor,
            audit=payload.audit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    response = PlaygroundPipelineResponse(
        session_id=playground.id,
        state=playground.state,
        launched=launched,
    )
    await session.commit()
    # Dispatch the background runners after commit so the worker can find
    # the freshly-created job rows.
    for runner, job_id in dispatch_specs:
        background_tasks.add_task(runner, job_id)
    return response


@router.get("/sessions/{session_id}/results")
async def playground_results(
    session_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Get aggregated results from all pipeline steps."""
    try:
        playground = await get_session(session, session_id=session_id, user=user)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    results = await get_results(session, playground=playground)
    await session.commit()
    return results
