from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_auth import hash_api_key
from app.models.api_key import ApiKey
from app.services.config.public_api import (
    PUBLIC_API_KEY_BYTES,
    PUBLIC_API_KEY_PREFIX,
    PUBLIC_API_KEY_PREFIX_DISPLAY_LENGTH,
)


def generate_api_key() -> str:
    return f"{PUBLIC_API_KEY_PREFIX}{secrets.token_urlsafe(PUBLIC_API_KEY_BYTES)}"


async def create_api_key(
    session: AsyncSession,
    *,
    user_id: int,
    name: str,
) -> tuple[ApiKey, str]:
    raw_key = generate_api_key()
    cleaned_name = str(name or "").strip()
    if not cleaned_name:
        raise ValueError("API key name must not be empty")
    row = ApiKey(
        user_id=user_id,
        name=cleaned_name,
        key_prefix=raw_key[:PUBLIC_API_KEY_PREFIX_DISPLAY_LENGTH],
        key_hash=hash_api_key(raw_key),
        is_active=True,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row, raw_key


async def list_api_keys(session: AsyncSession, *, user_id: int) -> list[ApiKey]:
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(
    session: AsyncSession,
    *,
    user_id: int,
    key_id: int,
) -> ApiKey:
    row = await session.get(ApiKey, key_id)
    if row is None or row.user_id != user_id:
        raise LookupError("API key not found")
    row.is_active = False
    row.last_used_at = row.last_used_at or datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return row
