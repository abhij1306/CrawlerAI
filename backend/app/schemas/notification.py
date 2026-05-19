from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InAppNotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    monitor_id: int
    event_count: int
    message: str
    read: bool
    read_at: datetime | None = None
    created_at: datetime


class NotificationUnreadCountResponse(BaseModel):
    count: int
