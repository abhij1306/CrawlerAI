from __future__ import annotations

import asyncio

from app.core.database import SessionLocal
from app.services.crawl.crud import get_run_records
from app.services.config.runtime_settings import crawler_runtime_settings
from sqlalchemy.ext.asyncio import AsyncSession


def summary_expects_records(summary: object) -> bool:
    if not isinstance(summary, dict):
        return False
    try:
        return int(summary.get("record_count", 0) or 0) > 0
    except (TypeError, ValueError):
        return False


async def load_records_with_reconciliation(
    session: AsyncSession,
    *,
    run_id: int,
    run_summary: object,
    page: int,
    limit: int,
) -> tuple[list, int]:
    rows, total = await get_run_records(session, run_id, page, limit)
    if rows or total or page != 1 or not summary_expects_records(run_summary):
        return rows, total

    retry_attempts = max(0, crawler_runtime_settings.records_read_retry_attempts)
    retry_delay_seconds = max(
        0.0, crawler_runtime_settings.records_read_retry_delay_ms / 1000
    )
    for _ in range(retry_attempts):
        if retry_delay_seconds > 0:
            await asyncio.sleep(retry_delay_seconds)
        async with SessionLocal() as retry_session:
            retry_rows, retry_total = await get_run_records(
                retry_session, run_id, page, limit
            )
        if retry_rows or retry_total:
            return retry_rows, retry_total
    return rows, total


__all__ = ["load_records_with_reconciliation", "summary_expects_records"]
