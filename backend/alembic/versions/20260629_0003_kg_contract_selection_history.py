"""Add Knowledge Graph contract selection history.

Revision ID: 20260629_0003
Revises: 20260629_0002
Create Date: 2026-06-29 00:03:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260629_0003"
down_revision: str | None = "20260629_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "revision"]


def upgrade() -> None:
    op.execute(
        "ALTER TABLE kg_extraction_contracts "
        "ADD COLUMN selection_history JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.drop_column("kg_extraction_contracts", "selection_history")
