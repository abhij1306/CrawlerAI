"""Unit tests for the Redis sliding-window rate-limit consumer (audit 1.9)."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict

import pytest

import app.core.redis as app_redis
from app.core.rate_limit import (
    consume_redis_sliding_window,
    consume_sliding_window_limit,
    sliding_window_redis_key,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_BASE_NOW_MS = 1_700_000_000_000


class _SlidingWindowFakeRedis:
    """Script-aware fake: emulates the sliding-window Lua with a settable clock."""

    def __init__(self) -> None:
        self._zsets: dict[str, dict[str, float]] = {}
        self.now_ms = _BASE_NOW_MS
        self.eval_calls = 0

    async def eval(self, script: str, numkeys: int, *args: object):
        assert "ZREMRANGEBYSCORE" in script
        assert numkeys == 1
        self.eval_calls += 1
        key = str(args[0])
        window_ms = int(args[1])
        max_requests = int(args[2])
        member = str(args[3])
        zset = self._zsets.setdefault(key, {})
        cutoff = self.now_ms - window_ms
        for existing, score in list(zset.items()):
            if score <= cutoff:
                del zset[existing]
        count = len(zset)
        if count >= max_requests:
            oldest = min(zset.values()) if zset else None
            retry_after_ms = (
                window_ms
                if oldest is None
                else max(1, math.ceil(oldest + window_ms - self.now_ms))
            )
            return [0, retry_after_ms, 0, retry_after_ms]
        zset[member] = self.now_ms
        oldest = min(zset.values())
        reset_ms = max(1, math.ceil(oldest + window_ms - self.now_ms))
        return [1, 0, max_requests - count - 1, reset_ms]


@pytest.fixture
def fake_redis_client(monkeypatch: pytest.MonkeyPatch) -> _SlidingWindowFakeRedis:
    client = _SlidingWindowFakeRedis()
    monkeypatch.setattr(app_redis, "_client", client)
    return client


async def test_redis_path_allows_up_to_limit_then_denies_with_retry_after(
    fake_redis_client: _SlidingWindowFakeRedis,
) -> None:
    key = sliding_window_redis_key("client-a", window_seconds=60)

    first = await consume_redis_sliding_window(
        key, window_seconds=60, max_requests=2
    )
    second = await consume_redis_sliding_window(
        key, window_seconds=60, max_requests=2
    )
    third = await consume_redis_sliding_window(
        key, window_seconds=60, max_requests=2
    )

    assert first is not None and first[0] is True
    assert first[2] == 1  # remaining
    assert second is not None and second[0] is True
    assert second[2] == 0
    assert third is not None
    assert third[0] is False
    assert 0 < third[1] <= 60  # retry_after seconds
    assert third[2] == 0


async def test_redis_path_window_slides_with_server_clock(
    fake_redis_client: _SlidingWindowFakeRedis,
) -> None:
    key = sliding_window_redis_key("client-b", window_seconds=60)
    await consume_redis_sliding_window(key, window_seconds=60, max_requests=1)
    denied = await consume_redis_sliding_window(
        key, window_seconds=60, max_requests=1
    )
    assert denied is not None and denied[0] is False

    fake_redis_client.now_ms += 61_000

    allowed = await consume_redis_sliding_window(
        key, window_seconds=60, max_requests=1
    )
    assert allowed is not None and allowed[0] is True


async def test_redis_path_keys_are_scoped_per_identifier_and_window(
    fake_redis_client: _SlidingWindowFakeRedis,
) -> None:
    await consume_redis_sliding_window(
        sliding_window_redis_key("client-c", window_seconds=60),
        window_seconds=60,
        max_requests=1,
    )

    other_identifier = await consume_redis_sliding_window(
        sliding_window_redis_key("client-d", window_seconds=60),
        window_seconds=60,
        max_requests=1,
    )
    other_window = await consume_redis_sliding_window(
        sliding_window_redis_key("client-c", window_seconds=5),
        window_seconds=5,
        max_requests=1,
    )

    assert other_identifier is not None and other_identifier[0] is True
    assert other_window is not None and other_window[0] is True


async def test_consume_sliding_window_limit_uses_redis_path(
    fake_redis_client: _SlidingWindowFakeRedis,
) -> None:
    buckets: OrderedDict[str, object] = OrderedDict()
    lock = asyncio.Lock()

    results = [
        await consume_sliding_window_limit(
            buckets,
            lock,
            identifier="client-e",
            window_seconds=60,
            max_requests=2,
            max_clients=10,
        )
        for _ in range(3)
    ]

    assert [allowed for allowed, _ in results] == [True, True, False]
    assert results[2][1] > 0  # retry_after from the Redis window
    assert fake_redis_client.eval_calls == 3
    assert buckets == OrderedDict()  # in-process buckets untouched


async def test_consume_sliding_window_limit_falls_back_on_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The conftest FakeRedis returns 0 for unknown scripts; the consumer must
    # treat that as "Redis path unavailable" and use the in-process buckets.
    buckets: OrderedDict[str, object] = OrderedDict()
    lock = asyncio.Lock()

    results = [
        await consume_sliding_window_limit(
            buckets,
            lock,
            identifier="client-f",
            window_seconds=60,
            max_requests=1,
            max_clients=10,
        )
        for _ in range(2)
    ]

    assert results[0] == (True, 0)
    assert results[1][0] is False
    assert results[1][1] in (59, 60)  # retry_after from the in-process window
    assert "client-f" in buckets


async def test_consume_sliding_window_limit_falls_back_when_redis_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RaisingRedis:
        async def eval(self, *_args: object) -> None:
            raise ConnectionError("redis down")

    monkeypatch.setattr(app_redis, "_client", _RaisingRedis())
    buckets: OrderedDict[str, object] = OrderedDict()
    lock = asyncio.Lock()

    allowed, retry_after = await consume_sliding_window_limit(
        buckets,
        lock,
        identifier="client-g",
        window_seconds=60,
        max_requests=1,
        max_clients=10,
    )

    assert (allowed, retry_after) == (True, 0)
    assert "client-g" in buckets
    assert app_redis.redis_failure_total() == 1


async def test_redis_execute_is_not_gated_on_redis_state_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_redis.settings, "redis_state_enabled", False)
    client = _SlidingWindowFakeRedis()
    monkeypatch.setattr(app_redis, "_client", client)

    result = await consume_redis_sliding_window(
        "ratelimit:test:ungated", window_seconds=60, max_requests=1
    )

    assert result is not None and result[0] is True
    assert client.eval_calls == 1


async def test_malformed_response_does_not_trip_circuit_breaker(
    fake_redis_client: _SlidingWindowFakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MalformedRedis:
        async def eval(self, *_args: object) -> int:
            return 0

    monkeypatch.setattr(app_redis, "_client", _MalformedRedis())

    result = await consume_redis_sliding_window(
        "ratelimit:test:malformed", window_seconds=60, max_requests=1
    )

    assert result is None
    assert app_redis.redis_failure_total() == 0
    assert app_redis._redis_failure_state.disabled_until == 0.0
