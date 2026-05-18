from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.ucp_audit import (
    UCPAuditJobCreate,
    UCPAuditJobDetailResponse,
    UCPAuditJobResponse,
)
from app.services.ucp_audit.service import (
    build_ucp_audit_job_payload,
    create_ucp_audit_job,
    get_ucp_audit_job,
    get_ucp_audit_report,
    list_ucp_audit_jobs,
    run_ucp_audit_job,
)

router = APIRouter(prefix="/api/ucp-audit", tags=["ucp-audit"])


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    payload: UCPAuditJobCreate,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> UCPAuditJobResponse:
    try:
        job = await create_ucp_audit_job(
            session,
            user=user,
            payload=payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    background_tasks.add_task(run_ucp_audit_job, job.id)
    return UCPAuditJobResponse.model_validate(job, from_attributes=True)


@router.get("/jobs")
async def list_jobs(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[UCPAuditJobResponse]:
    jobs = await list_ucp_audit_jobs(session, user=user, limit=limit)
    return [
        UCPAuditJobResponse.model_validate(job, from_attributes=True)
        for job in jobs
    ]


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> UCPAuditJobDetailResponse:
    try:
        job = await get_ucp_audit_job(session, user=user, job_id=job_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    payload = await build_ucp_audit_job_payload(session, job=job)
    return UCPAuditJobDetailResponse.model_validate(payload)


@router.get("/jobs/{job_id}/export.json")
async def export_json(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    try:
        await get_ucp_audit_job(session, user=user, job_id=job_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    report = await get_ucp_audit_report(session, job_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return JSONResponse(report.report_json)


@router.get("/jobs/{job_id}/export.md")
async def export_markdown(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlainTextResponse:
    try:
        await get_ucp_audit_job(session, user=user, job_id=job_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    report = await get_ucp_audit_report(session, job_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return PlainTextResponse(report.markdown_report)
