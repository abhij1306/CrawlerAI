"""Scope durable cookie memory to a user and discard unsafe legacy memory.

Revision ID: 20260824_0002
Revises: 20260703_0001

Legacy domain cookie rows have no trustworthy owner, and legacy run profiles
may contain globally learned state written by ordinary users. Both are deleted
rather than assigned or exposed to an arbitrary tenant.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260824_0002"
down_revision: str | None = "20260703_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ["revision", "down_revision", "branch_labels", "depends_on"]


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM domain_cookie_memory"))
    op.execute(sa.text("DELETE FROM domain_run_profiles"))
    op.drop_index("uq_domain_cookie_memory_domain", table_name="domain_cookie_memory")
    op.add_column(
        "domain_cookie_memory",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_domain_cookie_memory_user_id_users",
        "domain_cookie_memory",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_domain_cookie_memory_user_id"),
        "domain_cookie_memory",
        ["user_id"],
        unique=False,
    )
    op.alter_column("domain_cookie_memory", "user_id", nullable=False)
    op.create_index(
        "uq_domain_cookie_memory_user_domain",
        "domain_cookie_memory",
        ["user_id", "domain"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_domain_cookie_memory_user_domain",
        table_name="domain_cookie_memory",
    )
    op.drop_index(
        op.f("ix_domain_cookie_memory_user_id"),
        table_name="domain_cookie_memory",
    )
    op.drop_constraint(
        "fk_domain_cookie_memory_user_id_users",
        "domain_cookie_memory",
        type_="foreignkey",
    )
    op.execute(sa.text("DELETE FROM domain_cookie_memory"))
    op.drop_column("domain_cookie_memory", "user_id")
    op.create_index(
        "uq_domain_cookie_memory_domain",
        "domain_cookie_memory",
        ["domain"],
        unique=True,
    )
