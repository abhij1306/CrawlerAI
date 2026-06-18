from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from time import monotonic

from starlette.requests import Request


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


async def consume_sliding_window_limit(
    buckets: OrderedDict[str, deque[float]],
    lock: asyncio.Lock,
    *,
    identifier: str,
    window_seconds: float,
    max_requests: int,
    max_clients: int,
) -> tuple[bool, int]:
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
