from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.monitor import MonitorJob, MonitorURLState
from app.services.config.monitor_settings import (
    HEAD_CHECK_TIMEOUT_SECONDS,
    MAX_HASH_BYTES,
    MAX_CONCURRENT_MONITOR_DISPATCHES_PER_TICK,
    MONITOR_ID_SETTING_KEY,
    MONITOR_PRIORITY_ON_DEMAND,
    MONITOR_STATUS_ACTIVE,
    MONITOR_STATUS_ARCHIVED,
    MONITOR_RUN_TYPE_BATCH,
    MONITOR_RUN_TYPE_CRAWL,
    SKIP_HEAD_CHECK_KEY,
)
from app.services.crawl.ingestion_service import create_crawl_run_from_payload
from app.services.crawl.service import dispatch_run
from app.services.domain_utils import normalize_domain
from app.services.monitor_service import PRIORITY_ORDER, next_run_time, utcnow

logger = logging.getLogger(__name__)


class MonitorSchedulerService:
    async def check_due_jobs(self) -> None:
        async with SessionLocal() as session:
            now = utcnow()
            due_monitors = await self._due_monitors(session, now)
            dispatched_regular = 0
            for monitor in due_monitors:
                if (
                    monitor.priority != MONITOR_PRIORITY_ON_DEMAND
                    and dispatched_regular >= MAX_CONCURRENT_MONITOR_DISPATCHES_PER_TICK
                ):
                    continue
                changed_urls = await self._changed_urls_for_monitor(session, monitor)
                if changed_urls:
                    await self.dispatch_monitor_run(session, monitor, changed_urls)
                    if monitor.priority != MONITOR_PRIORITY_ON_DEMAND:
                        dispatched_regular += 1
                monitor.last_run_at = now
                monitor.next_run_at = next_run_time(now, monitor.schedule_interval_hours)
                await session.commit()

    async def pre_check_url(self, url: str, state: MonitorURLState) -> bool:
        now = utcnow()
        try:
            async with httpx.AsyncClient(timeout=HEAD_CHECK_TIMEOUT_SECONDS, follow_redirects=True) as client:
                response = await client.head(url)
                if response.status_code == 405:
                    response = await client.get(url)
                response.raise_for_status()
                etag = response.headers.get("etag")
                last_modified = response.headers.get("last-modified")
                content_hash = None
                if not etag and not last_modified:
                    content_hash = await _stream_content_hash(client, url)
        except Exception:
            state.last_checked_at = now
            return True

        had_prior_state = bool(state.last_etag or state.last_modified or state.last_content_hash)
        changed = not had_prior_state
        if etag:
            changed = state.last_etag != etag if had_prior_state else True
        elif last_modified:
            changed = state.last_modified != last_modified if had_prior_state else True
        elif content_hash:
            changed = state.last_content_hash != content_hash if had_prior_state else True
        else:
            changed = True

        state.last_etag = etag
        state.last_modified = last_modified
        if content_hash is not None:
            state.last_content_hash = content_hash
        state.last_checked_at = now
        if changed:
            state.last_changed_at = now
            state.consecutive_unchanged_count = 0
        else:
            state.consecutive_unchanged_count = int(state.consecutive_unchanged_count or 0) + 1
        return changed

    async def dispatch_monitor_run(
        self,
        session: AsyncSession,
        monitor: MonitorJob,
        urls: list[str],
    ) -> list[int]:
        if monitor.status == MONITOR_STATUS_ARCHIVED:
            raise ValueError("Archived monitor cannot run")
        if monitor.user_id is None:
            raise ValueError(f"Monitor {monitor.id} has no user_id")
        user_id = int(monitor.user_id)
        run_ids: list[int] = []
        for domain_urls in _urls_by_domain(urls).values():
            settings = dict(monitor.settings or {})
            settings[MONITOR_ID_SETTING_KEY] = monitor.id
            payload = {
                "run_type": MONITOR_RUN_TYPE_BATCH if len(domain_urls) > 1 else MONITOR_RUN_TYPE_CRAWL,
                "url": domain_urls[0],
                "urls": domain_urls,
                "surface": monitor.surface,
                "settings": settings,
                "requested_fields": list(monitor.requested_fields or []),
            }
            run = await create_crawl_run_from_payload(
                session,
                user_id,
                payload,
            )
            await dispatch_run(session, run)
            run_ids.append(int(run.id))
        return run_ids

    async def _due_monitors(
        self,
        session: AsyncSession,
        now: datetime,
    ) -> list[MonitorJob]:
        monitors = list(
            (
                await session.scalars(
                    select(MonitorJob).where(
                        MonitorJob.status == MONITOR_STATUS_ACTIVE,
                        MonitorJob.next_run_at <= now,
                    )
                )
            ).all()
        )
        return sorted(
            monitors,
            key=lambda monitor: (
                PRIORITY_ORDER.get(str(monitor.priority), 99),
                monitor.next_run_at or datetime.max.replace(tzinfo=UTC),
                monitor.id,
            ),
        )

    async def _changed_urls_for_monitor(
        self,
        session: AsyncSession,
        monitor: MonitorJob,
    ) -> list[str]:
        settings = monitor.settings if isinstance(monitor.settings, dict) else {}
        skip_head = bool(settings.get(SKIP_HEAD_CHECK_KEY, False))
        if skip_head:
            return list(monitor.urls or [])
        state_rows = {
            row.url: row
            for row in (
                await session.scalars(
                    select(MonitorURLState).where(MonitorURLState.monitor_id == monitor.id)
                )
            ).all()
        }
        changed_urls: list[str] = []
        for url in monitor.urls or []:
            state = state_rows.get(url)
            if state is None:
                state = MonitorURLState(monitor_id=monitor.id, url=url)
                session.add(state)
                await session.flush()
            if await self.pre_check_url(url, state):
                changed_urls.append(url)
        await session.commit()
        return changed_urls


def _urls_by_domain(urls: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        grouped[normalize_domain(url)].append(url)
    return dict(grouped)


async def _stream_content_hash(client: httpx.AsyncClient, url: str) -> str | None:
    digest = hashlib.sha256()
    total = 0
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > MAX_HASH_BYTES:
            return None
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_HASH_BYTES:
                return None
            digest.update(chunk)
    return digest.hexdigest()
