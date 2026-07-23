from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.acquisition import (
    browser_context_lifecycle,
    browser_runtime_lifecycle,
)
from app.acquisition.browser_pool import SharedBrowserRuntime
from app.core.config.runtime_settings import crawler_runtime_settings

pytestmark = pytest.mark.unit


def _runtime(**kwargs) -> SharedBrowserRuntime:
    kwargs.setdefault("max_contexts", 2)
    return SharedBrowserRuntime(**kwargs)


def test_update_active_contexts_clamps_at_zero() -> None:
    runtime = _runtime()
    browser_context_lifecycle.update_active_contexts(runtime, 3)
    assert runtime._active_contexts == 3
    browser_context_lifecycle.update_active_contexts(runtime, -10)
    assert runtime._active_contexts == 0


def test_update_queue_count_clamps_at_zero() -> None:
    runtime = _runtime()
    browser_context_lifecycle.update_queue_count(runtime, -1)
    assert runtime._queued_count == 0
    browser_context_lifecycle.update_queue_count(runtime, 2)
    assert runtime._queued_count == 2


async def test_release_context_capacity_releases_semaphore() -> None:
    runtime = _runtime(max_contexts=1)
    await runtime._semaphore.acquire()
    runtime._active_contexts = 1
    assert runtime._semaphore.locked()
    browser_context_lifecycle.release_context_capacity(runtime)
    assert not runtime._semaphore.locked()
    assert runtime._active_contexts == 0


def test_context_recycle_threshold_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    monkeypatch.setattr(
        crawler_runtime_settings, "browser_max_contexts_before_recycle", 3
    )
    assert browser_runtime_lifecycle.context_recycle_threshold_reached(runtime) is False
    runtime._total_contexts_created = 3
    assert browser_runtime_lifecycle.context_recycle_threshold_reached(runtime) is True
    monkeypatch.setattr(
        crawler_runtime_settings, "browser_max_contexts_before_recycle", 0
    )
    assert browser_runtime_lifecycle.context_recycle_threshold_reached(runtime) is False


def test_should_recycle_browser_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime()
    assert browser_runtime_lifecycle.should_recycle_browser(runtime) is False
    runtime._browser = SimpleNamespace(is_connected=lambda: False)
    assert browser_runtime_lifecycle.should_recycle_browser(runtime) is True

    runtime = _runtime()
    runtime._browser = SimpleNamespace(is_connected=lambda: True)
    runtime._active_contexts = 1
    runtime._browser_launched_at = time.monotonic() - 100.0
    monkeypatch.setattr(crawler_runtime_settings, "browser_max_lifetime_seconds", 1)
    assert browser_runtime_lifecycle.should_recycle_browser(runtime) is False
    runtime._active_contexts = 0
    assert browser_runtime_lifecycle.should_recycle_browser(runtime) is True


async def test_ensure_delegates_to_lifecycle_collaborator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[SharedBrowserRuntime] = []

    async def _fake_ensure(runtime: SharedBrowserRuntime) -> None:
        calls.append(runtime)

    monkeypatch.setattr(
        browser_runtime_lifecycle, "ensure_browser_runtime", _fake_ensure
    )
    runtime = _runtime()
    await runtime.ensure()
    assert calls == [runtime]


async def test_close_delegates_to_lifecycle_collaborator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[SharedBrowserRuntime] = []

    async def _fake_close(runtime: SharedBrowserRuntime) -> None:
        calls.append(runtime)

    monkeypatch.setattr(
        browser_runtime_lifecycle, "close_browser_runtime_locked", _fake_close
    )
    runtime = _runtime()
    await runtime.close()
    assert calls == [runtime]


async def test_context_entry_points_delegate_to_context_collaborator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_acquire(runtime, *, phase_timings_ms) -> None:
        calls.append("acquire")

    async def _fake_ensure_with_timing(runtime, *, phase_timings_ms) -> None:
        calls.append("ensure_with_timing")

    async def _fake_open(runtime, *, context_options):
        calls.append("open")
        return ("context", "page")

    def _fake_release(runtime) -> None:
        calls.append("release")

    def _fake_update(runtime, delta: int) -> None:
        calls.append(f"update:{delta}")

    monkeypatch.setattr(
        browser_context_lifecycle, "acquire_context_slot", _fake_acquire
    )
    monkeypatch.setattr(
        browser_context_lifecycle, "ensure_with_timing", _fake_ensure_with_timing
    )
    monkeypatch.setattr(browser_context_lifecycle, "open_context_page", _fake_open)
    monkeypatch.setattr(
        browser_context_lifecycle, "release_context_capacity", _fake_release
    )
    monkeypatch.setattr(
        browser_context_lifecycle, "update_active_contexts", _fake_update
    )

    runtime = _runtime()
    await runtime._acquire_context_slot(phase_timings_ms=None)
    await runtime._ensure_with_timing(phase_timings_ms=None)
    assert await runtime._open_context_page(context_options={}) == ("context", "page")
    runtime._release_context_capacity()
    runtime._update_active_contexts(1)
    assert calls == [
        "acquire",
        "ensure_with_timing",
        "open",
        "release",
        "update:1",
    ]


async def test_acquire_context_slot_dispatches_instance_level_yield_patch() -> None:
    # Component tests patch ``runtime._yield_slot_until_recycle_window`` on the
    # instance; the collaborator must keep dispatching through the instance.
    runtime = _runtime(max_contexts=1)
    calls: list[float] = []

    async def _fake_yield(timeout_seconds: float) -> bool:
        calls.append(timeout_seconds)
        return False

    runtime._yield_slot_until_recycle_window = _fake_yield
    await browser_context_lifecycle.acquire_context_slot(runtime, phase_timings_ms=None)
    assert len(calls) == 1
    assert runtime._queued_count == 0
    assert runtime._semaphore.locked()


async def test_yield_slot_delegate_calls_lifecycle_collaborator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_yield(runtime: SharedBrowserRuntime, timeout_seconds: float):
        return (runtime, timeout_seconds)

    monkeypatch.setattr(
        browser_runtime_lifecycle, "yield_slot_until_recycle_window", _fake_yield
    )
    runtime = _runtime()
    assert await runtime._yield_slot_until_recycle_window(1.5) == (runtime, 1.5)
