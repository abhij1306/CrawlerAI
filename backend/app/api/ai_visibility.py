"""AI-search visibility benchmark API.

The provider API key is read server-side only (see ``ai_visibility_settings``);
it is never accepted, returned, or serialized by any endpoint here.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_visibility import exports
from app.ai_visibility.constants import BEST_AND_LESS_PROJECT, BEST_AND_LESS_PROMPTS
from app.ai_visibility.runner import run_benchmark
from app.ai_visibility.service import (
    cancel_run,
    create_project,
    create_run,
    delete_run,
    delete_project,
    get_execution,
    get_project,
    get_run,
    list_executions,
    list_projects,
    list_runs,
    update_project,
)
from app.core.config.ai_visibility import (
    AI_VISIBILITY_PROVIDER_GEMINI,
    AI_VISIBILITY_PROVIDER_OPENROUTER_ANTHROPIC,
    AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI,
    ai_visibility_settings,
)
from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.ai_visibility import (
    AiVisibilityExecutionResponse,
    AiVisibilityProjectCreate,
    AiVisibilityProjectResponse,
    AiVisibilityProjectUpdate,
    AiVisibilityProviderStatus,
    AiVisibilityRunCreate,
    AiVisibilityRunDetailResponse,
    AiVisibilityRunResponse,
)

router = APIRouter(prefix="/api/ai-visibility", tags=["ai-visibility"])
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Provider status
# --------------------------------------------------------------------------
@router.get("/presets/best-and-less")
async def ai_visibility_best_and_less_preset(
    _user: Annotated[User, Depends(get_current_user)],
) -> AiVisibilityProjectCreate:
    """Return the canonical pilot preset from its single backend owner."""
    return AiVisibilityProjectCreate.model_validate(
        {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS}
    )


@router.get("/providers")
async def ai_visibility_providers(
    _user: Annotated[User, Depends(get_current_user)],
) -> list[AiVisibilityProviderStatus]:
    gemini_configured = bool(ai_visibility_settings.resolved_gemini_api_key())
    openrouter_configured = bool(ai_visibility_settings.resolved_openrouter_api_key())
    return [
        AiVisibilityProviderStatus(
            provider=AI_VISIBILITY_PROVIDER_GEMINI,
            label="Gemini grounded API direct",
            surface="google_gemini_grounded_api",
            configured=gemini_configured,
            model=ai_visibility_settings.model_for_provider(
                AI_VISIBILITY_PROVIDER_GEMINI
            ),
            supports_search_fanout=True,
            supports_citations=True,
        ),
        AiVisibilityProviderStatus(
            provider=AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI,
            label="OpenAI grounded API via OpenRouter",
            surface="openrouter_native_grounded_api",
            configured=openrouter_configured,
            model=ai_visibility_settings.model_for_provider(
                AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI
            ),
            supports_search_fanout=False,
            supports_citations=True,
        ),
        AiVisibilityProviderStatus(
            provider=AI_VISIBILITY_PROVIDER_OPENROUTER_ANTHROPIC,
            label="Anthropic grounded API via OpenRouter",
            surface="openrouter_native_grounded_api",
            configured=openrouter_configured,
            model=ai_visibility_settings.model_for_provider(
                AI_VISIBILITY_PROVIDER_OPENROUTER_ANTHROPIC
            ),
            supports_search_fanout=False,
            supports_citations=True,
        ),
    ]


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------
@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def ai_visibility_create_project(
    payload: AiVisibilityProjectCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AiVisibilityProjectResponse:
    project = await create_project(session, user=user, payload=payload.model_dump())
    return AiVisibilityProjectResponse.model_validate(project)


@router.get("/projects")
async def ai_visibility_list_projects(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AiVisibilityProjectResponse]:
    projects = await list_projects(session, user=user, limit=limit)
    return [AiVisibilityProjectResponse.model_validate(p) for p in projects]


@router.get("/projects/{project_id}")
async def ai_visibility_get_project(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AiVisibilityProjectResponse:
    try:
        project = await get_project(session, user=user, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return AiVisibilityProjectResponse.model_validate(project)


@router.patch("/projects/{project_id}")
async def ai_visibility_update_project(
    project_id: int,
    payload: AiVisibilityProjectUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AiVisibilityProjectResponse:
    try:
        project = await update_project(
            session,
            user=user,
            project_id=project_id,
            payload=payload.model_dump(exclude_unset=True),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return AiVisibilityProjectResponse.model_validate(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def ai_visibility_delete_project(
    project_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    try:
        await delete_project(session, user=user, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------
@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def ai_visibility_create_run(
    payload: AiVisibilityRunCreate,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AiVisibilityRunResponse:
    try:
        run = await create_run(
            session,
            user=user,
            project_id=payload.project_id,
            repetitions=payload.repetitions,
            prompt_indices=payload.prompt_indices,
            provider=payload.provider,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    background_tasks.add_task(run_benchmark, run.id)
    return AiVisibilityRunResponse.model_validate(run)


@router.get("/runs")
async def ai_visibility_list_runs(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    project_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AiVisibilityRunResponse]:
    runs = await list_runs(session, user=user, project_id=project_id, limit=limit)
    return [AiVisibilityRunResponse.model_validate(r) for r in runs]


@router.get("/runs/{run_id}")
async def ai_visibility_get_run(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AiVisibilityRunDetailResponse:
    try:
        run = await get_run(session, user=user, run_id=run_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    executions = await list_executions(session, run=run)
    return AiVisibilityRunDetailResponse(
        run=AiVisibilityRunResponse.model_validate(run),
        executions=[
            AiVisibilityExecutionResponse.model_validate(e) for e in executions
        ],
    )


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def ai_visibility_delete_run(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    try:
        await delete_run(session, user=user, run_id=run_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/runs/{run_id}/cancel")
async def ai_visibility_cancel_run(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AiVisibilityRunResponse:
    """Kill an active (or zombie) run: flip it to ``cancelled`` and terminalize
    its unfinished executions. A live worker stops cooperatively at its next
    execution boundary."""
    try:
        run = await cancel_run(session, user=user, run_id=run_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return AiVisibilityRunResponse.model_validate(run)


@router.get("/runs/{run_id}/executions")
async def ai_visibility_list_run_executions(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[AiVisibilityExecutionResponse]:
    try:
        run = await get_run(session, user=user, run_id=run_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    executions = await list_executions(session, run=run)
    return [AiVisibilityExecutionResponse.model_validate(e) for e in executions]


@router.get("/runs/{run_id}/export.csv")
async def ai_visibility_export_csv(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlainTextResponse:
    try:
        run = await get_run(session, user=user, run_id=run_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    executions = await list_executions(session, run=run)
    body = exports.run_to_csv(run, executions)
    return PlainTextResponse(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="ai-visibility-run-{run_id}.csv"'
            )
        },
    )


@router.get("/runs/{run_id}/export.md")
async def ai_visibility_export_markdown(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlainTextResponse:
    try:
        run = await get_run(session, user=user, run_id=run_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    executions = await list_executions(session, run=run)
    body = exports.run_to_markdown(run, executions)
    return PlainTextResponse(
        content=body,
        media_type="text/markdown",
        headers={
            "Content-Disposition": (
                f'attachment; filename="ai-visibility-run-{run_id}.md"'
            )
        },
    )


# --------------------------------------------------------------------------
# Executions
# --------------------------------------------------------------------------
@router.get("/executions/{execution_id}")
async def ai_visibility_get_execution(
    execution_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AiVisibilityExecutionResponse:
    try:
        execution = await get_execution(session, user=user, execution_id=execution_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return AiVisibilityExecutionResponse.model_validate(execution)
