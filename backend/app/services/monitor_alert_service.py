from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitor import MonitorEvent, MonitorJob
from app.models.notification import InAppNotification
from app.services.config.monitor_settings import (
    MONITOR_EVENT_FIELD_CHANGED,
    MONITOR_NOTIFICATION_MESSAGE_TEMPLATE,
    NOTIFICATION_STATUS_SENT,
    NOTIFICATION_STATUS_SKIPPED,
)
from app.services.monitor_service import utcnow


async def create_monitor_change_notification(
    session: AsyncSession,
    *,
    monitor: MonitorJob,
    events: Sequence[MonitorEvent],
) -> InAppNotification | None:
    changed_events = [
        event for event in events if event.event_type == MONITOR_EVENT_FIELD_CHANGED
    ]
    if not changed_events:
        return None
    now = utcnow()
    if monitor.user_id is None:
        for event in changed_events:
            event.notification_status = NOTIFICATION_STATUS_SKIPPED
            event.notified_at = now
        return None
    notification = InAppNotification(
        user_id=monitor.user_id,
        monitor_id=monitor.id,
        event_count=len(changed_events),
        message=MONITOR_NOTIFICATION_MESSAGE_TEMPLATE.format(
            monitor_name=monitor.name,
            event_count=len(changed_events),
        ),
    )
    session.add(notification)
    for event in changed_events:
        event.notification_status = NOTIFICATION_STATUS_SENT
        event.notified_at = now
    return notification


async def list_unread_notifications(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int,
) -> list[InAppNotification]:
    rows = await session.scalars(
        select(InAppNotification)
        .where(
            InAppNotification.user_id == user_id,
            InAppNotification.read.is_(False),
        )
        .order_by(InAppNotification.created_at.desc(), InAppNotification.id.desc())
        .limit(limit)
    )
    return list(rows.all())


async def unread_notification_count(session: AsyncSession, *, user_id: int) -> int:
    return int(
        (
            await session.scalar(
                select(func.count())
                .select_from(InAppNotification)
                .where(
                    InAppNotification.user_id == user_id,
                    InAppNotification.read.is_(False),
                )
            )
        )
        or 0
    )


async def mark_notification_read(
    session: AsyncSession,
    *,
    user_id: int,
    notification_id: int,
) -> InAppNotification:
    notification = await session.get(InAppNotification, notification_id)
    if notification is None or notification.user_id != user_id:
        raise LookupError("Notification not found")
    if not notification.read:
        notification.read = True
        notification.read_at = utcnow()
        await session.commit()
        await session.refresh(notification)
    return notification


async def mark_monitor_notifications_read(
    session: AsyncSession,
    *,
    user_id: int,
    monitor_id: int,
) -> int:
    result = await session.execute(
        update(InAppNotification)
        .where(
            InAppNotification.user_id == user_id,
            InAppNotification.monitor_id == monitor_id,
            InAppNotification.read.is_(False),
        )
        .values(read=True, read_at=utcnow())
    )
    await session.commit()
    return int(result.rowcount or 0)
