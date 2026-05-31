# Read-only observability route: serves a run's trace + audit flags + LLM diagnosis.
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.crawl.access_service import (
    AccessDeniedError,
    RUN_NOT_FOUND_DETAIL,
    require_accessible_run,
)
from app.services.observability.artifact_reader import read_run_observability
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["observability"])


@router.get("/api/runs/{run_id}/observability")
async def get_run_observability(
    run_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    """Return the trace, audit flags, and LLM diagnosis for a run (read-only)."""
    try:
        await require_accessible_run(db, run_id=run_id, user=current_user)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND_DETAIL) from exc
    return read_run_observability(run_id)
