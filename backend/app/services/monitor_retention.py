from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.monitor import (
    MonitorEvent,
    MonitorJob,
    MonitorSnapshot,
    MonitorSnapshotRecord,
    MonitorURLState,
)
from app.services.config.monitor_settings import MONITOR_STATUS_ARCHIVED
from app.services.monitor_service import utcnow

logger = logging.getLogger(__name__)
PURGE_BATCH_SIZE = 100


class MonitorRetentionService:
    async def purge_expired(self) -> None:
        async with SessionLocal() as session:
            await self.purge_expired_with_session(session)

    async def purge_expired_with_session(self, session: AsyncSession) -> None:
        now = utcnow()
        purged_count = 0
        last_id = 0
        while True:
            monitors = list(
                (
                    await session.scalars(
                        select(MonitorJob)
                        .where(MonitorJob.id > last_id)
                        .order_by(MonitorJob.id)
                        .limit(PURGE_BATCH_SIZE)
                    )
                )
                .all()
            )
            if not monitors:
                break
            for monitor in monitors:
                monitor_id = int(monitor.id)
                last_id = monitor_id
                try:
                    cutoff = now - timedelta(days=max(1, int(monitor.retention_days or 1)))
                    old_snapshot_ids = list(
                        (
                            await session.scalars(
                                select(MonitorSnapshot.id).where(
                                    MonitorSnapshot.monitor_id == monitor_id,
                                    MonitorSnapshot.created_at < cutoff,
                                )
                            )
                        ).all()
                    )
                    if old_snapshot_ids:
                        await session.execute(
                            delete(MonitorSnapshotRecord).where(
                                MonitorSnapshotRecord.snapshot_id.in_(old_snapshot_ids)
                            )
                        )
                        await session.execute(
                            delete(MonitorSnapshot).where(
                                MonitorSnapshot.id.in_(old_snapshot_ids)
                            )
                        )
                    await session.execute(
                        delete(MonitorEvent).where(
                            MonitorEvent.monitor_id == monitor_id,
                            MonitorEvent.detected_at < cutoff,
                        )
                    )
                    if monitor.status == MONITOR_STATUS_ARCHIVED:
                        await session.execute(
                            delete(MonitorURLState).where(
                                MonitorURLState.monitor_id == monitor_id
                            )
                        )
                    await session.commit()
                    purged_count += 1
                except Exception:
                    await session.rollback()
                    logger.exception(
                        "Monitor retention purge failed for monitor=%s", monitor_id
                    )
        logger.info("Monitor retention purge completed for %s monitor(s)", purged_count)
