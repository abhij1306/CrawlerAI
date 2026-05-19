from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitor import (
    MonitorEvent,
    MonitorJob,
    MonitorSnapshot,
    MonitorSnapshotRecord,
    MonitorURLState,
)
from app.models.user import User
from app.services.config.domain_profiles import (
    INVALID_SURFACE_VALUES,
    SURFACE_VALIDATION_ERROR,
)
from app.services.config.monitor_settings import (
    ECOMMERCE_SURFACES,
    MAX_RETENTION_DAYS,
    MIN_SCHEDULE_INTERVAL_HOURS,
    MONITOR_PRIORITY_BACKGROUND,
    MONITOR_PRIORITY_ON_DEMAND,
    MONITOR_PRIORITY_PRIORITY,
    MONITOR_STATUS_ACTIVE,
    MONITOR_STATUS_ARCHIVED,
    MONITOR_STATUS_PAUSED,
    SKIP_HEAD_CHECK_KEY,
)
from app.services.crawl.utils import normalize_target_url
from app.services.domain_utils import normalize_domain
from app.services.field_policy import preserve_requested_fields
from app.services.url_safety import ensure_public_crawl_targets

PRIORITY_ORDER = {
    MONITOR_PRIORITY_ON_DEMAND: 0,
    MONITOR_PRIORITY_PRIORITY: 1,
    MONITOR_PRIORITY_BACKGROUND: 2,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def next_run_time(now: datetime, interval_hours: int) -> datetime:
    return now + timedelta(hours=max(MIN_SCHEDULE_INTERVAL_HOURS, int(interval_hours)))


def monitor_domains(urls: list[str]) -> list[str]:
    domains: list[str] = []
    seen: set[str] = set()
    for url in urls:
        domain = normalize_domain(url)
        if domain and domain not in seen:
            domains.append(domain)
            seen.add(domain)
    return domains


async def create_monitor(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, object],
) -> MonitorJob:
    urls = _normalized_urls(payload.get("urls"))
    await ensure_public_crawl_targets(urls)
    surface = _normalized_surface(payload.get("surface"))
    tracked_fields = _field_list(payload.get("tracked_fields")) or ["price"]
    requested_fields = preserve_requested_fields(
        [*_field_list(payload.get("requested_fields")), *tracked_fields]
    )
    interval = _bounded_interval(payload.get("schedule_interval_hours"))
    now = utcnow()
    monitor = MonitorJob(
        user_id=user.id,
        name=str(payload.get("name") or "").strip(),
        urls=urls,
        domains=monitor_domains(urls),
        surface=surface,
        tracked_fields=tracked_fields,
        schedule_interval_hours=interval,
        priority=_priority(payload.get("priority")),
        retention_days=_retention_days(payload.get("retention_days")),
        settings=_monitor_settings(payload.get("settings"), surface),
        requested_fields=requested_fields,
        status=MONITOR_STATUS_ACTIVE,
        last_run_at=None,
        next_run_at=next_run_time(now, interval),
    )
    session.add(monitor)
    await session.flush()
    for url in urls:
        session.add(MonitorURLState(monitor_id=monitor.id, url=url))
    await session.commit()
    await session.refresh(monitor)
    return monitor


async def list_monitors(
    session: AsyncSession,
    *,
    status: str | None = None,
    priority: str | None = None,
) -> list[MonitorJob]:
    statement = select(MonitorJob)
    if status:
        statement = statement.where(MonitorJob.status == status)
    if priority:
        statement = statement.where(MonitorJob.priority == priority)
    result = await session.scalars(statement.order_by(MonitorJob.updated_at.desc()))
    return list(result.all())


async def get_monitor(session: AsyncSession, monitor_id: int) -> MonitorJob:
    monitor = await session.get(MonitorJob, monitor_id)
    if monitor is None:
        raise LookupError("Monitor not found")
    return monitor


async def update_monitor(
    session: AsyncSession,
    *,
    monitor_id: int,
    payload: dict[str, object],
) -> MonitorJob:
    monitor = await get_monitor(session, monitor_id)
    if payload.get("name") is not None:
        monitor.name = str(payload["name"]).strip()
    if payload.get("tracked_fields") is not None:
        monitor.tracked_fields = _field_list(payload.get("tracked_fields"))
        monitor.requested_fields = preserve_requested_fields(
            [*_field_list(monitor.requested_fields), *monitor.tracked_fields]
        )
    if payload.get("schedule_interval_hours") is not None:
        monitor.schedule_interval_hours = _bounded_interval(payload.get("schedule_interval_hours"))
        monitor.next_run_at = next_run_time(utcnow(), monitor.schedule_interval_hours)
    if payload.get("priority") is not None:
        monitor.priority = _priority(payload.get("priority"))
    if payload.get("retention_days") is not None:
        monitor.retention_days = _retention_days(payload.get("retention_days"))
    if payload.get("settings") is not None:
        monitor.settings = _monitor_settings(payload.get("settings"), monitor.surface)
    if payload.get("status") is not None:
        monitor.status = _status(payload.get("status"))
        if monitor.status == MONITOR_STATUS_ACTIVE and monitor.next_run_at is None:
            monitor.next_run_at = next_run_time(utcnow(), monitor.schedule_interval_hours)
    await session.commit()
    await session.refresh(monitor)
    return monitor


async def archive_monitor(session: AsyncSession, monitor_id: int) -> MonitorJob:
    monitor = await get_monitor(session, monitor_id)
    monitor.status = MONITOR_STATUS_ARCHIVED
    await session.commit()
    await session.refresh(monitor)
    return monitor


async def monitor_change_count_since(
    session: AsyncSession,
    *,
    monitor_id: int,
    since: datetime | None = None,
) -> int:
    statement = select(func.count()).select_from(MonitorEvent).where(
        MonitorEvent.monitor_id == monitor_id
    )
    if since is not None:
        statement = statement.where(MonitorEvent.detected_at > since)
    return int((await session.scalar(statement)) or 0)


async def batch_monitor_change_counts(
    session: AsyncSession,
    monitor_ids: list[int],
    since: datetime | None = None,
) -> dict[int, int]:
    if not monitor_ids:
        return {}
    statement = (
        select(MonitorEvent.monitor_id, func.count())
        .where(MonitorEvent.monitor_id.in_(monitor_ids))
        .group_by(MonitorEvent.monitor_id)
    )
    if since is not None:
        statement = statement.where(MonitorEvent.detected_at > since)
    rows = (await session.execute(statement)).all()
    return {int(monitor_id): int(count) for monitor_id, count in rows}


async def list_events(
    session: AsyncSession,
    *,
    monitor_id: int,
    page: int,
    limit: int,
    event_type: str | None = None,
    field_name: str | None = None,
) -> tuple[list[MonitorEvent], int]:
    page = max(1, page)
    statement = select(MonitorEvent).where(MonitorEvent.monitor_id == monitor_id)
    count = select(func.count()).select_from(MonitorEvent).where(MonitorEvent.monitor_id == monitor_id)
    if event_type:
        statement = statement.where(MonitorEvent.event_type == event_type)
        count = count.where(MonitorEvent.event_type == event_type)
    if field_name:
        statement = statement.where(MonitorEvent.field_name == field_name)
        count = count.where(MonitorEvent.field_name == field_name)
    total = int((await session.scalar(count)) or 0)
    rows = await session.scalars(
        statement.order_by(MonitorEvent.detected_at.desc(), MonitorEvent.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(rows.all()), total


async def list_snapshot_records(
    session: AsyncSession,
    *,
    monitor_id: int,
    limit: int,
) -> list[MonitorSnapshotRecord]:
    rows = await session.scalars(
        select(MonitorSnapshotRecord)
        .where(MonitorSnapshotRecord.monitor_id == monitor_id)
        .order_by(MonitorSnapshotRecord.created_at.asc(), MonitorSnapshotRecord.id.asc())
        .limit(limit)
    )
    return list(rows.all())


async def list_snapshots(
    session: AsyncSession,
    *,
    monitor_id: int,
    page: int,
    limit: int,
) -> tuple[list[MonitorSnapshot], int]:
    page = max(1, page)
    statement = select(MonitorSnapshot).where(MonitorSnapshot.monitor_id == monitor_id)
    total = int(
        (await session.scalar(select(func.count()).select_from(MonitorSnapshot).where(MonitorSnapshot.monitor_id == monitor_id)))
        or 0
    )
    rows = await session.scalars(
        statement.order_by(MonitorSnapshot.created_at.desc(), MonitorSnapshot.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(rows.all()), total


async def current_snapshot_records(
    session: AsyncSession,
    *,
    monitor_id: int,
) -> list[MonitorSnapshotRecord]:
    latest_snapshot_id = await session.scalar(
        select(MonitorSnapshot.id)
        .where(MonitorSnapshot.monitor_id == monitor_id)
        .order_by(MonitorSnapshot.created_at.desc(), MonitorSnapshot.id.desc())
        .limit(1)
    )
    if latest_snapshot_id is None:
        return []
    rows = await session.scalars(
        select(MonitorSnapshotRecord)
        .where(MonitorSnapshotRecord.snapshot_id == latest_snapshot_id)
        .order_by(MonitorSnapshotRecord.source_url.asc())
    )
    return list(rows.all())


def _normalized_urls(value: object) -> list[str]:
    raw_items = value if isinstance(value, list) else []
    urls: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        url = normalize_target_url(item)
        if not url or url in seen:
            continue
        scheme = urlsplit(url).scheme.lower()
        if scheme not in {"http", "https"}:
            raise ValueError("All URLs must start with http:// or https://")
        urls.append(url)
        seen.add(url)
    if not urls:
        raise ValueError("At least one URL is required")
    return urls


def _normalized_surface(value: object) -> str:
    surface = str(value or "").strip().lower()
    if not surface:
        raise ValueError("surface is required")
    if surface in INVALID_SURFACE_VALUES:
        raise ValueError(SURFACE_VALIDATION_ERROR)
    return surface


def _field_list(value: object) -> list[str]:
    raw_items = value if isinstance(value, list) else []
    fields: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        field = str(item or "").strip()
        if field and field not in seen:
            fields.append(field)
            seen.add(field)
    return fields


def _bounded_interval(value: object) -> int:
    parsed = _int_value(value, MIN_SCHEDULE_INTERVAL_HOURS)
    if parsed < MIN_SCHEDULE_INTERVAL_HOURS:
        raise ValueError("schedule_interval_hours is too small")
    return parsed


def _retention_days(value: object) -> int:
    parsed = _int_value(value, 30)
    if parsed < 1 or parsed > MAX_RETENTION_DAYS:
        raise ValueError("retention_days must be between 1 and 90")
    return parsed


def _priority(value: object) -> str:
    priority = str(value or MONITOR_PRIORITY_BACKGROUND).strip().lower()
    if priority not in {
        MONITOR_PRIORITY_ON_DEMAND,
        MONITOR_PRIORITY_PRIORITY,
        MONITOR_PRIORITY_BACKGROUND,
    }:
        raise ValueError("Invalid monitor priority")
    return priority


def _status(value: object) -> str:
    status = str(value or "").strip().lower()
    if status not in {
        MONITOR_STATUS_ACTIVE,
        MONITOR_STATUS_PAUSED,
        MONITOR_STATUS_ARCHIVED,
    }:
        raise ValueError("Invalid monitor status")
    return status


def _int_value(value: object, default: int) -> int:
    try:
        return int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        return default


def _monitor_settings(settings: object, surface: str) -> dict[str, object]:
    data = dict(settings or {}) if isinstance(settings, dict) else {}
    if surface in ECOMMERCE_SURFACES and SKIP_HEAD_CHECK_KEY not in data:
        data[SKIP_HEAD_CHECK_KEY] = True
    return data
