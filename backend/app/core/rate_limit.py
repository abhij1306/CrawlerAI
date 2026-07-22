from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict, deque
from math import ceil
from time import monotonic

from starlette.requests import Request

from app.core.redis import RedisUnavailableError, redis_execute

logger = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "ratelimit"
# One ZSET key per identifier+window; members are unique request tokens scored
# by arrival time (Redis server clock, so all app processes share one window).
# Returns {allowed, retry_after_ms, remaining, reset_ms}.
_REDIS_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local window_ms = tonumber(ARGV[1])
local max_requests = tonumber(ARGV[2])
local member = ARGV[3]
local clock = redis.call('TIME')
local now_ms = clock[1] * 1000 + math.floor(clock[2] / 1000)
redis.call('ZREMRANGEBYSCORE', key, '-inf', now_ms - window_ms)
local count = redis.call('ZCARD', key)
if count >= max_requests then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry_after_ms = window_ms
  if oldest[2] then
    retry_after_ms = math.max(1, math.ceil(oldest[2] + window_ms - now_ms))
  end
  return {0, retry_after_ms, 0, retry_after_ms}
end
redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms)
local oldest_after = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local reset_ms = window_ms
if oldest_after[2] then
  reset_ms = math.max(1, math.ceil(oldest_after[2] + window_ms - now_ms))
end
return {1, 0, max_requests - count - 1, reset_ms}
"""


def client_identifier_from_request(
    request: Request,
    *,
    trusted_proxies: tuple[str, ...] = (),
) -> str:
    peer_host = request.client.host if request.client and request.client.host else ""
    trusted_proxy_set = frozenset(
        normalized
        for normalized in (str(value).strip() for value in trusted_proxies)
        if normalized
    )
    forwarded_for = (
        request.headers.get("x-forwarded-for")
        if peer_host in trusted_proxy_set
        else None
    )
    if forwarded_for:
        first = forwarded_for.split(",", maxsplit=1)[0].strip()
        if first:
            return first
    if peer_host:
        return peer_host
    return "unknown"


def sliding_window_redis_key(identifier: str, *, window_seconds: float) -> str:
    window_ms = max(1, int(float(window_seconds) * 1000))
    return f"{_REDIS_KEY_PREFIX}:{window_ms}:{identifier}"


async def consume_redis_sliding_window(
    key: str,
    *,
    window_seconds: float,
    max_requests: int,
) -> tuple[bool, int, int, int] | None:
    """Consume one request from the Redis sliding-window bucket at ``key``.

    Returns (allowed, retry_after_seconds, remaining, reset_seconds), or None
    when the Redis path is unavailable (breaker open, Redis error, or an
    unexpected response shape) so the caller can use its in-process fallback.
    """
    window_ms = max(1, int(float(window_seconds) * 1000))
    try:
        raw = await redis_execute(
            lambda redis: redis.eval(
                _REDIS_SLIDING_WINDOW_SCRIPT,
                1,
                key,
                window_ms,
                int(max_requests),
                uuid.uuid4().hex,
            ),
            operation_name=f"rate_limit:consume:{key[:64]}",
        )
    except RedisUnavailableError:
        return None
    return _parse_sliding_window_result(raw)


def _parse_sliding_window_result(raw: object) -> tuple[bool, int, int, int] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        logger.debug(
            "Unexpected Redis sliding-window response shape; using in-process fallback"
        )
        return None
    try:
        allowed_raw, retry_after_ms, remaining, reset_ms = (
            int(value) for value in raw
        )
    except (TypeError, ValueError):
        logger.debug(
            "Unexpected Redis sliding-window response values; using in-process fallback"
        )
        return None
    if allowed_raw not in (0, 1):
        return None
    allowed = bool(allowed_raw)
    retry_after_seconds = (
        0 if allowed else max(1, ceil(max(0, retry_after_ms) / 1000))
    )
    reset_seconds = max(1, ceil(max(0, reset_ms) / 1000))
    return allowed, retry_after_seconds, max(0, remaining), reset_seconds


async def consume_sliding_window_limit(
    buckets: OrderedDict[str, deque[float]],
    lock: asyncio.Lock,
    *,
    identifier: str,
    window_seconds: float,
    max_requests: int,
    max_clients: int,
) -> tuple[bool, int]:
    redis_result = await consume_redis_sliding_window(
        sliding_window_redis_key(identifier, window_seconds=window_seconds),
        window_seconds=window_seconds,
        max_requests=max_requests,
    )
    if redis_result is not None:
        allowed, retry_after, _remaining, _reset = redis_result
        return allowed, retry_after

    now = monotonic()
    async with lock:
        bucket = buckets.get(identifier)
        if bucket is None:
            bucket = deque()
            buckets[identifier] = bucket
        else:
            buckets.move_to_end(identifier)

        cutoff = now - float(window_seconds)
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= int(max_requests):
            retry_after = max(1, int(bucket[0] + float(window_seconds) - now))
            return False, retry_after

        bucket.append(now)
        while len(buckets) > int(max_clients):
            buckets.popitem(last=False)
        return True, 0
