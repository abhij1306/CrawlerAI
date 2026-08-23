from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from cryptography.hazmat.primitives import hashes, hmac
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.models.api_key import ApiKey
from app.models.user import User
from app.core.config.public_api import (
    PUBLIC_API_ERROR_API_KEY_REQUIRED,
    PUBLIC_API_ERROR_AUTH_UNAVAILABLE,
    PUBLIC_API_ERROR_INVALID_API_KEY,
    PUBLIC_API_LAST_USED_TOUCH_SECONDS,
    PUBLIC_API_PRINCIPAL_CACHE_MAX_ENTRIES,
    PUBLIC_API_PRINCIPAL_CACHE_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

# Test seam: monkeypatched by cache TTL/throttle tests.
_monotonic = time.monotonic


@dataclass(frozen=True)
class PublicApiPrincipal:
    api_key_id: int
    user_id: int


@dataclass
class _CachedPrincipal:
    principal: PublicApiPrincipal
    expires_at: float
    last_touch_at: float


# 2.12: validated principals cached per process (bounded, oldest-entry
# eviction). Revocation/disable staleness is bounded by the cache TTL.
_PRINCIPAL_CACHE: dict[str, _CachedPrincipal] = {}
_PRINCIPAL_CACHE_LOCK = asyncio.Lock()


def hash_api_key(value: str) -> str:
    digest = hmac.HMAC(settings.jwt_secret_key.encode("utf-8"), hashes.SHA256())
    digest.update(value.encode("utf-8"))
    return digest.finalize().hex()


async def _principal_cache_entry(key_hash: str) -> _CachedPrincipal | None:
    async with _PRINCIPAL_CACHE_LOCK:
        return _PRINCIPAL_CACHE.get(key_hash)


async def _cache_principal(key_hash: str, entry: _CachedPrincipal) -> None:
    async with _PRINCIPAL_CACHE_LOCK:
        _PRINCIPAL_CACHE.pop(key_hash, None)
        while len(_PRINCIPAL_CACHE) >= PUBLIC_API_PRINCIPAL_CACHE_MAX_ENTRIES:
            _PRINCIPAL_CACHE.pop(next(iter(_PRINCIPAL_CACHE)))
        _PRINCIPAL_CACHE[key_hash] = entry


async def _touch_last_used_best_effort(
    session: AsyncSession, principal: PublicApiPrincipal
) -> None:
    try:
        await session.execute(
            update(ApiKey)
            .where(ApiKey.id == principal.api_key_id)
            .values(last_used_at=datetime.now(UTC))
        )
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        logger.exception(
            "Failed to update last_used_at for api_key.id=%s (best-effort)",
            principal.api_key_id,
        )


async def authenticate_public_api_key(
    session: AsyncSession,
    authorization: str | None,
    *,
    touch: bool = True,
) -> PublicApiPrincipal:
    scheme, _, credentials = str(authorization or "").partition(" ")
    if any((scheme.lower() != "bearer", not credentials.strip())):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": PUBLIC_API_ERROR_API_KEY_REQUIRED,
                "message": "API key required",
            },
        )
    raw_key = credentials.strip()
    key_hash = hash_api_key(raw_key)
    now = _monotonic()
    entry = await _principal_cache_entry(key_hash)
    # The touch stamp carries across cache refreshes: last_used_at is written
    # at most once per throttle window per key, while the shorter entry TTL
    # still bounds revocation staleness.
    last_touch_at = entry.last_touch_at if entry is not None else float("-inf")
    if entry is not None and entry.expires_at > now:
        if touch and now - entry.last_touch_at >= PUBLIC_API_LAST_USED_TOUCH_SECONDS:
            # Stamp before the attempt so a sick database is retried at most
            # once per throttle window instead of on every request.
            entry.last_touch_at = now
            await _touch_last_used_best_effort(session, entry.principal)
        return entry.principal
    api_key = await session.scalar(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.is_active.is_(True),
        )
    )
    if api_key is None or api_key.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": PUBLIC_API_ERROR_INVALID_API_KEY,
                "message": "Invalid API key",
            },
        )
    user = await session.get(User, int(api_key.user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": PUBLIC_API_ERROR_INVALID_API_KEY,
                "message": "Inactive API user",
            },
        )
    if touch and now - last_touch_at >= PUBLIC_API_LAST_USED_TOUCH_SECONDS:
        api_key.last_used_at = datetime.now(UTC)
        try:
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            logger.exception(
                "Failed to update last_used_at for api_key.id=%s",
                api_key.id,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": PUBLIC_API_ERROR_AUTH_UNAVAILABLE,
                    "message": "API key authentication unavailable",
                },
            ) from None
        last_touch_at = now
    principal = PublicApiPrincipal(api_key_id=int(api_key.id), user_id=int(user.id))
    await _cache_principal(
        key_hash,
        _CachedPrincipal(
            principal=principal,
            expires_at=now + PUBLIC_API_PRINCIPAL_CACHE_TTL_SECONDS,
            last_touch_at=last_touch_at,
        ),
    )
    return principal


async def get_public_api_user(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> User:
    user_id = getattr(request.state, "public_api_user_id", None)
    if user_id is None:
        principal = await authenticate_public_api_key(
            session, authorization, touch=True
        )
        user_id = principal.user_id
        request.state.public_api_key_id = principal.api_key_id
        request.state.public_api_user_id = principal.user_id
    user = await session.get(User, int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": PUBLIC_API_ERROR_INVALID_API_KEY,
                "message": "Inactive API user",
            },
        )
    return user
