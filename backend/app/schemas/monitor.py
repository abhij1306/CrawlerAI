from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.config.monitor_settings import (
    MAX_RETENTION_DAYS,
    MAX_URLS_PER_MONITOR,
    MIN_SCHEDULE_INTERVAL_HOURS,
    MONITOR_EVENT_FIELD_CHANGED,
    MONITOR_EVENT_RECORD_NEW,
    MONITOR_EVENT_RECORD_REMOVED,
    MONITOR_PRIORITY_BACKGROUND,
    MONITOR_PRIORITY_ON_DEMAND,
    MONITOR_PRIORITY_PRIORITY,
    MONITOR_STATUS_ACTIVE,
    MONITOR_STATUS_ARCHIVED,
    MONITOR_STATUS_PAUSED,
)

MonitorPriority = Literal["on_demand", "priority", "background"]
MonitorStatus = Literal["active", "paused", "archived"]
MonitorEventType = Literal["field_changed", "record_new", "record_removed"]


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    urls: list[str] = Field(min_length=1, max_length=MAX_URLS_PER_MONITOR)
    surface: str = Field(min_length=1)
    tracked_fields: list[str] = Field(default_factory=lambda: ["price"])
    schedule_interval_hours: int = Field(ge=MIN_SCHEDULE_INTERVAL_HOURS)
    priority: MonitorPriority = MONITOR_PRIORITY_BACKGROUND
    retention_days: int = Field(default=30, ge=1, le=MAX_RETENTION_DAYS)
    requested_fields: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("urls")
    @classmethod
    def _validate_urls(cls, value: list[str]) -> list[str]:
        urls = [str(item or "").strip() for item in value if str(item or "").strip()]
        if not urls:
            raise ValueError("At least one URL is required")
        invalid = [url for url in urls if not url.startswith(("http://", "https://"))]
        if invalid:
            raise ValueError("All URLs must start with http:// or https://")
        return urls

    @field_validator("tracked_fields", "requested_fields")
    @classmethod
    def _clean_fields(cls, value: list[str]) -> list[str]:
        fields: list[str] = []
        seen: set[str] = set()
        for item in value:
            field = str(item or "").strip()
            if field and field not in seen:
                fields.append(field)
                seen.add(field)
        return fields

    @model_validator(mode="after")
    def _ensure_tracked_fields(self) -> MonitorCreate:
        if not self.tracked_fields:
            raise ValueError("tracked_fields must not be empty")
        requested = list(self.requested_fields)
        for field in self.tracked_fields:
            if field not in requested:
                requested.append(field)
        self.requested_fields = requested
        return self


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    tracked_fields: list[str] | None = None
    schedule_interval_hours: int | None = Field(default=None, ge=MIN_SCHEDULE_INTERVAL_HOURS)
    priority: MonitorPriority | None = None
    retention_days: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)
    status: MonitorStatus | None = None
    settings: dict[str, Any] | None = None

    @field_validator("tracked_fields")
    @classmethod
    def _clean_tracked_fields(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        fields: list[str] = []
        seen: set[str] = set()
        for item in value:
            field = str(item or "").strip()
            if field and field not in seen:
                fields.append(field)
                seen.add(field)
        if not fields:
            raise ValueError("tracked_fields must not be empty")
        return fields


class MonitorJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    urls: list[str]
    domains: list[str]
    surface: str
    tracked_fields: list[str]
    schedule_interval_hours: int
    priority: MonitorPriority
    retention_days: int
    status: MonitorStatus
    settings: dict[str, Any]
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    change_count: int = 0


class MonitorEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    run_id: int | None = None
    source_url: str
    event_type: MonitorEventType
    field_name: str | None = None
    old_value: Any = None
    new_value: Any = None
    detected_at: datetime
    notified_at: datetime | None = None
    notification_status: str


class MonitorSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    run_id: int
    snapshot_data: dict[str, Any]
    record_count: int
    change_count: int
    created_at: datetime


class MonitorSnapshotRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    snapshot_id: int
    monitor_id: int
    source_url: str
    url_identity_key: str
    field_values: dict[str, Any]
    created_at: datetime


class MonitorRunNowResponse(BaseModel):
    run_id: int
    dispatched_at: datetime
    url_count: int
    run_ids: list[int] = Field(default_factory=list)


MONITOR_STATUSES = {
    MONITOR_STATUS_ACTIVE,
    MONITOR_STATUS_PAUSED,
    MONITOR_STATUS_ARCHIVED,
}
MONITOR_PRIORITIES = {
    MONITOR_PRIORITY_ON_DEMAND,
    MONITOR_PRIORITY_PRIORITY,
    MONITOR_PRIORITY_BACKGROUND,
}
MONITOR_EVENT_TYPES = {
    MONITOR_EVENT_FIELD_CHANGED,
    MONITOR_EVENT_RECORD_NEW,
    MONITOR_EVENT_RECORD_REMOVED,
}
