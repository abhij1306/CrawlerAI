"""AI Visibility (Gemini grounded search) MVP tables.

Adds ai_visibility_projects, ai_visibility_runs, ai_visibility_executions.

Revision ID: 20260711_0002
Revises: 20260703_0001
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_0002"
down_revision: str | None = "20260703_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "revision"]

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "ai_visibility_projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("brand_name", sa.String(length=255), nullable=False),
        sa.Column("brand_aliases", _JSONB, nullable=False),
        sa.Column("owned_domains", _JSONB, nullable=False),
        sa.Column("unintended_domains", _JSONB, nullable=False),
        sa.Column("competitors", _JSONB, nullable=False),
        sa.Column("country_code", sa.String(length=8), nullable=False),
        sa.Column("language_code", sa.String(length=16), nullable=False),
        sa.Column("prompts", _JSONB, nullable=False),
        sa.Column("default_repetitions", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_visibility_projects_user_id"),
        "ai_visibility_projects",
        ["user_id"],
    )

    op.create_table(
        "ai_visibility_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("random_seed", sa.String(length=64), nullable=False),
        sa.Column("system_instruction", sa.Text(), nullable=False),
        sa.Column("configuration", _JSONB, nullable=False),
        sa.Column("summary", _JSONB, nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["ai_visibility_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_visibility_runs_project_id"), "ai_visibility_runs", ["project_id"]
    )
    op.create_index(
        op.f("ix_ai_visibility_runs_status"), "ai_visibility_runs", ["status"]
    )
    op.create_index(
        op.f("ix_ai_visibility_runs_user_id"), "ai_visibility_runs", ["user_id"]
    )

    op.create_table(
        "ai_visibility_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("prompt_index", sa.Integer(), nullable=False),
        sa.Column("prompt_text_snapshot", sa.Text(), nullable=False),
        sa.Column("prompt_theme_snapshot", sa.String(length=128), nullable=False),
        sa.Column("prompt_intent_snapshot", sa.String(length=64), nullable=False),
        sa.Column("repetition", sa.Integer(), nullable=False),
        sa.Column("randomized_position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("search_used", sa.Boolean(), nullable=False),
        sa.Column("search_events", _JSONB, nullable=False),
        sa.Column("citations", _JSONB, nullable=False),
        sa.Column("score", _JSONB, nullable=False),
        sa.Column("request_snapshot", _JSONB, nullable=False),
        sa.Column("provider_metadata", _JSONB, nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["ai_visibility_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "prompt_index",
            "repetition",
            name="uq_ai_visibility_execution_slot",
        ),
    )
    op.create_index(
        op.f("ix_ai_visibility_executions_run_id"),
        "ai_visibility_executions",
        ["run_id"],
    )
    op.create_index(
        op.f("ix_ai_visibility_executions_prompt_index"),
        "ai_visibility_executions",
        ["prompt_index"],
    )
    op.create_index(
        op.f("ix_ai_visibility_executions_randomized_position"),
        "ai_visibility_executions",
        ["randomized_position"],
    )
    op.create_index(
        op.f("ix_ai_visibility_executions_status"),
        "ai_visibility_executions",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("ai_visibility_executions")
    op.drop_table("ai_visibility_runs")
    op.drop_table("ai_visibility_projects")
