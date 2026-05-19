from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone

from app.services.monitor_retention import MonitorRetentionService
from app.services.monitor_scheduler_service import MonitorSchedulerService

logger = logging.getLogger(__name__)
SECONDS_PER_DAY = 86_400


class AsyncSchedulerLoop:
    def __init__(self, service: MonitorSchedulerService, interval_seconds: int):
        self._service = service
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._last_purge_at: datetime | None = None

    def start_nowait(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="monitor-scheduler-loop")
        logger.info("AsyncSchedulerLoop started (interval=%ss)", self._interval)

    async def start(self) -> None:
        self.start_nowait()

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("AsyncSchedulerLoop stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._service.check_due_jobs()
                await self._maybe_purge()
            except Exception:
                logger.exception("AsyncSchedulerLoop tick failed")
            finally:
                await asyncio.sleep(self._interval)

    async def _maybe_purge(self) -> None:
        now = datetime.now(timezone.utc)
        if (
            self._last_purge_at is None
            or (now - self._last_purge_at).total_seconds() >= SECONDS_PER_DAY
        ):
            await MonitorRetentionService().purge_expired()
            self._last_purge_at = now
