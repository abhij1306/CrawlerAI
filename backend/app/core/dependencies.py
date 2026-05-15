# FastAPI dependency helpers.
from __future__ import annotations

import inspect
import logging
import threading

from app.core.config import settings
from app.core.database import get_session
from app.core.security import decode_access_token
from app.models.user import User
from app.services.dispatch.base import RunDispatcher
from app.services.dispatch.celery_dispatcher import CeleryRunDispatcher
from app.services.dispatch.local_dispatcher import LocalRunDispatcher
from fastapi import Cookie, Depends, Header, HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_run_dispatchers: dict[bool, RunDispatcher] = {}
_dispatcher_lock = threading.Lock()


async def get_db(
    session: AsyncSession = Depends(get_session),  # noqa: B008 - FastAPI injects dependencies via parameter defaults.
) -> AsyncSession:
    return session


async def get_current_user(
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),  # noqa: B008 - FastAPI dependency injection requires Depends defaults.
) -> User:
    token = access_token
    if not token and authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            token = credentials.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
        token_version = int(payload.get("ver", 0))
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user"
        )
    user_token_version = user.token_version if user.token_version is not None else 0
    if user_token_version != token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired"
        )
    return user


async def require_admin(
    user: User = Depends(get_current_user),  # noqa: B008 - FastAPI dependency injection requires Depends defaults.
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
            dispatcher = CeleryRunDispatcher() if celery_enabled else LocalRunDispatcher()
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
                "Error shutting down dispatcher %s", type(dispatcher).__name__,
                exc_info=True,
            )
