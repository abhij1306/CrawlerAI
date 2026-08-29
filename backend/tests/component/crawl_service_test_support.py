from __future__ import annotations

import asyncio

import logging

from datetime import UTC, datetime, timedelta

import pytest

from app.core import database as database_module

from app.core import dependencies as dependencies_module

from app.core.config import settings

from app.core.config.runtime_settings import crawler_runtime_settings

from app.models.crawl_run import CrawlRecord, CrawlRun

from app.models.domain_memory import DomainRunProfile

from app.models.extraction_memory import ExtractionOperatorLabel as ReviewPromotion

from app.models.crawl_domain import CONTROL_REQUEST_KILL, CONTROL_REQUEST_PAUSE

from app.models.crawl_settings import normalize_crawl_settings

from app.crawl import service as crawl_service

from app.workers import celery_dispatcher as celery_dispatch_module

from app.workers import local_dispatcher as local_dispatch_module

from app.crawl.crud import (
    commit_selected_fields,
    create_crawl_run,
    delete_run,
)

from app.crawl.profile import (
    apply_acquisition_contract_to_profile,
    build_success_acquisition_contract,
    load_domain_run_profile,
    note_acquisition_contract_failure,
    normalize_acquisition_contract,
    normalize_domain_run_profile,
    record_acquisition_contract_outcome,
    resolve_url_acquisition_recipe,
    save_domain_run_profile,
)

from app.core.exceptions import CrawlerConfigurationError

from app.crawl.state import get_control_request, update_run_status

from sqlalchemy import select

from sqlalchemy.exc import ProgrammingError

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _create_running_run(
    db_session: AsyncSession,
    *,
    user_id: int,
    url: str = "https://example.com/jobs/1",
) -> CrawlRun:
    run = await create_crawl_run(
        db_session,
        user_id,
        {
            "run_type": "crawl",
            "url": url,
            "surface": "job_detail",
        },
    )
    update_run_status(run, "running")
    run.update_summary(celery_task_id=f"crawl-run-{run.id}")
    await db_session.commit()
    await db_session.refresh(run)
    return run


__all__ = [
    "CONTROL_REQUEST_KILL",
    "CONTROL_REQUEST_PAUSE",
    "UTC",
    "AsyncSession",
    "CrawlRecord",
    "CrawlRun",
    "CrawlerConfigurationError",
    "DomainRunProfile",
    "ProgrammingError",
    "ReviewPromotion",
    "_create_running_run",
    "apply_acquisition_contract_to_profile",
    "async_sessionmaker",
    "asyncio",
    "build_success_acquisition_contract",
    "celery_dispatch_module",
    "commit_selected_fields",
    "crawl_service",
    "crawler_runtime_settings",
    "create_crawl_run",
    "database_module",
    "datetime",
    "delete_run",
    "dependencies_module",
    "get_control_request",
    "load_domain_run_profile",
    "local_dispatch_module",
    "logging",
    "normalize_acquisition_contract",
    "normalize_crawl_settings",
    "normalize_domain_run_profile",
    "note_acquisition_contract_failure",
    "pytest",
    "record_acquisition_contract_outcome",
    "resolve_url_acquisition_recipe",
    "save_domain_run_profile",
    "select",
    "settings",
    "timedelta",
    "update_run_status",
]
