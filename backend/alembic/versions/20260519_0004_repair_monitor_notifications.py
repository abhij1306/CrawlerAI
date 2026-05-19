"""repair monitor notification tables

Revision ID: 20260519_0004
Revises: 20260519_0003
Create Date: 2026-05-19 00:04:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260519_0004"
down_revision = "20260519_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("in_app_notifications"):
        op.create_table(
            "in_app_notifications",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("monitor_id", sa.Integer(), nullable=False),
            sa.Column("event_count", sa.Integer(), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("read", sa.Boolean(), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["monitor_id"],
                ["monitor_jobs.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_in_app_notifications_user_id "
        "ON in_app_notifications (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_in_app_notifications_monitor_id "
        "ON in_app_notifications (monitor_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_in_app_notifications_read "
        "ON in_app_notifications (read)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_in_app_notifications_user_read_created "
        "ON in_app_notifications (user_id, read, created_at)"
    )
    op.execute("DROP INDEX IF EXISTS ix_monitor_snapshot_records_snapshot_id")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_in_app_notifications_user_read_created")
    op.execute("DROP INDEX IF EXISTS ix_in_app_notifications_read")
    op.execute("DROP INDEX IF EXISTS ix_in_app_notifications_monitor_id")
    op.execute("DROP INDEX IF EXISTS ix_in_app_notifications_user_id")
    op.execute("DROP TABLE IF EXISTS in_app_notifications")
