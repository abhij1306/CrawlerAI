from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_run import CrawlRun
from app.models.user import User
from app.services.crawl.access_service import require_accessible_run


def raise_http_from_exception(*, status_code: int, exc: Exception) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


async def get_accessible_run_or_404(
    session: AsyncSession,
    *,
    run_id: int,
    user: User,
    detail: str | None = None,
) -> CrawlRun:
    try:
        return await require_accessible_run(session, run_id=run_id, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail if detail is not None else str(exc),
        ) from exc
