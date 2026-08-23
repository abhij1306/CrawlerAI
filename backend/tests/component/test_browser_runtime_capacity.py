"""test_browser_context cases split by public behavior."""

from __future__ import annotations

from tests.component.browser_context_test_support import (
    SimpleNamespace,
    _context_spec,
    acquisition_browser_pool,
    acquisition_browser_pool_page,
    acquisition_browser_runtime,
    asyncio,
    browser_background_tasks,
    crawl_fetch_runtime,
    crawler_runtime_settings,
    pytest,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_snapshot_tracks_queue_without_private_semaphore_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )

    async def _hold_page() -> None:
        async with runtime.page():
            entered.set()
            await release.wait()

    first = asyncio.create_task(_hold_page())
    await entered.wait()
    second = asyncio.create_task(_hold_page())
    await asyncio.sleep(0)

    snapshot = runtime.snapshot()

    assert snapshot["active"] == 1
    assert snapshot["queued"] == 1

    release.set()
    await asyncio.gather(first, second)


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_bounds_context_slot_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            del script
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        acquisition_browser_pool.crawler_runtime_settings,
        "browser_context_slot_timeout_seconds",
        0.01,
    )
    phase_timings_ms_first: dict[str, int] = {}
    phase_timings_ms_second: dict[str, int] = {}

    async def _hold_page() -> None:
        async with runtime.page(phase_timings_ms=phase_timings_ms_first):
            entered.set()
            await release.wait()

    first = asyncio.create_task(_hold_page())
    await entered.wait()
    try:
        with pytest.raises(TimeoutError, match="browser context slot"):
            async with runtime.page(phase_timings_ms=phase_timings_ms_second):
                await asyncio.sleep(0)
    finally:
        assert runtime._semaphore.locked()
        release.set()
        _ = await first

    snapshot = runtime.snapshot()
    assert snapshot["active"] == 0
    assert snapshot["queued"] == 0
    assert phase_timings_ms_first["context_open_ms"] >= 0
    assert phase_timings_ms_first["context_close_ms"] >= 0
    assert phase_timings_ms_second["context_slot_wait_ms"] >= 0
    assert "context_open_ms" not in phase_timings_ms_second
    assert "context_close_ms" not in phase_timings_ms_second


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_recycles_browser_without_deadlocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_events: list[str] = []
    new_events: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            new_events.append("context_closed")

    class FakeBrowser:
        def __init__(self, events: list[str]) -> None:
            self._events = events

        def is_connected(self) -> bool:
            return True

        async def new_context(self, **kwargs):
            del kwargs
            self._events.append("new_context")
            return FakeContext()

        async def close(self) -> None:
            self._events.append("browser_closed")

    class FakePlaywrightInstance:
        def __init__(self, events: list[str]) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)
            self._events = events

        async def _launch(self, **kwargs):
            del kwargs
            self._events.append("launched")
            return FakeBrowser(self._events)

        async def stop(self) -> None:
            self._events.append("playwright_stopped")

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance(new_events)

    class OldPlaywright:
        async def stop(self) -> None:
            old_events.append("playwright_stopped")

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser(old_events)
    runtime._playwright = OldPlaywright()
    runtime._browser_launched_at = 1.0
    runtime._total_contexts_created = 1

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_max_contexts_before_recycle",
        1,
    )
    monkeypatch.setattr(
        "patchright.async_api.async_playwright", lambda: FakePlaywrightManager()
    )

    async with asyncio.timeout(1):
        async with runtime.page():
            pass

    assert old_events == ["browser_closed", "playwright_stopped"]
    assert new_events == ["launched", "new_context", "context_closed"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_does_not_recycle_with_active_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    events: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            del script
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            events.append("context_closed")

    class FakeBrowser:
        def is_connected(self) -> bool:
            return True

        async def new_context(self, **kwargs):
            del kwargs
            events.append("new_context")
            return FakeContext()

        async def close(self) -> None:
            events.append("browser_closed")

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=2)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()
    runtime._browser_launched_at = acquisition_browser_pool.time.monotonic()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_max_contexts_before_recycle",
        1,
    )

    async def _hold_page() -> None:
        async with runtime.page():
            entered.set()
            await release.wait()

    first = asyncio.create_task(_hold_page())
    await entered.wait()
    runtime._total_contexts_created = 1
    async with runtime.page():
        await asyncio.sleep(0)
    release.set()
    _ = await first

    assert "browser_closed" not in events


@pytest.mark.asyncio
@pytest.mark.component
async def test_acquisition_shared_browser_runtime_recycles_after_driver_closed_on_new_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_events: list[str] = []
    new_events: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            new_events.append("context_closed")

    class DeadBrowser:
        def is_connected(self) -> bool:
            return True

        async def new_context(self, **kwargs):
            del kwargs
            raise Exception(
                "Browser.new_context: Connection closed while reading from the driver"
            )

        async def close(self) -> None:
            old_events.append("browser_closed")

    class FreshBrowser:
        def is_connected(self) -> bool:
            return True

        async def new_context(self, **kwargs):
            del kwargs
            new_events.append("new_context")
            return FakeContext()

        async def close(self) -> None:
            new_events.append("browser_closed")

    class FakePlaywrightInstance:
        def __init__(self) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)

        async def _launch(self, **kwargs):
            del kwargs
            new_events.append("launched")
            return FreshBrowser()

        async def stop(self) -> None:
            old_events.append("playwright_stopped")

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance()

    class OldPlaywright:
        async def stop(self) -> None:
            old_events.append("playwright_stopped")

    runtime = acquisition_browser_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = DeadBrowser()
    runtime._playwright = OldPlaywright()
    runtime._browser_launched_at = 1.0

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        acquisition_browser_pool,
        "_patchright_async_playwright_factory",
        lambda: lambda: FakePlaywrightManager(),
    )

    async with runtime.page():
        pass

    assert old_events == ["browser_closed", "playwright_stopped"]
    assert new_events == ["launched", "new_context", "context_closed"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_bounds_hung_browser_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocker = asyncio.Event()
    events: list[str] = []

    class FakePlaywrightInstance:
        def __init__(self) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)

        async def _launch(self, **kwargs):
            del kwargs
            await blocker.wait()

        async def stop(self) -> None:
            events.append("playwright_stopped")

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance()

    runtime = acquisition_browser_runtime.SharedBrowserRuntime(max_contexts=1)
    monkeypatch.setattr(
        acquisition_browser_pool,
        "_patchright_async_playwright_factory",
        lambda: lambda: FakePlaywrightManager(),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_launch_timeout_seconds",
        0.05,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_close_timeout_ms",
        50,
    )

    with pytest.raises(asyncio.TimeoutError, match="Timed out launching browser"):
        async with asyncio.timeout(0.5):
            await runtime.ensure()

    assert events == ["playwright_stopped"]
    assert runtime._browser is None
    assert runtime._playwright is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_bounds_hung_new_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocker = asyncio.Event()

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            await blocker.wait()

    runtime = acquisition_browser_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_context_timeout_ms",
        50,
    )

    with pytest.raises(asyncio.TimeoutError, match="Timed out opening browser context"):
        async with asyncio.timeout(0.5):
            async with runtime.page(allow_storage_state=False):
                pass

    assert runtime._active_contexts == 0


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_bounds_hung_new_page_and_closes_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocker = asyncio.Event()
    closed: list[str] = []

    class FakeContext:
        async def new_page(self):
            await blocker.wait()

        async def close(self) -> None:
            closed.append("context_closed")

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    runtime = acquisition_browser_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_new_page_timeout_ms",
        50,
    )

    with pytest.raises(asyncio.TimeoutError, match="Timed out opening browser page"):
        async with asyncio.timeout(0.5):
            async with runtime.page(allow_storage_state=False):
                pass

    assert closed == ["context_closed"]
    assert runtime._active_contexts == 0


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_keeps_capacity_until_timed_out_close_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_close = asyncio.Event()

    class FakeContext:
        async def new_page(self):
            return object()

        async def close(self) -> None:
            await release_close.wait()

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    async def _skip_storage(*args, **kwargs) -> None:
        pass

    runtime = acquisition_browser_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()
    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        acquisition_browser_pool_page,
        "persist_context_storage_state",
        _skip_storage,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_close_timeout_ms",
        1,
    )

    async with runtime.page(allow_storage_state=False):
        pass

    assert runtime._active_contexts == 1
    assert runtime._semaphore.locked()
    release_close.set()
    await browser_background_tasks.drain_browser_background_tasks()
    assert runtime._active_contexts == 0
    assert not runtime._semaphore.locked()


@pytest.mark.asyncio
@pytest.mark.component
async def test_await_without_cancelling_returns_false_when_awaitable_fails() -> None:
    async def _fail() -> None:
        raise RuntimeError("close failed")

    assert (
        await browser_background_tasks.await_without_cancelling(
            _fail(),
            timeout_seconds=1,
        )
        is False
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_await_without_cancelling_registers_task_when_caller_is_cancelled() -> (
    None
):
    release = asyncio.Event()

    async def _wait() -> None:
        await release.wait()

    caller = asyncio.create_task(
        browser_background_tasks.await_without_cancelling(
            _wait(),
            timeout_seconds=10,
        )
    )
    await asyncio.sleep(0)
    caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        _ = await caller

    assert browser_background_tasks._eviction_cleanup_tasks
    release.set()
    await browser_background_tasks.drain_browser_background_tasks()
    assert not browser_background_tasks._eviction_cleanup_tasks


@pytest.mark.component
def test_browser_runtime_snapshot_reports_runtime_capacity_without_host_cache() -> None:
    snapshot = crawl_fetch_runtime.browser_runtime_snapshot()

    assert "preferred_hosts" not in snapshot
    assert "capacity" in snapshot


@pytest.mark.component
def test_real_chrome_candidate_paths_include_common_platform_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_real_chrome_executable_path",
        "",
    )

    candidates = acquisition_browser_runtime._real_chrome_candidate_paths()

    assert "/usr/bin/google-chrome" in candidates
    assert "/opt/google/chrome/chrome" in candidates
    assert "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" in candidates


@pytest.mark.component
def test_real_chrome_browser_available_requires_enabled_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_real_chrome_enabled",
        False,
    )

    assert acquisition_browser_runtime.real_chrome_browser_available() is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_get_browser_runtime_evicts_idle_proxied_runtime_when_pool_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str | None, str]] = []
    closed: list[tuple[str | None, str]] = []

    class FakeRuntime:
        def __init__(
            self,
            *,
            max_contexts: int,
            launch_proxy: str | None = None,
            browser_engine: str = "chromium",
        ) -> None:
            del max_contexts
            self.launch_proxy = launch_proxy
            self.browser_engine = browser_engine
            self.browser_binary = browser_engine
            self._last_used_at = 0.0
            created.append((launch_proxy, browser_engine))

        def touch(self) -> None:
            self._last_used_at += 1

        def idle_seconds(self) -> float:
            return 999.0

        def bridge_used(self) -> bool:
            return False

        def eviction_key(self) -> tuple[int, float]:
            return (0, self._last_used_at)

        def snapshot(self) -> dict[str, int | bool | str]:
            return {
                "active": 0,
                "queued": 0,
                "ready": False,
                "browser_engine": self.browser_engine,
            }

        async def close(self) -> None:
            closed.append((self.launch_proxy, self.browser_engine))

    monkeypatch.setattr(
        acquisition_browser_pool,
        "SharedBrowserRuntime",
        FakeRuntime,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_runtime_pool_max_entries",
        1,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_runtime_pool_idle_ttl_seconds",
        0,
    )
    await acquisition_browser_runtime.shutdown_browser_runtime()
    first = await acquisition_browser_runtime.get_browser_runtime(
        proxy="http://proxy-one",
        browser_engine="chromium",
    )
    second = await acquisition_browser_runtime.get_browser_runtime(
        proxy="http://proxy-two",
        browser_engine="real_chrome",
    )

    assert first is not second
    assert created == [
        ("http://proxy-one", "chromium"),
        ("http://proxy-two", "real_chrome"),
    ]
    await browser_background_tasks.drain_browser_background_tasks()
    assert closed == [("http://proxy-one", "chromium")]
    await acquisition_browser_runtime.shutdown_browser_runtime()


@pytest.mark.asyncio
@pytest.mark.component
async def test_get_browser_runtime_uses_context_capacity_for_runtime_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        acquisition_browser_pool.crawler_runtime_settings,
        "browser_runtime_context_capacity",
        10,
    )
    monkeypatch.setattr(
        acquisition_browser_pool.crawler_runtime_settings,
        "browser_runtime_pool_max_entries",
        1,
    )

    await acquisition_browser_runtime.shutdown_browser_runtime()
    runtime = await acquisition_browser_runtime.get_browser_runtime(
        browser_engine="chromium"
    )

    try:
        snapshot = runtime.snapshot()
        assert isinstance(runtime, acquisition_browser_pool.SharedBrowserRuntime)
        assert snapshot["capacity"] == 10
        assert snapshot["max_size"] == 10
        assert "browser_instances" not in snapshot
        assert "contexts_per_instance" not in snapshot
    finally:
        await acquisition_browser_runtime.shutdown_browser_runtime()


@pytest.mark.asyncio
@pytest.mark.component
async def test_get_browser_runtime_evicts_idle_direct_runtime_when_pool_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str | None, str]] = []
    closed: list[tuple[str | None, str]] = []

    class FakeRuntime:
        def __init__(
            self,
            *,
            max_contexts: int,
            launch_proxy: str | None = None,
            browser_engine: str = "chromium",
        ) -> None:
            del max_contexts
            self.launch_proxy = launch_proxy
            self.browser_engine = browser_engine
            self.browser_binary = browser_engine
            self._last_used_at = 0.0
            created.append((launch_proxy, browser_engine))

        def touch(self) -> None:
            self._last_used_at += 1

        def idle_seconds(self) -> float:
            return 999.0

        def eviction_key(self) -> tuple[int, float]:
            return (0, self._last_used_at)

        def snapshot(self) -> dict[str, int | bool | str]:
            return {
                "active": 0,
                "queued": 0,
                "ready": False,
                "browser_engine": self.browser_engine,
            }

        async def close(self) -> None:
            closed.append((self.launch_proxy, self.browser_engine))

    monkeypatch.setattr(
        acquisition_browser_pool,
        "SharedBrowserRuntime",
        FakeRuntime,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_runtime_pool_max_entries",
        1,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_runtime_pool_idle_ttl_seconds",
        0,
    )
    await acquisition_browser_runtime.shutdown_browser_runtime()
    first = await acquisition_browser_runtime.get_browser_runtime(
        browser_engine="chromium"
    )
    second = await acquisition_browser_runtime.get_browser_runtime(
        browser_engine="real_chrome"
    )

    assert first is not second
    assert created == [(None, "chromium"), (None, "real_chrome")]
    await browser_background_tasks.drain_browser_background_tasks()
    assert closed == [(None, "chromium")]
    await acquisition_browser_runtime.shutdown_browser_runtime()


@pytest.mark.asyncio
@pytest.mark.component
async def test_browser_pool_skip_evicts_runtime_reused_after_candidate_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []

    class FakeRuntime:
        def __init__(self, name: str, *, last_used: float, idle_seconds: float) -> None:
            self.name = name
            self._last_used_at = last_used
            self._idle_seconds = idle_seconds

        def touch(self) -> None:
            self._last_used_at += 100

        def idle_seconds(self) -> float:
            return self._idle_seconds

        def eviction_key(self) -> tuple[int, float]:
            if self.name == "second":
                first.touch()
            return (0, self._last_used_at)

        async def close(self) -> None:
            closed.append(self.name)

    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_runtime_pool_max_entries",
        1,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_runtime_pool_idle_ttl_seconds",
        1,
    )

    await acquisition_browser_runtime.shutdown_browser_runtime()
    first = FakeRuntime("first", last_used=1.0, idle_seconds=999.0)
    second = FakeRuntime("second", last_used=2.0, idle_seconds=0.0)
    acquisition_browser_pool._BROWSER_POOL.direct["chromium"] = first
    acquisition_browser_pool._BROWSER_POOL.direct["real_chrome"] = second

    try:
        async with acquisition_browser_pool._BROWSER_POOL.lock:
            to_close = acquisition_browser_pool._evict_idle_browser_runtimes_locked()
        for r in to_close:
            await r.close()

        assert closed == ["second"]
        assert acquisition_browser_pool._BROWSER_POOL.direct["chromium"] is first
    finally:
        await acquisition_browser_runtime.shutdown_browser_runtime()


@pytest.mark.component
def test_browser_launch_args_exclude_detectable_flags() -> None:
    assert (
        "--disable-component-update" not in crawler_runtime_settings.browser_launch_args
    )
    assert (
        "--disable-blink-features=AutomationControlled"
        not in crawler_runtime_settings.browser_launch_args
    )
