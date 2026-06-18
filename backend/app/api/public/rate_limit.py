from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from math import ceil
from time import monotonic

from app.services.config.public_api import (
    PUBLIC_API_BURST_WINDOW_SECONDS,
    PUBLIC_API_EXTRACT_BURST_LIMIT,
    PUBLIC_API_EXTRACT_RATE_LIMIT,
    PUBLIC_API_RATE_LIMIT_MAX_BUCKETS,
    PUBLIC_API_RATE_LIMIT_WINDOW_SECONDS,
    PUBLIC_API_READ_BURST_LIMIT,
    PUBLIC_API_READ_RATE_LIMIT,
)


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
    lock,
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
            minute_retry = _retry_after(
                minute_bucket,
                now=now,
                window_seconds=PUBLIC_API_RATE_LIMIT_WINDOW_SECONDS,
            )
            burst_retry = _retry_after(
                burst_bucket,
                now=now,
                window_seconds=PUBLIC_API_BURST_WINDOW_SECONDS,
            )
            retry_after = max(1, min(value for value in (minute_retry, burst_retry) if value > 0))
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
        remaining = min(minute_limit - len(minute_bucket), burst_limit - len(burst_bucket))
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
