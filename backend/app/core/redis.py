from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "close_redis",
    "get_redis",
    "get_redis_pool",
    "redis_fail_open",
    "redis_failure_total",
    "redis_is_enabled",
    "schedule_fail_open",
]

_pool: ConnectionPool | None = None
_client: Redis | None = None
_DISABLE_COOLDOWN_SECONDS = 30.0
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()
T = TypeVar("T")
_LOG_EXTRA_TOKEN_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


@dataclass
class _RedisFailureState:
    disabled_until: float = 0.0
    last_disable_log_at: float = 0.0
    total: int = 0


_redis_failure_state = _RedisFailureState()


def _safe_log_extra_token(value: object) -> str:
    text = str(value or "")[:128]
    return _LOG_EXTRA_TOKEN_RE.sub("_", text)


def redis_is_enabled() -> bool:
    if not settings.redis_state_enabled:
        return False
    return time.monotonic() >= _redis_failure_state.disabled_until


def _temporarily_disable_redis(_exc: Exception) -> None:
    now = time.monotonic()
    _redis_failure_state.disabled_until = now + _DISABLE_COOLDOWN_SECONDS
    _redis_failure_state.total += 1
    if now - _redis_failure_state.last_disable_log_at >= _DISABLE_COOLDOWN_SECONDS:
        logger.warning(
            "Redis unavailable; disabling shared state for %.0fs",
            _DISABLE_COOLDOWN_SECONDS,
            extra={"exception_type": _safe_log_extra_token(type(_exc).__name__)},
        )
        _redis_failure_state.last_disable_log_at = now


def get_redis_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            health_check_interval=30,
        )
    return _pool


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis(connection_pool=get_redis_pool())
    return _client


def redis_failure_total() -> int:
    return _redis_failure_state.total


async def close_redis() -> None:
    global _client, _pool
    client = _client
    pool = _pool
    _client = None
    _pool = None
    if client is not None:
        await client.aclose()
    if pool is not None:
        await pool.aclose()


async def redis_fail_open(
    operation: Callable[[Redis], Awaitable[T]],
    *,
    default: T,
    operation_name: str,
) -> T:
    if not redis_is_enabled():
        return default
    try:
        return await operation(get_redis())
    except Exception as exc:
        _temporarily_disable_redis(exc)
        logger.warning(
            "Redis operation failed; continuing without shared state",
            exc_info=False,
            extra={
                "exception_type": _safe_log_extra_token(type(exc).__name__),
            },
        )
        return default


def schedule_fail_open(
    operation: Callable[[Redis], Awaitable[object]],
    *,
    operation_name: str,
) -> None:
    if not redis_is_enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _runner() -> None:
        await redis_fail_open(
            operation,
            default=None,
            operation_name=operation_name,
        )

    task = loop.create_task(_runner())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
