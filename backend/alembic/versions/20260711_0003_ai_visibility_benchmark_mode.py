"""Add explicit AI-visibility benchmark mode.

Revision ID: 20260711_0003
Revises: 20260711_0002
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260711_0003"
down_revision: str | None = "20260711_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "revision"]


def upgrade() -> None:
    op.add_column(
        "ai_visibility_projects",
        sa.Column(
            "benchmark_mode",
            sa.String(length=32),
            nullable=False,
            server_default="controlled_localized",
        ),
    )
    op.alter_column("ai_visibility_projects", "benchmark_mode", server_default=None)


def downgrade() -> None:
    op.drop_column("ai_visibility_projects", "benchmark_mode")
