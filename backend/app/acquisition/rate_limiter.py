from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.domain_utils import normalize_host
from app.core.redis import RedisUnavailableError, redis_execute

logger = logging.getLogger(__name__)

_HOST_NEXT_ALLOWED_AT: dict[str, float] = {}
_HOST_PACING_LOCK = asyncio.Lock()

_REDIS_KEY_PREFIX = "pacing"
# One key per host holding the next-allowed fetch start (ms, Redis server clock
# so all app/worker processes share the schedule). Atomically claims the next
# slot: start = max(now, current); stores start+interval with a PX TTL that
# replaces the in-process pruning; returns {wait_ms, next_allowed_ms}.
_REDIS_CLAIM_HOST_SLOT_SCRIPT = """
local key = KEYS[1]
local interval_ms = tonumber(ARGV[1])
local ttl_ms = tonumber(ARGV[2])
local clock = redis.call('TIME')
local now_ms = clock[1] * 1000 + math.floor(clock[2] / 1000)
local current = tonumber(redis.call('GET', key) or '0')
local start_ms = math.max(now_ms, current)
local next_allowed_ms = start_ms + interval_ms
redis.call('SET', key, next_allowed_ms, 'PX', ttl_ms)
return {math.max(0, start_ms - now_ms), next_allowed_ms}
"""


def _normalized_host(value: str) -> str:
    return normalize_host(value)


def _host_slot_redis_key(host: str) -> str:
    return f"{_REDIS_KEY_PREFIX}:host:{host}"


async def _claim_host_slot_redis(
    host: str,
    *,
    interval_ms: int,
    ttl_seconds: int,
) -> float | None:
    """Claim the next fetch slot for ``host`` in Redis.

    Returns the wait in seconds until the claimed slot starts, or None when the
    Redis path is unavailable (breaker open, Redis error, or an unexpected
    response shape) so the caller can use the in-process fallback.
    """
    try:
        raw = await redis_execute(
            lambda redis: _eval_claim_host_slot_script(
                redis,
                host,
                interval_ms=interval_ms,
                ttl_seconds=ttl_seconds,
            ),
            operation_name=f"pacing:claim:{host[:64]}",
        )
    except RedisUnavailableError:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        logger.debug(
            "Unexpected Redis host-pacing response shape; using in-process fallback"
        )
        return None
    try:
        wait_ms = int(raw[0])
    except (TypeError, ValueError):
        return None
    return max(0.0, wait_ms / 1000.0)


async def _eval_claim_host_slot_script(
    redis: Redis,
    host: str,
    *,
    interval_ms: int,
    ttl_seconds: int,
) -> object:
    # redis-py stubs share the sync/async signatures: eval() is typed as
    # returning str | Awaitable[str] with str-only script args. The asyncio
    # client always returns an awaitable, and ints encode identically to
    # their str form on the wire.
    return await cast(
        Awaitable[object],
        redis.eval(
            _REDIS_CLAIM_HOST_SLOT_SCRIPT,
            1,
            _host_slot_redis_key(host),
            str(int(interval_ms)),
            str(max(1, int(ttl_seconds)) * 1000),
        ),
    )


async def wait_for_host_slot(_url: str, *, ttl_seconds: int | None = None) -> None:
    host = _normalized_host(_url)
    if not host:
        return
    min_interval_ms = _host_interval_ms(protected=False)
    resolved_ttl_seconds = max(
        1,
        int(
            ttl_seconds
            if ttl_seconds is not None
            else crawler_runtime_settings.pacing_host_cache_ttl_seconds
        ),
    )
    wait_seconds = await _claim_host_slot_redis(
        host,
        interval_ms=min_interval_ms,
        ttl_seconds=resolved_ttl_seconds,
    )
    if wait_seconds is None:
        now = time.monotonic()
        async with _HOST_PACING_LOCK:
            _prune_expired_hosts(now=now, ttl_seconds=resolved_ttl_seconds)
            next_allowed_at = _HOST_NEXT_ALLOWED_AT.get(host, now)
            wait_seconds = max(0.0, next_allowed_at - now)
            _HOST_NEXT_ALLOWED_AT[host] = max(now, next_allowed_at) + (
                min_interval_ms / 1000.0
            )
            _enforce_host_cache_limit()
    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)


async def reset_pacing_state() -> None:
    async with _HOST_PACING_LOCK:
        _HOST_NEXT_ALLOWED_AT.clear()

    async def _clear_redis_slots(redis) -> None:
        keys = [
            key
            async for key in redis.scan_iter(match=f"{_REDIS_KEY_PREFIX}:host:*")
        ]
        if keys:
            await redis.delete(*keys)

    try:
        await redis_execute(_clear_redis_slots, operation_name="pacing:reset")
    except RedisUnavailableError:
        pass


async def apply_protected_host_backoff(
    _url: str,
    *,
    ttl_seconds: int | None = None,
) -> None:
    host = _normalized_host(_url)
    if not host:
        return
    resolved_ttl_seconds = max(
        1,
        int(
            ttl_seconds
            if ttl_seconds is not None
            else crawler_runtime_settings.pacing_host_cache_ttl_seconds
        ),
    )
    protected_interval_ms = _host_interval_ms(protected=True)
    # Same claim script as wait_for_host_slot with the protected interval: the
    # next slot is pushed at least protected_interval_ms out, and repeated
    # blocks on an already backed-off host keep escalating the window.
    claimed = await _claim_host_slot_redis(
        host,
        interval_ms=protected_interval_ms,
        ttl_seconds=resolved_ttl_seconds,
    )
    if claimed is not None:
        return
    now = time.monotonic()
    protected_interval_seconds = protected_interval_ms / 1000.0
    async with _HOST_PACING_LOCK:
        _prune_expired_hosts(now=now, ttl_seconds=resolved_ttl_seconds)
        next_allowed_at = _HOST_NEXT_ALLOWED_AT.get(host, now)
        _HOST_NEXT_ALLOWED_AT[host] = max(
            next_allowed_at, now + protected_interval_seconds
        )
        _enforce_host_cache_limit()


async def record_fetch_outcome(
    _url: str,
    *,
    status_code: int,
    blocked: bool,
    ttl_seconds: int | None = None,
) -> bool:
    if blocked or int(status_code or 0) in set(
        crawler_runtime_settings.http_retry_status_codes
    ):
        await apply_protected_host_backoff(_url, ttl_seconds=ttl_seconds)
        return True
    return False


def _host_interval_ms(*, protected: bool) -> int:
    base_interval_ms = max(
        0,
        int(crawler_runtime_settings.acquire_host_min_interval_ms),
    )
    if not protected:
        return base_interval_ms
    return max(
        base_interval_ms,
        int(crawler_runtime_settings.protected_host_additional_interval_ms),
    )


def _prune_expired_hosts(*, now: float, ttl_seconds: int) -> None:
    expired_hosts = [
        host
        for host, allowed_at in _HOST_NEXT_ALLOWED_AT.items()
        if now > allowed_at + ttl_seconds
    ]
    for host in expired_hosts:
        _HOST_NEXT_ALLOWED_AT.pop(host, None)


def _enforce_host_cache_limit() -> None:
    max_entries = max(
        1,
        int(crawler_runtime_settings.pacing_host_cache_max_entries),
    )
    _trim_host_cache(_HOST_NEXT_ALLOWED_AT, max_entries=max_entries)


def _trim_host_cache(cache: dict[str, float], *, max_entries: int) -> None:
    overflow = len(cache) - max_entries
    if overflow <= 0:
        return
    for host, _ in sorted(cache.items(), key=lambda item: item[1])[:overflow]:
        cache.pop(host, None)
