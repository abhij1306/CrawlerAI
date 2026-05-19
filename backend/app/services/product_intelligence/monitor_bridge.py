from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.monitor import MonitorJob
from app.models.product_intelligence import ProductIntelligenceJob, ProductIntelligenceMatch
from app.services.config.product_intelligence import PRODUCT_INTELLIGENCE_REVIEW_ACCEPTED
from app.services.config.monitor_settings import (
    MONITOR_PRIORITY_BACKGROUND,
    PRODUCT_INTELLIGENCE_MONITOR_DEFAULT_SCHEDULE_HOURS,
    PRODUCT_INTELLIGENCE_MONITOR_DEFAULT_SURFACE,
    PRODUCT_INTELLIGENCE_MONITOR_DEFAULT_TRACKED_FIELDS,
    SKIP_HEAD_CHECK_KEY,
)
from app.services.monitor_service import create_monitor

logger = logging.getLogger(__name__)


async def create_monitor_from_job(
    session: AsyncSession,
    *,
    job_id: int,
    user: User,
    name: str | None = None,
    schedule_interval_hours: int | None = None,
    tracked_fields: list[str] | None = None,
    priority: str | None = None,
) -> MonitorJob:
    job = await session.get(ProductIntelligenceJob, job_id)
    if not job:
        raise LookupError(f"Product intelligence job {job_id} not found")

    # Fetch accepted matches
    stmt = select(ProductIntelligenceMatch).where(
        ProductIntelligenceMatch.job_id == job_id,
        ProductIntelligenceMatch.review_status == PRODUCT_INTELLIGENCE_REVIEW_ACCEPTED,
    )
    matches = (await session.scalars(stmt)).all()
    urls = sorted(list(set(m.candidate_url for m in matches if m.candidate_url)))

    if not urls:
        raise ValueError("No accepted match URLs found to monitor")

    monitor_name = name or f"PI Job #{job_id} - Accepted Matches"
    
    payload = {
        "name": monitor_name,
        "urls": urls,
        "surface": PRODUCT_INTELLIGENCE_MONITOR_DEFAULT_SURFACE,
        "tracked_fields": tracked_fields or PRODUCT_INTELLIGENCE_MONITOR_DEFAULT_TRACKED_FIELDS,
        "schedule_interval_hours": (
            schedule_interval_hours or PRODUCT_INTELLIGENCE_MONITOR_DEFAULT_SCHEDULE_HOURS
        ),
        "priority": priority or MONITOR_PRIORITY_BACKGROUND,
        "settings": {
            # PI monitors always do full scheduled crawls for content sampling accuracy.
            # Users cannot opt out of full crawls for monitors created from PI workflows.
            SKIP_HEAD_CHECK_KEY: True
        }
    }

    logger.info(
        "Creating monitor from PI job matches job_id=%s name=%r url_count=%s",
        job_id,
        monitor_name,
        len(urls),
    )
    return await create_monitor(session, user=user, payload=payload)
