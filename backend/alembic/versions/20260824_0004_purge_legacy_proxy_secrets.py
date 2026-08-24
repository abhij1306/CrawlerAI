"""Purge legacy plaintext proxy configuration from run settings.

Revision ID: 20260824_0004
Revises: 20260824_0003

Legacy JSON settings may contain proxy URL userinfo. Ownership of those
credentials cannot be reconstructed into the new encrypted reference shape,
so proxy configuration is removed rather than copied forward.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260824_0004"
down_revision: str | None = "20260824_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ["revision", "down_revision", "branch_labels", "depends_on"]


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE crawl_runs
            SET settings = (settings
                - 'proxy'
                - 'proxies'
                - 'proxy_list'
                - 'proxy_profile'
                - 'proxy_secret_refs'
                - 'proxy_username'
                - 'proxy_password')
                || '{"proxy_enabled": false}'::jsonb
            WHERE settings ?| ARRAY[
                'proxy', 'proxies', 'proxy_list', 'proxy_profile',
                'proxy_secret_refs', 'proxy_username', 'proxy_password'
            ]
            """
        )
    )


def downgrade() -> None:
    # Purged credentials are deliberately unrecoverable.
    pass
