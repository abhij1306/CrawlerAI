from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.page_audit import PageAuditJob, PageAuditResult
from app.models.user import User
from app.services.config import page_audit as config
from app.services.fetch.fetch_context import fetch_page
from app.services.page_audit.analysis import analyze_page
from app.services.page_audit.reporting import build_markdown_report
from app.services.shared.url_utils import ensure_scheme
from app.services.url_safety import validate_public_target

logger = logging.getLogger(__name__)


async def create_page_audit_job(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, object],
) -> PageAuditJob:
    normalized_url = ensure_scheme(str(payload.get("url") or "").strip())
    await validate_public_target(normalized_url)
    context = str(
        payload.get("context") or config.PAGE_AUDIT_CONTEXT_AUTO
    ).strip().lower()
    if context not in config.PAGE_AUDIT_ALLOWED_CONTEXTS:
        raise ValueError("Unsupported page audit context")
    job = PageAuditJob(
        user_id=user.id,
        url=normalized_url,
        context=context,
        status=config.PAGE_AUDIT_JOB_STATUS_QUEUED,
        options={},
        summary={"critical_failure_count": 0, "scores": {}},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def run_page_audit_job(job_id: int) -> None:
    async with SessionLocal() as session:
        job = await session.scalar(
            select(PageAuditJob)
            .where(
                PageAuditJob.id == job_id,
                PageAuditJob.status == config.PAGE_AUDIT_JOB_STATUS_QUEUED,
            )
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return
        try:
            await _run_job(session, job)
        except Exception as exc:
            logger.exception("Page audit job failed: %s", job_id)
            await session.rollback()
            await session.refresh(job)
            job.status = config.PAGE_AUDIT_JOB_STATUS_FAILED
            job.summary = {
                **dict(job.summary or {}),
                "error": f"{type(exc).__name__}: {exc}",
            }
            job.completed_at = datetime.now(UTC)
            await session.commit()


async def _run_job(session: AsyncSession, job: PageAuditJob) -> None:
    job.status = config.PAGE_AUDIT_JOB_STATUS_RUNNING
    await session.commit()
    report = await build_page_audit_report(job.url, context=job.context)
    result = PageAuditResult(
        job_id=job.id,
        url=str(report.get("url") or job.url),
        report_json=report,
        markdown_report=build_markdown_report(report),
    )
    session.add(result)
    job.status = config.PAGE_AUDIT_JOB_STATUS_COMPLETE
    job.summary = {
        "critical_failure_count": len(report.get("critical_failures") or []),
        "scores": dict(report.get("scores") or {}),
    }
    job.completed_at = datetime.now(UTC)
    await session.commit()


async def get_page_audit_job(
    session: AsyncSession,
    *,
    user: User,
    job_id: int,
) -> PageAuditJob:
    job = await session.get(PageAuditJob, job_id)
    if job is None or (
        getattr(user, "role", "") != "admin" and job.user_id != user.id
    ):
        raise LookupError("Page audit job not found")
    return job


async def get_page_audit_result(
    session: AsyncSession,
    *,
    job_id: int,
) -> PageAuditResult | None:
    return await session.scalar(
        select(PageAuditResult).where(PageAuditResult.job_id == job_id)
    )


async def build_page_audit_job_payload(
    session: AsyncSession,
    *,
    job: PageAuditJob,
) -> dict[str, object]:
    result = await get_page_audit_result(session, job_id=job.id)
    return {"job": job, "result": result}


async def build_page_audit_report(
    url: str,
    *,
    context: str = config.PAGE_AUDIT_CONTEXT_AUTO,
) -> dict[str, Any]:
    normalized_url = ensure_scheme(str(url or "").strip())
    await validate_public_target(normalized_url)
    source_result = await fetch_page(
        normalized_url,
        timeout_seconds=config.PAGE_AUDIT_HTTP_TIMEOUT_SECONDS,
        fetch_mode=config.PAGE_AUDIT_SOURCE_FETCH_MODE,
        surface=config.PAGE_AUDIT_SURFACE,
        max_pages=1,
        max_scrolls=1,
    )
    dom_result = await fetch_page(
        normalized_url,
        timeout_seconds=config.PAGE_AUDIT_BROWSER_TIMEOUT_SECONDS,
        fetch_mode=config.PAGE_AUDIT_BROWSER_FETCH_MODE,
        prefer_browser=True,
        browser_reason=config.PAGE_AUDIT_BROWSER_REASON,
        surface=config.PAGE_AUDIT_SURFACE,
        max_pages=1,
        max_scrolls=1,
    )
    artifacts = (
        dict(getattr(dom_result, "artifacts", {}) or {})
        if isinstance(getattr(dom_result, "artifacts", {}), dict)
        else {}
    )
    dom_html = str(
        artifacts.get("full_rendered_html")
        or getattr(dom_result, "html", "")
        or ""
    )
    final_url = str(
        getattr(dom_result, "final_url", "")
        or getattr(source_result, "final_url", "")
        or normalized_url
    )
    report = analyze_page(
        url=final_url,
        source_html=str(getattr(source_result, "html", "") or ""),
        dom_html=dom_html,
        context=context,
    )
    browser_diagnostics = dict(
        getattr(dom_result, "browser_diagnostics", {}) or {}
    )
    report["render_summary"] = {
        **dict(report.get("render_summary") or {}),
        "source_method": str(getattr(source_result, "method", "") or ""),
        "dom_method": str(getattr(dom_result, "method", "") or ""),
        "source_status_code": int(getattr(source_result, "status_code", 0) or 0),
        "dom_status_code": int(getattr(dom_result, "status_code", 0) or 0),
        "browser_engine": str(browser_diagnostics.get("browser_engine") or ""),
        "browser_outcome": str(browser_diagnostics.get("browser_outcome") or ""),
    }
    return report
