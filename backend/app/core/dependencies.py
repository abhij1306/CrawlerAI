# FastAPI dependency helpers.
from __future__ import annotations

import inspect
import hashlib
import hmac
import logging
import secrets
import threading
from urllib.parse import urlsplit

from app.core.config import get_frontend_origins, settings
from app.core.config.auth_security import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    CSRF_UNSAFE_METHODS,
)
from app.core.database import get_session
from app.core.security import TokenDecodeError, decode_access_token
from app.models.user import User
from app.workers.base import RunDispatcher
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_run_dispatchers: dict[bool, RunDispatcher] = {}
_dispatcher_lock = threading.Lock()


def get_db(
    session: AsyncSession = Depends(get_session),
) -> AsyncSession:
    return session


def _access_token_from_headers(
    access_token: str | None, authorization: str | None
) -> str | None:
    token = None
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            token = credentials.strip()
    return token or access_token


def _token_source(access_token: str | None, authorization: str | None) -> str | None:
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            return "bearer"
    return "cookie" if access_token else None


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _csrf_signature(nonce: str) -> str:
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        nonce.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def csrf_token_is_valid(value: str) -> bool:
    nonce, separator, signature = str(value or "").partition(".")
    return bool(
        separator
        and nonce
        and signature
        and hmac.compare_digest(signature, _csrf_signature(nonce))
    )


def create_csrf_token() -> str:
    nonce = secrets.token_urlsafe(32)
    return f"{nonce}.{_csrf_signature(nonce)}"


def enforce_cookie_csrf(request: Request) -> None:
    if request.method.upper() not in CSRF_UNSAFE_METHODS:
        return
    supplied_origin = _origin(request.headers.get("origin", ""))
    if supplied_origin is None:
        supplied_origin = _origin(request.headers.get("referer", ""))
    request_origin = _origin(str(request.base_url))
    allowed_origins = {
        origin
        for origin in (_origin(value) for value in get_frontend_origins())
        if origin is not None
    }
    if request_origin is not None:
        allowed_origins.add(request_origin)
    if supplied_origin not in allowed_origins:
        raise HTTPException(status_code=403, detail="CSRF origin rejected")

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
    header_token = request.headers.get(CSRF_HEADER_NAME, "")
    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
        or not csrf_token_is_valid(cookie_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF token rejected")


async def _resolve_token_user(
    session: AsyncSession, token: str
) -> tuple[User | None, str]:
    """Resolve a user from an access token; (None, 401 detail) on failure."""
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
        token_version = int(payload.get("ver", 0))
    except (TokenDecodeError, KeyError, ValueError):
        return None, "Invalid token"
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None, "Inactive user"
    user_token_version = user.token_version if user.token_version is not None else 0
    if user_token_version != token_version:
        return None, "Session expired"
    return user, ""


async def get_current_user(
    request: Request,
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> User:
    if _token_source(access_token, authorization) == "cookie":
        enforce_cookie_csrf(request)
    token = _access_token_from_headers(access_token, authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    user, detail = await _resolve_token_user(session, token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
    return user


async def get_current_user_optional(
    request: Request,
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> User | None:
    """Same resolution as get_current_user but anonymous-friendly (no 401)."""
    if _token_source(access_token, authorization) == "cookie":
        enforce_cookie_csrf(request)
    token = _access_token_from_headers(access_token, authorization)
    if not token:
        return None
    user, _detail = await _resolve_token_user(session, token)
    return user


def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return user


def get_run_dispatcher() -> RunDispatcher:
    """Resolve one shared run dispatcher per dispatch mode."""
    celery_enabled = bool(settings.celery_dispatch_enabled)
    dispatcher = _run_dispatchers.get(celery_enabled)
    if dispatcher is not None:
        return dispatcher
    with _dispatcher_lock:
        # Double-check after acquiring lock.
        dispatcher = _run_dispatchers.get(celery_enabled)
        if dispatcher is None:
            if celery_enabled:
                from app.workers.celery_dispatcher import CeleryRunDispatcher

                dispatcher = CeleryRunDispatcher()
            else:
                from app.workers.local_dispatcher import LocalRunDispatcher

                dispatcher = LocalRunDispatcher()
            _run_dispatchers[celery_enabled] = dispatcher
    return dispatcher


async def shutdown_run_dispatchers() -> None:
    """Best-effort cleanup for shared dispatcher instances."""
    # Hold the lock while copying + clearing so concurrent callers of
    # get_run_dispatcher cannot create a fresh dispatcher that escapes cleanup.
    # Release before awaiting to avoid blocking new lookups during async shutdowns.
    with _dispatcher_lock:
        dispatchers = list(_run_dispatchers.values())
        _run_dispatchers.clear()
    for dispatcher in dispatchers:
        cleanup = getattr(dispatcher, "shutdown", None) or getattr(
            dispatcher, "close", None
        )
        if not callable(cleanup):
            continue
        try:
            result = cleanup()
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.warning(
                "Error shutting down dispatcher %s",
                type(dispatcher).__name__,
                exc_info=True,
            )
