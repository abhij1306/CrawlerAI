from __future__ import annotations

import asyncio
import time

import pytest

from app.core import redis as redis_module


@pytest.mark.asyncio
@pytest.mark.regression
async def test_schedule_fail_open_tracks_background_tasks_until_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    finished = asyncio.Event()
    release = asyncio.Event()

    async def _fake_redis_fail_open(operation, *, default):
        del operation, default
        started.set()
        await release.wait()
        finished.set()
        return None

    redis_module._BACKGROUND_TASKS.clear()
    monkeypatch.setattr(redis_module, "redis_is_enabled", lambda: True)
    monkeypatch.setattr(redis_module, "redis_fail_open", _fake_redis_fail_open)

    redis_module.schedule_fail_open(lambda _: asyncio.sleep(0))

    await asyncio.wait_for(started.wait(), timeout=1)
    assert len(redis_module._BACKGROUND_TASKS) == 1

    release.set()
    await asyncio.wait_for(finished.wait(), timeout=1)
    await asyncio.sleep(0)

    assert redis_module._BACKGROUND_TASKS == set()


@pytest.mark.asyncio
@pytest.mark.regression
async def test_redis_execute_bypasses_redis_state_enabled_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redis_module.settings, "redis_state_enabled", False)

    async def _operation(redis) -> str:
        assert redis is redis_module.get_redis()
        return "ok"

    result = await redis_module.redis_execute(_operation, operation_name="test")

    assert result == "ok"


@pytest.mark.asyncio
@pytest.mark.regression
async def test_redis_execute_raises_when_circuit_breaker_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_module._redis_failure_state.disabled_until = time.monotonic() + 30
    called = False

    async def _operation(_redis) -> None:
        nonlocal called
        called = True

    with pytest.raises(redis_module.RedisUnavailableError):
        await redis_module.redis_execute(_operation, operation_name="test")

    assert called is False


@pytest.mark.asyncio
@pytest.mark.regression
async def test_redis_execute_trips_breaker_and_raises_on_operation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch

    async def _operation(_redis) -> None:
        raise ConnectionError("redis down")

    with pytest.raises(redis_module.RedisUnavailableError):
        await redis_module.redis_execute(_operation, operation_name="test")

    assert redis_module.redis_failure_total() == 1
    assert redis_module._redis_failure_state.disabled_until > time.monotonic()
