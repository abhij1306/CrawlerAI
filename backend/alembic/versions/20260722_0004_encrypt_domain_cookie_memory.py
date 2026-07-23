"""Encrypt domain cookie memory storage_state at rest.

Revision ID: 20260722_0004
Revises: 20260711_0003
Create Date: 2026-07-22

Audit 1.6: DomainCookieMemory.storage_state held plaintext session cookies in
JSONB. This data migration rewrites every plaintext row to the encryption
envelope {"v": 1, "ct": <fernet ciphertext>} used by the new application code.

Properties:
- Batched keyset pagination so large memories do not load into memory.
- Idempotent: rows already carrying the envelope ("ct" key) are skipped, so a
  re-run after failure only processes what is left.
- Requires ENCRYPTION_KEY (already mandatory for the app to boot).
- Deploy ordering: run AFTER workers run the new code; old workers skip
  encrypted rows and simply re-learn the domain state.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from app.core.config import settings
from app.core.config.cookie_settings import (
    STORAGE_STATE_ENVELOPE_CIPHERTEXT_KEY,
    STORAGE_STATE_ENVELOPE_VERSION,
    STORAGE_STATE_ENVELOPE_VERSION_KEY,
)
from app.core.security import decrypt_secret, encrypt_secret

revision: str = "20260722_0004"
down_revision: str | None = "20260711_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "revision"]

_BATCH_SIZE = 500


def _plaintext_rows(bind: sa.engine.Connection, last_id: int) -> list[dict]:
    return (
        bind.execute(
            sa.text(
                "SELECT id, storage_state FROM domain_cookie_memory "
                "WHERE id > :last_id AND NOT jsonb_exists(storage_state, 'ct') "
                "ORDER BY id LIMIT :batch_size"
            ),
            {"last_id": last_id, "batch_size": _BATCH_SIZE},
        )
        .mappings()
        .all()
    )


def _envelope_rows(bind: sa.engine.Connection, last_id: int) -> list[dict]:
    return (
        bind.execute(
            sa.text(
                "SELECT id, storage_state FROM domain_cookie_memory "
                "WHERE id > :last_id AND jsonb_exists(storage_state, 'ct') "
                "ORDER BY id LIMIT :batch_size"
            ),
            {"last_id": last_id, "batch_size": _BATCH_SIZE},
        )
        .mappings()
        .all()
    )


def _write_storage_state(
    bind: sa.engine.Connection, row_id: int, payload: dict
) -> None:
    bind.execute(
        sa.text(
            "UPDATE domain_cookie_memory "
            "SET storage_state = CAST(:payload AS jsonb) "
            "WHERE id = :row_id"
        ),
        {"payload": json.dumps(payload), "row_id": row_id},
    )


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "20260722_0004 is a data migration and cannot run in offline SQL mode"
        )
    if not str(settings.encryption_key or "").strip():
        raise RuntimeError(
            "ENCRYPTION_KEY is required to encrypt domain cookie memory at rest"
        )
    bind = op.get_bind()
    last_id = 0
    while True:
        rows = _plaintext_rows(bind, last_id)
        if not rows:
            break
        for row in rows:
            last_id = row["id"]
            envelope = {
                STORAGE_STATE_ENVELOPE_VERSION_KEY: STORAGE_STATE_ENVELOPE_VERSION,
                STORAGE_STATE_ENVELOPE_CIPHERTEXT_KEY: encrypt_secret(
                    json.dumps(row["storage_state"], separators=(",", ":"))
                ),
            }
            _write_storage_state(bind, row["id"], envelope)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "20260722_0004 is a data migration and cannot run in offline SQL mode"
        )
    bind = op.get_bind()
    last_id = 0
    while True:
        rows = _envelope_rows(bind, last_id)
        if not rows:
            break
        for row in rows:
            last_id = row["id"]
            storage_state = row["storage_state"]
            ciphertext = storage_state.get(STORAGE_STATE_ENVELOPE_CIPHERTEXT_KEY)
            if not isinstance(ciphertext, str):
                continue
            plaintext = json.loads(decrypt_secret(ciphertext))
            if isinstance(plaintext, dict):
                _write_storage_state(bind, row["id"], plaintext)
