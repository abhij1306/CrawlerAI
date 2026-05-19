from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.notification import (
    InAppNotificationResponse,
    NotificationUnreadCountResponse,
)
from app.services.monitor_alert_service import (
    list_unread_notifications,
    mark_monitor_notifications_read,
    mark_notification_read,
    unread_notification_count,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def notifications_list(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> list[InAppNotificationResponse]:
    rows = await list_unread_notifications(session, user_id=user.id, limit=limit)
    return [
        InAppNotificationResponse.model_validate(row, from_attributes=True)
        for row in rows
    ]


@router.get("/unread-count")
async def notifications_unread_count(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> NotificationUnreadCountResponse:
    return NotificationUnreadCountResponse(
        count=await unread_notification_count(session, user_id=user.id)
    )


@router.post("/monitors/{monitor_id}/read")
async def monitor_notifications_mark_read(
    monitor_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, int]:
    return {
        "updated": await mark_monitor_notifications_read(
            session,
            user_id=user.id,
            monitor_id=monitor_id,
        )
    }


@router.post("/{notification_id}/read")
async def notification_mark_read(
    notification_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> InAppNotificationResponse:
    try:
        notification = await mark_notification_read(
            session,
            user_id=user.id,
            notification_id=notification_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return InAppNotificationResponse.model_validate(notification, from_attributes=True)
