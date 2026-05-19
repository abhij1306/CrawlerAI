from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_run import (
    CASCADE,
    CRAWL_RUN_FK,
    CreatedAtMixin,
    SET_NULL,
    USERS_FK,
    UpdatedAtMixin,
)
from app.services.config.monitor_settings import (
    MONITOR_PRIORITY_BACKGROUND,
    MONITOR_STATUS_ACTIVE,
    NOTIFICATION_STATUS_PENDING,
)

MONITOR_JOB_FK = "monitor_jobs.id"


class MonitorJob(UpdatedAtMixin, Base):
    __tablename__ = "monitor_jobs"
    __table_args__ = (
        Index("ix_monitor_jobs_status_priority_next_run", "status", "priority", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey(USERS_FK, ondelete=SET_NULL), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    urls: Mapped[list] = mapped_column(JSONB, default=list)
    domains: Mapped[list] = mapped_column(JSONB, default=list)
    surface: Mapped[str] = mapped_column(String(40))
    tracked_fields: Mapped[list] = mapped_column(JSONB, default=list)
    schedule_interval_hours: Mapped[int] = mapped_column(Integer)
    priority: Mapped[str] = mapped_column(
        String(32), default=MONITOR_PRIORITY_BACKGROUND, index=True
    )
    retention_days: Mapped[int] = mapped_column(Integer)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    requested_fields: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(32), default=MONITOR_STATUS_ACTIVE, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MonitorEvent(Base):
    __tablename__ = "monitor_events"
    __table_args__ = (
        Index("ix_monitor_events_monitor_detected", "monitor_id", "detected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey(MONITOR_JOB_FK, ondelete=CASCADE), index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL), nullable=True, index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    field_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    old_value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_status: Mapped[str] = mapped_column(
        String(32), default=NOTIFICATION_STATUS_PENDING, index=True
    )


class MonitorSnapshot(CreatedAtMixin, Base):
    __tablename__ = "monitor_snapshots"
    __table_args__ = (
        Index("ix_monitor_snapshots_monitor_created", "monitor_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey(MONITOR_JOB_FK, ondelete=CASCADE), index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey(CRAWL_RUN_FK, ondelete=CASCADE), index=True)
    snapshot_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    change_count: Mapped[int] = mapped_column(Integer, default=0)


class MonitorSnapshotRecord(CreatedAtMixin, Base):
    __tablename__ = "monitor_snapshot_records"
    __table_args__ = (
        Index("ix_monitor_snapshot_records_monitor_url", "monitor_id", "source_url"),
        Index("ix_monitor_snapshot_records_snapshot", "snapshot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("monitor_snapshots.id", ondelete=CASCADE)
    )
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey(MONITOR_JOB_FK, ondelete=CASCADE), index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    url_identity_key: Mapped[str] = mapped_column(String(255), index=True)
    field_values: Mapped[dict] = mapped_column(JSONB, default=dict)


class MonitorURLState(CreatedAtMixin, Base):
    __tablename__ = "monitor_url_states"
    __table_args__ = (
        Index("uq_monitor_url_states_monitor_url", "monitor_id", "url", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey(MONITOR_JOB_FK, ondelete=CASCADE), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    last_etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consecutive_unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_downgraded: Mapped[bool] = mapped_column(Boolean, default=False)
