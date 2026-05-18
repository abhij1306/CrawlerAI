"""add ucp audit tables

Revision ID: 20260518_0002
Revises: 20260509_0001
Create Date: 2026-05-18 00:02:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260518_0002"
down_revision = "20260509_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ucp_audit_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ucp_audit_jobs_user_id", "ucp_audit_jobs", ["user_id"])
    op.create_index("ix_ucp_audit_jobs_domain", "ucp_audit_jobs", ["domain"])
    op.create_index("ix_ucp_audit_jobs_status", "ucp_audit_jobs", ["status"])

    op.create_table(
        "ucp_audit_page_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("acquisition_mode", sa.String(length=32), nullable=False),
        sa.Column("dimension_payloads", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["ucp_audit_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "url", name="uq_ucp_audit_page_results_job_url"),
    )
    op.create_index("ix_ucp_audit_page_results_job_id", "ucp_audit_page_results", ["job_id"])

    op.create_table(
        "ucp_audit_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("dimension_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("markdown_report", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["ucp_audit_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_ucp_audit_reports_job_id", "ucp_audit_reports", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_ucp_audit_reports_job_id", table_name="ucp_audit_reports")
    op.drop_table("ucp_audit_reports")
    op.drop_index("ix_ucp_audit_page_results_job_id", table_name="ucp_audit_page_results")
    op.drop_table("ucp_audit_page_results")
    op.drop_index("ix_ucp_audit_jobs_status", table_name="ucp_audit_jobs")
    op.drop_index("ix_ucp_audit_jobs_domain", table_name="ucp_audit_jobs")
    op.drop_index("ix_ucp_audit_jobs_user_id", table_name="ucp_audit_jobs")
    op.drop_table("ucp_audit_jobs")
