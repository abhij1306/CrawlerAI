from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.page_audit import (
    PageAuditJobCreate,
    PageAuditJobDetailResponse,
    PageAuditJobResponse,
)
from app.services.page_audit.service import (
    build_page_audit_job_payload,
    create_page_audit_job,
    get_page_audit_job,
    get_page_audit_result,
    run_page_audit_job,
)

router = APIRouter(prefix="/api/page-audit", tags=["page-audit"])


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    payload: PageAuditJobCreate,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PageAuditJobResponse:
    try:
        job = await create_page_audit_job(
            session,
            user=user,
            payload=payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    background_tasks.add_task(run_page_audit_job, job.id)
    return PageAuditJobResponse.model_validate(job, from_attributes=True)


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PageAuditJobDetailResponse:
    try:
        job = await get_page_audit_job(session, user=user, job_id=job_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    payload = await build_page_audit_job_payload(session, job=job)
    return PageAuditJobDetailResponse.model_validate(payload)


@router.get("/jobs/{job_id}/export.json")
async def export_json(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    await _owned_job(session, user=user, job_id=job_id)
    result = await get_page_audit_result(session, job_id=job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page audit report not found",
        )
    return JSONResponse(result.report_json)


@router.get("/jobs/{job_id}/export.md")
async def export_markdown(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlainTextResponse:
    job = await _owned_job(session, user=user, job_id=job_id)
    result = await get_page_audit_result(session, job_id=job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page audit report not found",
        )
    hostname = quote(job.url.split("://", 1)[-1].split("/", 1)[0])
    return PlainTextResponse(
        result.markdown_report,
        headers={
            "Content-Disposition": (
                f'attachment; filename="page-technical-audit-{hostname}-{job_id}.md"'
            )
        },
    )


async def _owned_job(
    session: AsyncSession,
    *,
    user: User,
    job_id: int,
):
    try:
        return await get_page_audit_job(session, user=user, job_id=job_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
