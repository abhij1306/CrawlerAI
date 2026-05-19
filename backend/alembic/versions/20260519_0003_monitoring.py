"""add monitor tables

Revision ID: 20260519_0003
Revises: 20260518_0002
Create Date: 2026-05-19 00:03:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260519_0003"
down_revision = "20260518_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitor_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("domains", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("tracked_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schedule_interval_hours", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitor_jobs_user_id", "monitor_jobs", ["user_id"])
    op.create_index("ix_monitor_jobs_status", "monitor_jobs", ["status"])
    op.create_index("ix_monitor_jobs_priority", "monitor_jobs", ["priority"])
    op.create_index(
        "ix_monitor_jobs_status_priority_next_run",
        "monitor_jobs",
        ["status", "priority", "next_run_at"],
    )

    op.create_table(
        "monitor_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("field_name", sa.String(length=255), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_status", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitor_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["crawl_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitor_events_monitor_id", "monitor_events", ["monitor_id"])
    op.create_index("ix_monitor_events_run_id", "monitor_events", ["run_id"])
    op.create_index("ix_monitor_events_event_type", "monitor_events", ["event_type"])
    op.create_index("ix_monitor_events_field_name", "monitor_events", ["field_name"])
    op.create_index("ix_monitor_events_detected_at", "monitor_events", ["detected_at"])
    op.create_index(
        "ix_monitor_events_monitor_detected",
        "monitor_events",
        ["monitor_id", "detected_at"],
    )
    op.create_index(
        "ix_monitor_events_notification_status",
        "monitor_events",
        ["notification_status"],
    )

    op.create_table(
        "monitor_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("change_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitor_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitor_snapshots_monitor_id", "monitor_snapshots", ["monitor_id"])
    op.create_index("ix_monitor_snapshots_run_id", "monitor_snapshots", ["run_id"])
    op.create_index(
        "ix_monitor_snapshots_monitor_created",
        "monitor_snapshots",
        ["monitor_id", "created_at"],
    )

    op.create_table(
        "monitor_snapshot_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("url_identity_key", sa.String(length=255), nullable=False),
        sa.Column("field_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["monitor_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitor_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_monitor_snapshot_records_monitor_id",
        "monitor_snapshot_records",
        ["monitor_id"],
    )
    op.create_index(
        "ix_monitor_snapshot_records_url_identity_key",
        "monitor_snapshot_records",
        ["url_identity_key"],
    )
    op.create_index(
        "ix_monitor_snapshot_records_monitor_url",
        "monitor_snapshot_records",
        ["monitor_id", "source_url"],
    )
    op.create_index(
        "ix_monitor_snapshot_records_snapshot",
        "monitor_snapshot_records",
        ["snapshot_id"],
    )

    op.create_table(
        "monitor_url_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("last_etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("last_content_hash", sa.String(length=64), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_unchanged_count", sa.Integer(), nullable=False),
        sa.Column("auto_downgraded", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitor_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitor_url_states_monitor_id", "monitor_url_states", ["monitor_id"])
    op.create_index(
        "uq_monitor_url_states_monitor_url",
        "monitor_url_states",
        ["monitor_id", "url"],
        unique=True,
    )

    op.create_table(
        "in_app_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitor_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_in_app_notifications_user_id", "in_app_notifications", ["user_id"])
    op.create_index("ix_in_app_notifications_monitor_id", "in_app_notifications", ["monitor_id"])
    op.create_index("ix_in_app_notifications_read", "in_app_notifications", ["read"])
    op.create_index(
        "ix_in_app_notifications_user_read_created",
        "in_app_notifications",
        ["user_id", "read", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_in_app_notifications_user_read_created",
        table_name="in_app_notifications",
    )
    op.drop_index("ix_in_app_notifications_read", table_name="in_app_notifications")
    op.drop_index("ix_in_app_notifications_monitor_id", table_name="in_app_notifications")
    op.drop_index("ix_in_app_notifications_user_id", table_name="in_app_notifications")
    op.drop_table("in_app_notifications")
    op.drop_index("uq_monitor_url_states_monitor_url", table_name="monitor_url_states")
    op.drop_index("ix_monitor_url_states_monitor_id", table_name="monitor_url_states")
    op.drop_table("monitor_url_states")
    op.drop_index("ix_monitor_snapshot_records_snapshot", table_name="monitor_snapshot_records")
    op.drop_index("ix_monitor_snapshot_records_monitor_url", table_name="monitor_snapshot_records")
    op.drop_index("ix_monitor_snapshot_records_url_identity_key", table_name="monitor_snapshot_records")
    op.drop_index("ix_monitor_snapshot_records_monitor_id", table_name="monitor_snapshot_records")
    op.drop_table("monitor_snapshot_records")
    op.drop_index("ix_monitor_snapshots_monitor_created", table_name="monitor_snapshots")
    op.drop_index("ix_monitor_snapshots_run_id", table_name="monitor_snapshots")
    op.drop_index("ix_monitor_snapshots_monitor_id", table_name="monitor_snapshots")
    op.drop_table("monitor_snapshots")
    op.drop_index("ix_monitor_events_notification_status", table_name="monitor_events")
    op.drop_index("ix_monitor_events_monitor_detected", table_name="monitor_events")
    op.drop_index("ix_monitor_events_detected_at", table_name="monitor_events")
    op.drop_index("ix_monitor_events_field_name", table_name="monitor_events")
    op.drop_index("ix_monitor_events_event_type", table_name="monitor_events")
    op.drop_index("ix_monitor_events_run_id", table_name="monitor_events")
    op.drop_index("ix_monitor_events_monitor_id", table_name="monitor_events")
    op.drop_table("monitor_events")
    op.drop_index("ix_monitor_jobs_status_priority_next_run", table_name="monitor_jobs")
    op.drop_index("ix_monitor_jobs_priority", table_name="monitor_jobs")
    op.drop_index("ix_monitor_jobs_status", table_name="monitor_jobs")
    op.drop_index("ix_monitor_jobs_user_id", table_name="monitor_jobs")
    op.drop_table("monitor_jobs")
