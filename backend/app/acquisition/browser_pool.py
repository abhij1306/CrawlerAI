from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.acquisition import browser_context_lifecycle, browser_runtime_lifecycle
from app.acquisition.browser_background_tasks import (
    await_without_cancelling,
    drain_browser_background_tasks,
    register_eviction_cleanup_task,
)
from app.acquisition.browser_diagnostics import (
    CHROMIUM_BROWSER_ENGINE as _CHROMIUM_BROWSER_ENGINE,
    PATCHRIGHT_BROWSER_ENGINE as _PATCHRIGHT_BROWSER_ENGINE,
    REAL_CHROME_BROWSER_ENGINE as _REAL_CHROME_BROWSER_ENGINE,
    browser_profile_diagnostics as _browser_profile_diagnostics,
    normalize_browser_engine as _normalize_browser_engine,
    use_native_real_chrome_context as _use_native_real_chrome_context,
)
from app.acquisition.browser_identity import (
    PlaywrightContextSpec,
    clear_browser_identity_cache,
)
from app.acquisition.browser_identity import build_playwright_context_spec
from app.acquisition.browser_proxy_bridge import (
    Socks5AuthBridge as Socks5AuthBridge,
)
from app.acquisition.browser_page_helpers import object_int as _int_or_zero
from app.acquisition.browser_pool_eviction import (
    evict_idle_browser_runtimes_locked,
)
from app.acquisition.browser_pool_snapshot import (
    browser_runtime_snapshot_from_runtimes,
)
from app.acquisition.browser_pool_page import runtime_page
from app.acquisition.browser_proxy_bridge import (
    parse_socks5_upstream_proxy,
)
from app.acquisition.browser_proxy_config import (
    build_browser_proxy_config as _build_browser_proxy_config,
    normalized_proxy_value as _normalized_proxy_value,
)
from app.core.config.browser_fingerprint_profiles import (
    NATIVE_REAL_CHROME_CONTEXT_OPTIONS,
    REAL_CHROME_IGNORE_DEFAULT_ARGS as REAL_CHROME_IGNORE_DEFAULT_ARGS,
)
from app.core.config.runtime_settings import crawler_runtime_settings

if TYPE_CHECKING:
    from patchright.async_api import Browser, BrowserContext, Playwright

logger = logging.getLogger(__name__)


class BrowserRuntimePool:
    def __init__(self) -> None:
        self.direct: dict[str, SharedBrowserRuntime] = {}
        self.proxied: dict[tuple[str, str], SharedBrowserRuntime] = {}
        self.lock = asyncio.Lock()


_BROWSER_POOL = BrowserRuntimePool()


def _patchright_async_playwright_factory():
    from patchright.async_api import async_playwright as patchright_async_playwright

    return patchright_async_playwright


def patchright_browser_available() -> bool:
    if not bool(crawler_runtime_settings.browser_patchright_enabled):
        return False
    try:
        _patchright_async_playwright_factory()
    except Exception:
        logger.debug(
            "Patchright availability probe failed; reporting unavailable",
            exc_info=True,
        )
        return False
    return True


def real_chrome_candidate_paths() -> tuple[str, ...]:
    configured = str(
        crawler_runtime_settings.browser_real_chrome_executable_path or ""
    ).strip()
    if configured:
        return (configured,)
    return (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/opt/google/chrome/chrome",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )


def real_chrome_executable_path() -> str | None:
    if not crawler_runtime_settings.browser_real_chrome_enabled:
        return None
    return next(
        (
            candidate
            for candidate in real_chrome_candidate_paths()
            if Path(candidate).is_file()
        ),
        None,
    )


def real_chrome_browser_available() -> bool:
    return real_chrome_executable_path() is not None


def _resolve_browser_binary(engine: str) -> tuple[str | None, str]:
    normalized_engine = _normalize_browser_engine(engine)
    if normalized_engine in {_PATCHRIGHT_BROWSER_ENGINE, _CHROMIUM_BROWSER_ENGINE}:
        return None, normalized_engine
    executable_path = real_chrome_executable_path()
    if executable_path is None:
        return None, _REAL_CHROME_BROWSER_ENGINE
    return executable_path, executable_path


def _async_playwright_manager_for_engine(engine: str):
    normalized_engine = _normalize_browser_engine(engine)
    try:
        return _patchright_async_playwright_factory()
    except Exception as exc:
        raise RuntimeError(
            f"Patchright package is not available for {normalized_engine} browser runtime"
        ) from exc


class SharedBrowserRuntime:
    def __init__(
        self,
        *,
        max_contexts: int,
        launch_proxy: str | None = None,
        browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
    ) -> None:
        self.max_contexts = max(1, int(max_contexts))
        self.browser_engine = _normalize_browser_engine(browser_engine)
        self.executable_path, self.browser_binary = _resolve_browser_binary(
            self.browser_engine
        )
        self.engine_available = bool(
            (
                self.browser_engine
                in {_PATCHRIGHT_BROWSER_ENGINE, _CHROMIUM_BROWSER_ENGINE}
                and patchright_browser_available()
            )
            or self.executable_path
        )
        self.launch_proxy = _normalized_proxy_value(launch_proxy)
        self.launch_proxy_config = _build_browser_proxy_config(self.launch_proxy)
        self._authenticated_socks5_proxy = parse_socks5_upstream_proxy(
            self.launch_proxy
        )
        self._socks5_auth_bridge: Socks5AuthBridge | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(self.max_contexts)
        self._lock = asyncio.Lock()
        self._active_contexts = 0
        self._queued_count = 0
        self._total_contexts_created = 0
        self._browser_launched_at: float = 0.0
        self._last_used_at: float = time.monotonic()

    async def _yield_slot_until_recycle_window(self, timeout_seconds: float) -> bool:
        return await browser_runtime_lifecycle.yield_slot_until_recycle_window(
            self, timeout_seconds
        )

    async def ensure(self) -> None:
        """Public browser warm-up API."""
        await browser_runtime_lifecycle.ensure_browser_runtime(self)

    async def _open_context_page(
        self,
        *,
        context_options: dict[str, Any],
    ) -> tuple[BrowserContext, Any]:
        return await browser_context_lifecycle.open_context_page(
            self, context_options=context_options
        )

    async def _acquire_context_slot(
        self,
        *,
        phase_timings_ms: dict[str, int] | None,
    ) -> None:
        await browser_context_lifecycle.acquire_context_slot(
            self, phase_timings_ms=phase_timings_ms
        )

    async def _ensure_with_timing(
        self,
        *,
        phase_timings_ms: dict[str, int] | None,
    ) -> None:
        await browser_context_lifecycle.ensure_with_timing(
            self, phase_timings_ms=phase_timings_ms
        )

    def touch(self) -> None:
        self._last_used_at = time.monotonic()

    def idle_seconds(self) -> float:
        return max(0.0, time.monotonic() - self._last_used_at)

    def bridge_used(self) -> bool:
        return self._socks5_auth_bridge is not None

    def eviction_key(self) -> tuple[int, float]:
        snapshot = self.snapshot()
        return (
            _int_or_zero(snapshot.get("active")) + _int_or_zero(snapshot.get("queued")),
            self._last_used_at,
        )

    def _build_context_spec(
        self,
        *,
        run_id: int | None = None,
        locality_profile: dict[str, object] | None = None,
    ) -> PlaywrightContextSpec:
        if _use_native_real_chrome_context(self.browser_engine):
            return PlaywrightContextSpec(
                context_options=dict(NATIVE_REAL_CHROME_CONTEXT_OPTIONS)
            )
        raw_version = str(getattr(self._browser, "version", "") or "")
        major = raw_version.split(".", 1)[0]
        return build_playwright_context_spec(
            run_id=run_id,
            browser_major_version=int(major) if major.isdigit() else None,
            locality_profile=locality_profile,
        )

    def page(
        self,
        *,
        proxy: str | None = None,
        run_id: int | None = None,
        domain: str | None = None,
        locality_profile: dict[str, object] | None = None,
        allow_storage_state: bool = True,
        phase_timings_ms: dict[str, int] | None = None,
    ):
        return runtime_page(
            self,
            proxy=proxy,
            run_id=run_id,
            domain=domain,
            locality_profile=locality_profile,
            allow_storage_state=allow_storage_state,
            phase_timings_ms=phase_timings_ms,
        )

    def _release_context_capacity(self) -> None:
        browser_context_lifecycle.release_context_capacity(self)

    async def close(self) -> None:
        async with self._lock:
            await browser_runtime_lifecycle.close_browser_runtime_locked(self)

    def _update_active_contexts(self, delta: int) -> None:
        browser_context_lifecycle.update_active_contexts(self, delta)

    def snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "ready": self._browser is not None,
            "size": self._active_contexts,
            "max_size": self.max_contexts,
            "active": self._active_contexts,
            "queued": self._queued_count,
            "capacity": self.max_contexts,
            "total_contexts_created": self._total_contexts_created,
            "browser_lifetime_seconds": int(
                time.monotonic() - self._browser_launched_at
            )
            if self._browser_launched_at
            else 0,
            "browser_engine": self.browser_engine,
            **_browser_profile_diagnostics(self.browser_engine),
            "bridge_used": self.bridge_used(),
        }
        return snapshot


def _evict_idle_browser_runtimes_locked() -> list[SharedBrowserRuntime]:
    idle_ttl_seconds = max(
        0, int(crawler_runtime_settings.browser_runtime_pool_idle_ttl_seconds)
    )
    max_entries = max(1, int(crawler_runtime_settings.browser_runtime_pool_max_entries))
    return evict_idle_browser_runtimes_locked(
        direct_pool=_BROWSER_POOL.direct,
        proxied_pool=_BROWSER_POOL.proxied,
        idle_ttl_seconds=idle_ttl_seconds,
        max_entries=max_entries,
    )


async def get_browser_runtime(
    *,
    proxy: str | None = None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
) -> SharedBrowserRuntime:
    normalized_proxy = _normalized_proxy_value(proxy)
    normalized_engine = _normalize_browser_engine(browser_engine)
    pool = _BROWSER_POOL.direct if normalized_proxy is None else _BROWSER_POOL.proxied
    key = (
        normalized_engine
        if normalized_proxy is None
        else (normalized_engine, normalized_proxy)
    )
    runtime = pool.get(key)  # type: ignore[arg-type]
    if runtime is not None:
        runtime.touch()
        return runtime
    runtimes_to_close: list[SharedBrowserRuntime] = []
    async with _BROWSER_POOL.lock:
        runtime = pool.get(key)  # type: ignore[arg-type]
        if runtime is None:
            runtimes_to_close = _evict_idle_browser_runtimes_locked()
            runtime = SharedBrowserRuntime(
                max_contexts=_browser_runtime_context_capacity(),
                launch_proxy=normalized_proxy,
                browser_engine=normalized_engine,
            )
            pool[key] = runtime  # type: ignore[index]
        runtime.touch()
    # Teardown evicted runtimes in background — never block the pool lock on
    # browser/playwright shutdown (can take several seconds each).
    for stale_runtime in runtimes_to_close:
        task = asyncio.create_task(_close_evicted_runtime(stale_runtime))
        register_eviction_cleanup_task(task)
    return runtime


async def _close_evicted_runtime(runtime: SharedBrowserRuntime) -> None:
    try:
        await runtime.close()
    except Exception:
        logger.warning(
            "Background eviction cleanup failed for %s runtime",
            getattr(runtime, "browser_engine", "unknown"),
            exc_info=True,
        )


async def shutdown_browser_runtime() -> None:
    await drain_browser_background_tasks()
    async with _BROWSER_POOL.lock:
        runtimes = [
            runtime
            for runtime in (
                *_BROWSER_POOL.direct.values(),
                *_BROWSER_POOL.proxied.values(),
            )
            if runtime is not None
        ]
        _BROWSER_POOL.direct.clear()
        _BROWSER_POOL.proxied.clear()
    results = await asyncio.gather(
        *(runtime.close() for runtime in runtimes),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            logger.warning(
                "Browser runtime close failed during shutdown: %s",
                result,
            )
    clear_browser_identity_cache()


def shutdown_browser_runtime_sync() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(shutdown_browser_runtime())
        return
    # When called from the event loop thread, waiting synchronously would deadlock
    # the loop, so shutdown remains best-effort and logs completion asynchronously.
    task = loop.create_task(shutdown_browser_runtime())
    task.add_done_callback(_log_shutdown_task_result)


def browser_runtime_snapshot() -> dict[str, int | bool]:
    runtimes = [
        runtime
        for runtime in (
            *_BROWSER_POOL.direct.values(),
            *_BROWSER_POOL.proxied.values(),
        )
        if runtime is not None
    ]
    return browser_runtime_snapshot_from_runtimes(
        runtimes,
        default_capacity=_browser_runtime_context_capacity(),
    )


def _log_shutdown_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.debug("Browser runtime shutdown task was cancelled")
    except Exception:
        logger.exception("Browser runtime shutdown task failed")


def _browser_context_timeout_seconds() -> float:
    return max(0.1, float(crawler_runtime_settings.browser_context_timeout_ms) / 1000)


def _browser_launch_timeout_seconds() -> float:
    return max(0.1, float(crawler_runtime_settings.browser_launch_timeout_seconds))


def _browser_context_slot_timeout_seconds() -> float:
    return max(
        0.1, float(crawler_runtime_settings.browser_context_slot_timeout_seconds)
    )


def _browser_new_page_timeout_seconds() -> float:
    return max(0.1, float(crawler_runtime_settings.browser_new_page_timeout_ms) / 1000)


def _browser_close_timeout_seconds() -> float:
    return max(0.1, float(crawler_runtime_settings.browser_close_timeout_ms) / 1000)


def _browser_runtime_context_capacity() -> int:
    return max(1, int(crawler_runtime_settings.browser_runtime_context_capacity))


async def _wait_for_browser_step(
    awaitable: Any,
    *,
    timeout_seconds: float,
    message: str,
) -> Any:
    bounded_timeout = max(0.1, float(timeout_seconds))
    try:
        return await asyncio.wait_for(awaitable, timeout=bounded_timeout)
    except asyncio.TimeoutError as exc:
        raise asyncio.TimeoutError(f"{message} after {bounded_timeout:.1f}s") from exc


async def _close_browser_context_safely(
    context: Any,
    *,
    on_pending_done: Callable[[asyncio.Task[Any]], None] | None = None,
) -> None:
    try:
        closed = await await_without_cancelling(
            context.close(),
            timeout_seconds=_browser_close_timeout_seconds(),
            on_pending_done=on_pending_done,
        )
        if not closed:
            logger.warning(
                "Timed out closing browser context after %.1fs",
                _browser_close_timeout_seconds(),
            )
    except asyncio.CancelledError:
        logger.warning("Browser context close was cancelled")
        raise
    except Exception:
        logger.debug("Failed to close browser context", exc_info=True)


def _record_timing(
    phase_timings_ms: dict[str, int] | None, key: str, started_at: float
) -> None:
    if phase_timings_ms is not None:
        phase_timings_ms[key] = max(0, int((time.perf_counter() - started_at) * 1000))
