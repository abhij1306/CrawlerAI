from __future__ import annotations

import asyncio
import fnmatch

import pytest

import app.core.redis as app_redis
from app.acquisition import rate_limiter as pacing


@pytest.mark.asyncio
@pytest.mark.component
async def test_apply_protected_host_backoff_extends_wait_window(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(
        pacing.crawler_runtime_settings,
        acquire_host_min_interval_ms=250,
        protected_host_additional_interval_ms=2000,
    )
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(pacing.asyncio, "sleep", _fake_sleep)
    await pacing.reset_pacing_state()
    url = "https://example.com/products/widget"
    try:
        await pacing.wait_for_host_slot(url)
        await pacing.record_fetch_outcome(url, status_code=429, blocked=False)
        await pacing.wait_for_host_slot(url)
    finally:
        await pacing.reset_pacing_state()

    assert sleeps
    assert sleeps[-1] >= 1.5


@pytest.mark.asyncio
@pytest.mark.component
async def test_conftest_fake_redis_uses_in_process_fallback(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    # The conftest FakeRedis returns 0 for the pacing script, so the in-process
    # schedule is the fallback and must stay green.
    patch_settings(
        pacing.crawler_runtime_settings,
        acquire_host_min_interval_ms=250,
    )
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(pacing.asyncio, "sleep", _fake_sleep)
    await pacing.reset_pacing_state()
    url = "https://fallback.example.com/products/widget"
    try:
        await pacing.wait_for_host_slot(url)
        await pacing.wait_for_host_slot(url)

        assert pacing._HOST_NEXT_ALLOWED_AT
        assert sleeps == [pytest.approx(0.25, abs=0.05)]
    finally:
        await pacing.reset_pacing_state()


class _PacingFakeRedis:
    """Script-aware fake: emulates the host-pacing claim Lua with a settable clock."""

    def __init__(self) -> None:
        self._values: dict[str, float] = {}
        self.now_ms = 1_700_000_000_000
        self.eval_calls = 0

    async def eval(self, script: str, numkeys: int, *args: object):
        assert "'SET'" in script
        assert numkeys == 1
        self.eval_calls += 1
        key = str(args[0])
        interval_ms = int(args[1])
        current = float(self._values.get(key, 0.0))
        start_ms = max(self.now_ms, current)
        next_allowed_ms = start_ms + interval_ms
        self._values[key] = next_allowed_ms
        return [max(0, start_ms - self.now_ms), next_allowed_ms]

    async def scan_iter(self, *, match: str | None = None):
        for key in list(self._values):
            if match is None or fnmatch.fnmatch(key, match):
                yield key

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._values:
                del self._values[key]
                deleted += 1
        return deleted


@pytest.fixture
def pacing_redis(monkeypatch: pytest.MonkeyPatch) -> _PacingFakeRedis:
    client = _PacingFakeRedis()
    monkeypatch.setattr(app_redis, "_client", client)
    return client


@pytest.mark.asyncio
@pytest.mark.component
async def test_redis_path_serializes_concurrent_callers_to_one_slot_per_interval(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
    pacing_redis: _PacingFakeRedis,
) -> None:
    patch_settings(
        pacing.crawler_runtime_settings,
        acquire_host_min_interval_ms=250,
    )
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(pacing.asyncio, "sleep", _fake_sleep)
    url = "https://example.com/products/widget"
    try:
        await asyncio.gather(*(pacing.wait_for_host_slot(url) for _ in range(4)))

        # Each caller claims a distinct 250ms slot: waits of 0/0.25/0.5/0.75s.
        assert sorted(sleeps) == [
            pytest.approx(0.25),
            pytest.approx(0.5),
            pytest.approx(0.75),
        ]
        # In-process schedule untouched — Redis owns the host schedule.
        assert pacing._HOST_NEXT_ALLOWED_AT == {}
        assert pacing_redis.eval_calls == 4
    finally:
        await pacing.reset_pacing_state()
        assert pacing_redis._values == {}


@pytest.mark.asyncio
@pytest.mark.component
async def test_redis_path_protected_backoff_pushes_next_allowed(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
    pacing_redis: _PacingFakeRedis,
) -> None:
    patch_settings(
        pacing.crawler_runtime_settings,
        acquire_host_min_interval_ms=250,
        protected_host_additional_interval_ms=2000,
    )
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(pacing.asyncio, "sleep", _fake_sleep)
    url = "https://example.com/products/widget"
    try:
        await pacing.wait_for_host_slot(url)
        await pacing.record_fetch_outcome(url, status_code=429, blocked=False)
        await pacing.wait_for_host_slot(url)

        # Backoff claims a protected-interval slot past the current schedule,
        # so the next fetch waits at least the 2s protected window (without
        # the backoff it would wait only the 250ms base interval).
        assert len(sleeps) == 1
        assert sleeps[0] >= 2.0
        assert pacing._HOST_NEXT_ALLOWED_AT == {}
    finally:
        await pacing.reset_pacing_state()


@pytest.mark.asyncio
@pytest.mark.component
async def test_redis_path_slots_expire_with_redis_ttl_window(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
    pacing_redis: _PacingFakeRedis,
) -> None:
    patch_settings(
        pacing.crawler_runtime_settings,
        acquire_host_min_interval_ms=250,
    )
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(pacing.asyncio, "sleep", _fake_sleep)
    url = "https://example.com/products/widget"
    try:
        await pacing.wait_for_host_slot(url)
        pacing_redis.now_ms += 60_000
        await pacing.wait_for_host_slot(url)

        # Far past the interval: the second caller starts immediately.
        assert sleeps == []
    finally:
        await pacing.reset_pacing_state()
