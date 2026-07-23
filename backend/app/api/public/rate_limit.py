from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass
from math import ceil
from time import monotonic

from app.core.config.public_api import (
    PUBLIC_API_BURST_WINDOW_SECONDS,
    PUBLIC_API_EXTRACT_BURST_LIMIT,
    PUBLIC_API_EXTRACT_RATE_LIMIT,
    PUBLIC_API_RATE_LIMIT_MAX_BUCKETS,
    PUBLIC_API_RATE_LIMIT_WINDOW_SECONDS,
    PUBLIC_API_READ_BURST_LIMIT,
    PUBLIC_API_READ_RATE_LIMIT,
)
from app.core.rate_limit import consume_redis_sliding_window

_REDIS_KEY_PREFIX = "ratelimit:public"


@dataclass(frozen=True)
class PublicRateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    retry_after: int

    def headers(self) -> dict[str, str]:
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(max(0, self.reset_seconds)),
        }
        if not self.allowed:
            headers["Retry-After"] = str(max(1, self.retry_after))
        return headers


def public_rate_scope(path: str) -> str:
    return "extract" if path.startswith("/api/v1/extract") else "read"


async def consume_public_rate_limit(
    buckets: OrderedDict[str, deque[float]],
    lock: asyncio.Lock,
    *,
    api_key_id: int,
    scope: str,
) -> PublicRateLimitResult:
    if scope == "extract":
        minute_limit = PUBLIC_API_EXTRACT_RATE_LIMIT
        burst_limit = PUBLIC_API_EXTRACT_BURST_LIMIT
    else:
        minute_limit = PUBLIC_API_READ_RATE_LIMIT
        burst_limit = PUBLIC_API_READ_BURST_LIMIT

    redis_result = await _consume_public_rate_limit_redis(
        api_key_id=api_key_id,
        scope=scope,
        minute_limit=minute_limit,
        burst_limit=burst_limit,
    )
    if redis_result is not None:
        return redis_result

    now = monotonic()
    minute_key = f"public:{api_key_id}:{scope}:minute"
    burst_key = f"public:{api_key_id}:{scope}:burst"
    async with lock:
        minute_bucket = _bucket_for(buckets, minute_key)
        burst_bucket = _bucket_for(buckets, burst_key)
        _trim(minute_bucket, now - PUBLIC_API_RATE_LIMIT_WINDOW_SECONDS)
        _trim(burst_bucket, now - PUBLIC_API_BURST_WINDOW_SECONDS)

        minute_allowed = len(minute_bucket) < minute_limit
        burst_allowed = len(burst_bucket) < burst_limit
        if not minute_allowed or not burst_allowed:
            retry_after_values: list[int] = []
            if not minute_allowed:
                retry_after_values.append(
                    _retry_after(
                        minute_bucket,
                        now=now,
                        window_seconds=PUBLIC_API_RATE_LIMIT_WINDOW_SECONDS,
                    )
                )
            if not burst_allowed:
                retry_after_values.append(
                    _retry_after(
                        burst_bucket,
                        now=now,
                        window_seconds=PUBLIC_API_BURST_WINDOW_SECONDS,
                    )
                )
            retry_after = max(retry_after_values, default=1)
            return PublicRateLimitResult(
                allowed=False,
                limit=minute_limit,
                remaining=0,
                reset_seconds=retry_after,
                retry_after=retry_after,
            )

        minute_bucket.append(now)
        burst_bucket.append(now)
        while len(buckets) > PUBLIC_API_RATE_LIMIT_MAX_BUCKETS:
            buckets.popitem(last=False)
        remaining = min(
            minute_limit - len(minute_bucket), burst_limit - len(burst_bucket)
        )
        reset_seconds = _retry_after(
            minute_bucket,
            now=now,
            window_seconds=PUBLIC_API_RATE_LIMIT_WINDOW_SECONDS,
        )
        return PublicRateLimitResult(
            allowed=True,
            limit=minute_limit,
            remaining=remaining,
            reset_seconds=reset_seconds,
            retry_after=0,
        )


async def _consume_public_rate_limit_redis(
    *,
    api_key_id: int,
    scope: str,
    minute_limit: int,
    burst_limit: int,
) -> PublicRateLimitResult | None:
    """Globally enforced minute + burst buckets (two ZSET keys per key/scope).

    Returns None when the Redis path is unavailable so the caller falls back to
    the in-process buckets.
    """
    minute = await consume_redis_sliding_window(
        f"{_REDIS_KEY_PREFIX}:{api_key_id}:{scope}:minute",
        window_seconds=PUBLIC_API_RATE_LIMIT_WINDOW_SECONDS,
        max_requests=minute_limit,
    )
    if minute is None:
        return None
    burst = await consume_redis_sliding_window(
        f"{_REDIS_KEY_PREFIX}:{api_key_id}:{scope}:burst",
        window_seconds=PUBLIC_API_BURST_WINDOW_SECONDS,
        max_requests=burst_limit,
    )
    if burst is None:
        return None
    minute_allowed, minute_retry, minute_remaining, minute_reset = minute
    burst_allowed, burst_retry, burst_remaining, _burst_reset = burst
    if not minute_allowed or not burst_allowed:
        retry_after = max(
            1,
            minute_retry if not minute_allowed else 0,
            burst_retry if not burst_allowed else 0,
        )
        return PublicRateLimitResult(
            allowed=False,
            limit=minute_limit,
            remaining=0,
            reset_seconds=retry_after,
            retry_after=retry_after,
        )
    return PublicRateLimitResult(
        allowed=True,
        limit=minute_limit,
        remaining=min(minute_remaining, burst_remaining),
        reset_seconds=minute_reset,
        retry_after=0,
    )


def _bucket_for(buckets: OrderedDict[str, deque[float]], key: str) -> deque[float]:
    bucket = buckets.get(key)
    if bucket is None:
        bucket = deque()
        buckets[key] = bucket
    else:
        buckets.move_to_end(key)
    return bucket


def _trim(bucket: deque[float], cutoff: float) -> None:
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


def _retry_after(bucket: deque[float], *, now: float, window_seconds: int) -> int:
    if not bucket:
        return int(window_seconds)
    return max(1, ceil(bucket[0] + window_seconds - now))
