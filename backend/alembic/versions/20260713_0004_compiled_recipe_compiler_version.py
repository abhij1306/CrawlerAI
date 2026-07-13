"""Scope compiled-recipe cache identity to compiler version.

Revision ID: 20260713_0004
Revises: 20260711_0003
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260713_0004"
down_revision: str | None = "20260711_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "revision"]


def upgrade() -> None:
    op.drop_index(
        "uq_compiled_extraction_recipes_checksum",
        table_name="compiled_extraction_recipes",
    )
    op.create_index(
        "uq_compiled_extraction_recipes_checksum",
        "compiled_extraction_recipes",
        ["recipe_id", "checksum", "compiler_version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_compiled_extraction_recipes_checksum",
        table_name="compiled_extraction_recipes",
    )
    op.create_index(
        "uq_compiled_extraction_recipes_checksum",
        "compiled_extraction_recipes",
        ["recipe_id", "checksum"],
        unique=True,
    )
