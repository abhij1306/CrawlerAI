"""Add canonical per-URL results and record linkage.

Revision ID: 20260619_0002
Revises: 20260509_0001
Create Date: 2026-06-19 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0002"
down_revision: str | None = "20260509_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crawl_url_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("acquisition_outcome", sa.String(length=24), nullable=False, server_default="empty"),
        sa.Column("verdict", sa.String(length=24), nullable=False, server_default="empty"),
        sa.Column("extraction_version", sa.String(length=32), nullable=False, server_default="extraction.v1"),
        sa.Column("bundle_id", sa.String(length=128), nullable=True),
        sa.Column("manifest_uri", sa.Text(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_crawl_url_results_run_id", "crawl_url_results", ["run_id"])
    op.create_index("ix_crawl_url_results_verdict", "crawl_url_results", ["verdict"])
    op.create_index(
        "uq_crawl_url_results_identity",
        "crawl_url_results",
        ["run_id", "normalized_url", "surface", "generation"],
        unique=True,
    )
    op.add_column("crawl_records", sa.Column("url_result_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_crawl_records_url_result_id",
        "crawl_records",
        "crawl_url_results",
        ["url_result_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_crawl_records_url_result_id", "crawl_records", ["url_result_id"])


def downgrade() -> None:
    op.drop_index("ix_crawl_records_url_result_id", table_name="crawl_records")
    op.drop_constraint("fk_crawl_records_url_result_id", "crawl_records", type_="foreignkey")
    op.drop_column("crawl_records", "url_result_id")
    op.drop_index("uq_crawl_url_results_identity", table_name="crawl_url_results")
    op.drop_index("ix_crawl_url_results_verdict", table_name="crawl_url_results")
    op.drop_index("ix_crawl_url_results_run_id", table_name="crawl_url_results")
    op.drop_table("crawl_url_results")
