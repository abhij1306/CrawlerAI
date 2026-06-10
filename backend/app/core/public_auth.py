from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from cryptography.hazmat.primitives import hashes, hmac
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.models.api_key import ApiKey
from app.models.user import User
from app.services.config.public_api import (
    PUBLIC_API_ERROR_API_KEY_REQUIRED,
    PUBLIC_API_ERROR_AUTH_UNAVAILABLE,
    PUBLIC_API_ERROR_INVALID_API_KEY,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublicApiPrincipal:
    api_key_id: int
    user_id: int


def hash_api_key(value: str) -> str:
    digest = hmac.HMAC(settings.jwt_secret_key.encode("utf-8"), hashes.SHA256())
    digest.update(value.encode("utf-8"))
    return digest.finalize().hex()


async def authenticate_public_api_key(
    session: AsyncSession,
    authorization: str | None,
    *,
    touch: bool = True,
) -> PublicApiPrincipal:
    scheme, _, credentials = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": PUBLIC_API_ERROR_API_KEY_REQUIRED,
                "message": "API key required",
            },
        )
    raw_key = credentials.strip()
    key_hash = hash_api_key(raw_key)
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
    if touch:
        api_key.last_used_at = datetime.now(UTC)
    if touch:
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
    return PublicApiPrincipal(api_key_id=int(api_key.id), user_id=int(user.id))


async def get_public_api_user(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> User:
    user_id = getattr(request.state, "public_api_user_id", None)
    if user_id is None:
        principal = await authenticate_public_api_key(session, authorization, touch=True)
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
