"""add page audit jobs and results

Revision ID: 20260605_0009
Revises: 20260528_0008
Create Date: 2026-06-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260605_0009"
down_revision: str | None = "20260528_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = [
    "revision",
    "down_revision",
    "branch_labels",
    "depends_on",
    "upgrade",
    "downgrade",
]


def upgrade() -> None:
    op.create_table(
        "page_audit_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("context", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_page_audit_jobs_user_id", "page_audit_jobs", ["user_id"])
    op.create_index("ix_page_audit_jobs_status", "page_audit_jobs", ["status"])
    op.create_table(
        "page_audit_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "report_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("markdown_report", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["page_audit_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_page_audit_results_job_id",
        "page_audit_results",
        ["job_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_page_audit_results_job_id", table_name="page_audit_results")
    op.drop_table("page_audit_results")
    op.drop_index("ix_page_audit_jobs_status", table_name="page_audit_jobs")
    op.drop_index("ix_page_audit_jobs_user_id", table_name="page_audit_jobs")
    op.drop_table("page_audit_jobs")
