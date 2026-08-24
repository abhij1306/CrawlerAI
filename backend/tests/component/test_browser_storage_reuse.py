"""test_browser_context cases split by public behavior."""

from __future__ import annotations

from tests.component.browser_context_test_support import (
    _context_spec,
    acquisition_browser_pool,
    acquisition_browser_runtime,
    asyncio,
    browser_background_tasks,
    browser_storage_state,
    cookie_store,
    crawl_fetch_runtime,
    pytest,
)


@pytest.fixture(autouse=True)
def _stub_storage_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _owner(run_id: int | None) -> int | None:
        return 1 if run_id is not None else None

    monkeypatch.setattr(cookie_store, "user_id_for_run", _owner)


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_reuses_run_storage_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []
    persisted_states: list[tuple[int, dict[str, object]]] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            return {
                "cookies": [
                    {
                        "name": "dd_session",
                        "value": "next-cookie",
                        "domain": ".etsy.com",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": "https://www.etsy.com",
                        "localStorage": [
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            }

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )

    async def _fake_load_storage_state_for_run(run_id: int | None, **_kwargs):
        del _kwargs
        assert run_id == 77
        return {
            "cookies": [
                {
                    "name": "dd_session",
                    "value": "existing-cookie",
                    "domain": ".etsy.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://www.etsy.com",
                    "localStorage": [
                        {"name": "consent", "value": "accepted"},
                    ],
                }
            ],
        }

    async def _fake_persist_storage_state_for_run(
        run_id: int | None,
        storage_state: dict[str, object],
        **_kwargs,
    ) -> None:
        del _kwargs
        assert run_id == 77
        persisted_states.append((int(run_id), dict(storage_state)))

    monkeypatch.setattr(
        cookie_store,
        "load_storage_state_for_run",
        _fake_load_storage_state_for_run,
    )
    monkeypatch.setattr(
        cookie_store,
        "persist_storage_state_for_run",
        _fake_persist_storage_state_for_run,
    )

    async with runtime.page(run_id=77):
        pass

    assert captured_kwargs == [
        {
            "storage_state": {
                "cookies": [
                    {
                        "name": "dd_session",
                        "value": "existing-cookie",
                        "domain": ".etsy.com",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": "https://www.etsy.com",
                        "localStorage": [
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            }
        }
    ]
    assert persisted_states == [
        (
            77,
            {
                "cookies": [
                    {
                        "name": "dd_session",
                        "value": "next-cookie",
                        "domain": ".etsy.com",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": "https://www.etsy.com",
                        "localStorage": [
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            },
        )
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_skips_storage_state_reuse_when_disallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            return {"cookies": [], "origins": []}

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )

    async def _boom(*args, **kwargs):
        raise AssertionError(f"storage state should not load: {args} {kwargs}")

    monkeypatch.setattr(
        cookie_store,
        "load_storage_state_for_run",
        _boom,
    )
    monkeypatch.setattr(
        cookie_store,
        "load_storage_state_for_domain",
        _boom,
    )

    async with runtime.page(
        run_id=77,
        domain="example.com",
        allow_storage_state=False,
    ):
        pass

    assert captured_kwargs == [{}]


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_skips_domain_storage_for_proxied_runtime_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []
    domain_load_calls: list[str | None] = []
    domain_persist_calls: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            return {"cookies": [], "origins": []}

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(
        max_contexts=1,
        launch_proxy="http://proxy-one",
    )
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )

    async def _load_run(run_id: int | None, **_kwargs):
        del run_id, _kwargs
        return None

    async def _load_domain(domain: str | None, **_kwargs):
        del _kwargs
        domain_load_calls.append(domain)
        return {"cookies": [], "origins": []}

    async def _persist_domain(
        domain: str, storage_state: dict[str, object], **_kwargs
    ) -> None:
        del storage_state, _kwargs
        domain_persist_calls.append(domain)

    monkeypatch.setattr(
        cookie_store,
        "load_storage_state_for_run",
        _load_run,
    )
    monkeypatch.setattr(
        cookie_store,
        "load_storage_state_for_domain",
        _load_domain,
    )
    monkeypatch.setattr(
        cookie_store,
        "persist_storage_state_for_domain",
        _persist_domain,
    )

    async with runtime.page(run_id=77, domain="example.com"):
        pass

    assert captured_kwargs == [{}]
    assert domain_load_calls == []
    assert domain_persist_calls == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_suppresses_storage_state_persist_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            return {"cookies": [], "origins": []}

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

    async def _boom(*args, **kwargs) -> None:
        del args, kwargs
        raise RuntimeError("boom")

    monkeypatch.setattr(
        cookie_store,
        "persist_storage_state_for_run",
        _boom,
    )

    async def _no_state(run_id: int | None, **_kwargs):
        del run_id, _kwargs
        return None

    monkeypatch.setattr(
        cookie_store,
        "load_storage_state_for_run",
        _no_state,
    )

    with caplog.at_level("ERROR", logger=acquisition_browser_runtime.logger.name):
        async with runtime.page(run_id=77):
            pass

    assert any(
        "Failed to persist browser storage state for run_id=77" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_bounds_hung_context_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocker = asyncio.Event()

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            await blocker.wait()
            return {"cookies": [], "origins": []}

        async def close(self) -> None:
            await blocker.wait()

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
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_context_timeout_ms",
        50,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_close_timeout_ms",
        50,
    )

    with caplog.at_level("WARNING", logger=acquisition_browser_runtime.logger.name):
        async with asyncio.timeout(0.5):
            async with runtime.page(
                run_id=77,
                domain="example.com",
                allow_storage_state=False,
            ):
                pass

    assert any(
        "Timed out capturing browser storage state" in record.message
        for record in caplog.records
    )
    assert any(
        (
            "Timed out closing browser context" in record.message
            or "Browser context close was cancelled" in record.message
        )
        for record in caplog.records
    )
    await browser_background_tasks.drain_browser_background_tasks()
    assert runtime._active_contexts == 0


@pytest.mark.asyncio
@pytest.mark.component
async def test_context_slot_released_when_cancelled_during_recycle_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    wait_started = asyncio.Event()
    release_wait = asyncio.Event()

    async def _block_recycle_wait(timeout_seconds: float) -> bool:
        del timeout_seconds
        wait_started.set()
        await release_wait.wait()
        return False

    monkeypatch.setattr(
        runtime,
        "_yield_slot_until_recycle_window",
        _block_recycle_wait,
    )

    task = asyncio.create_task(runtime._acquire_context_slot(phase_timings_ms={}))
    await asyncio.wait_for(wait_started.wait(), timeout=1.0)
    assert runtime._semaphore.locked()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        _ = await task

    assert not runtime._semaphore.locked()
    assert runtime.snapshot()["queued"] == 0


@pytest.mark.asyncio
@pytest.mark.component
async def test_runtime_page_releases_slot_when_cancelled_during_browser_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    ensure_started = asyncio.Event()
    release_ensure = asyncio.Event()

    async def _block_ensure(*, phase_timings_ms: dict[str, int] | None) -> None:
        del phase_timings_ms
        ensure_started.set()
        await release_ensure.wait()

    monkeypatch.setattr(runtime, "_ensure_with_timing", _block_ensure)

    async def _open_page() -> None:
        async with runtime.page(allow_storage_state=False):
            pass

    task = asyncio.create_task(_open_page())
    await asyncio.wait_for(ensure_started.wait(), timeout=1.0)
    assert runtime._semaphore.locked()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        _ = await task

    assert not runtime._semaphore.locked()
    assert runtime.snapshot()["active"] == 0
    assert runtime.snapshot()["queued"] == 0


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_releases_pool_slot_when_cleanup_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_started = asyncio.Event()
    close_release = asyncio.Event()
    close_calls = 0

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
            nonlocal close_calls
            close_calls += 1
            if close_calls == 1:
                close_started.set()
                await close_release.wait()

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

    async def _use_page() -> None:
        async with runtime.page(allow_storage_state=False):
            await asyncio.sleep(0)

    task = asyncio.create_task(_use_page())
    await asyncio.wait_for(close_started.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        _ = await task

    async def _acquire_again() -> None:
        async with runtime.page(allow_storage_state=False):
            await asyncio.sleep(0)

    assert runtime._semaphore.locked()
    close_release.set()
    await browser_background_tasks.drain_browser_background_tasks()
    await asyncio.wait_for(_acquire_again(), timeout=1.0)
    assert close_calls == 2


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_close_bounds_without_cancelling_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocker = asyncio.Event()
    cancelled: list[str] = []

    class FakeBrowser:
        async def close(self) -> None:
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                cancelled.append("browser")
                raise

    class FakePlaywright:
        async def stop(self) -> None:
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                cancelled.append("playwright")
                raise

    class FakeBridge:
        async def close(self) -> None:
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                cancelled.append("bridge")
                raise

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = FakePlaywright()
    runtime._socks5_auth_bridge = FakeBridge()

    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_close_timeout_ms",
        50,
    )

    with caplog.at_level("WARNING", logger=acquisition_browser_runtime.logger.name):
        async with asyncio.timeout(0.5):
            await runtime.close()

    assert runtime._browser is None
    assert runtime._playwright is None
    assert runtime._socks5_auth_bridge is None
    assert any(
        "Timed out closing browser runtime" in record.message
        for record in caplog.records
    )
    assert any(
        "Timed out stopping playwright" in record.message for record in caplog.records
    )
    assert any(
        "Timed out closing SOCKS5 auth bridge" in record.message
        for record in caplog.records
    )
    assert cancelled == []
    blocker.set()
    await browser_background_tasks.drain_browser_background_tasks()
    assert cancelled == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_context_storage_state_normalizes_domain_before_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeContext:
        async def storage_state(self) -> dict[str, object]:
            return {"cookies": [], "origins": []}

    persisted_domains: list[str] = []

    async def _persist_domain(
        domain: str, storage_state: dict[str, object], **_kwargs
    ) -> None:
        del storage_state, _kwargs
        persisted_domains.append(domain)

    monkeypatch.setattr(
        cookie_store,
        "persist_storage_state_for_domain",
        _persist_domain,
    )

    await browser_storage_state.persist_context_storage_state(
        FakeContext(),
        run_id=None,
        domain="  example.com  ",
    )

    assert persisted_domains == ["example.com"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_context_storage_state_skips_domain_persist_when_disallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeContext:
        async def storage_state(self) -> dict[str, object]:
            return {
                "cookies": [
                    {
                        "name": "session",
                        "value": "abc",
                        "domain": ".example.com",
                        "path": "/",
                    }
                ],
                "origins": [],
            }

    persisted_domains: list[str] = []

    async def _persist_domain(
        domain: str, storage_state: dict[str, object], **_kwargs
    ) -> None:
        del storage_state, _kwargs
        persisted_domains.append(domain)

    monkeypatch.setattr(
        cookie_store,
        "persist_storage_state_for_domain",
        _persist_domain,
    )

    await browser_storage_state.persist_context_storage_state(
        FakeContext(),
        run_id=None,
        domain="example.com",
        persist_domain_storage_state=False,
    )

    assert persisted_domains == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_context_storage_state_skips_run_persist_when_disallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeContext:
        async def storage_state(self) -> dict[str, object]:
            return {
                "cookies": [
                    {
                        "name": "session",
                        "value": "abc",
                        "domain": ".example.com",
                        "path": "/",
                    }
                ],
                "origins": [],
            }

    persisted_run_ids: list[int] = []

    async def _persist_run(
        run_id: int | None, storage_state: dict[str, object], **_kwargs
    ) -> None:
        del storage_state, _kwargs
        persisted_run_ids.append(int(run_id or 0))

    monkeypatch.setattr(
        cookie_store,
        "persist_storage_state_for_run",
        _persist_run,
    )

    await browser_storage_state.persist_context_storage_state(
        FakeContext(),
        run_id=77,
        domain=None,
        persist_run_storage_state=False,
    )

    assert persisted_run_ids == []
