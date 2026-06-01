# Authentication route handlers.
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Annotated

from app.core.config import runtime_app_env, settings
from app.core.rate_limit import (
    client_identifier_from_request,
    consume_sliding_window_limit,
)
from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.user import AuthResponse, UserCreate, UserResponse
from app.services.config.auth_security import (
    AUTH_RATE_LIMIT_MAX_BUCKETS,
    AUTH_RATE_LIMIT_WINDOW_SECONDS,
    auth_rate_limit,
    auth_rate_limit_key,
    secure_transport_required,
)
from app.services.auth_service import authenticate_user, create_user
from app.services.config.runtime_settings import crawler_runtime_settings
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("app.auth")


def _auth_log_hash(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return ""
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _auth_client_id_from_request(request: Request) -> str:
    return client_identifier_from_request(
        request,
        trusted_proxies=tuple(crawler_runtime_settings.api_rate_limit_trusted_proxies),
    )


async def _enforce_auth_rate_limit(request: Request, route_group: str) -> Response | None:
    crawler_state = getattr(request.app.state, "crawler", None)
    if crawler_state is None:
        raise RuntimeError("FastAPI app state.crawler must be initialized")
    client_identifier = client_identifier_from_request(
        request,
        trusted_proxies=tuple(crawler_runtime_settings.api_rate_limit_trusted_proxies),
    )
    allowed, retry_after = await consume_sliding_window_limit(
        crawler_state.auth_rate_limit_buckets,
        crawler_state.auth_rate_limit_lock,
        identifier=auth_rate_limit_key(client_identifier, route_group),
        window_seconds=AUTH_RATE_LIMIT_WINDOW_SECONDS,
        max_requests=auth_rate_limit(route_group),
        max_clients=AUTH_RATE_LIMIT_MAX_BUCKETS,
    )
    if allowed:
        return None
    return JSONResponse(
        {"detail": "Rate limit exceeded"},
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/register", response_model=UserResponse)
async def register(
    payload: UserCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse | Response:
    limited = await _enforce_auth_rate_limit(request, "register")
    if limited is not None:
        return limited
    if not settings.registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled. Enable REGISTRATION_ENABLED for multi-tenant deployments.",
        )
    existing = await session.execute(
        select(User).where(User.email == payload.email.lower())
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )
    user = await create_user(session, payload.email, payload.password)
    return UserResponse.model_validate(user, from_attributes=True)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: UserCreate,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthResponse | Response:
    limited = await _enforce_auth_rate_limit(request, "login")
    if limited is not None:
        return limited
    authenticated = await authenticate_user(session, payload.email, payload.password)
    client_id_hash = _auth_log_hash(_auth_client_id_from_request(request))
    if authenticated is None:
        logger.warning(
            "auth.login_failed",
            extra={
                "reason": "bad_credentials",
                "client_id_hash": client_id_hash,
                "email_hash": _auth_log_hash(payload.email),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    token, user = authenticated
    secure_cookie = secure_transport_required(runtime_app_env())
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        samesite="lax",
        secure=secure_cookie,
        path="/",
        max_age=int(settings.jwt_expire_hours * 3600),
    )
    logger.info(
        "auth.login_success",
        extra={"user_id": str(user.id), "client_id_hash": client_id_hash},
    )
    return AuthResponse(user=UserResponse.model_validate(user, from_attributes=True))


@router.get("/me")
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse.model_validate(user, from_attributes=True)
