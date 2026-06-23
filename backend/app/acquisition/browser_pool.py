from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from app.acquisition.browser_background_tasks import (
    await_without_cancelling,
    drain_browser_background_tasks,
    register_eviction_cleanup_task,
)
from app.acquisition.browser_diagnostics import (
    CHROMIUM_BROWSER_ENGINE as _CHROMIUM_BROWSER_ENGINE,
    PATCHRIGHT_BROWSER_ENGINE as _PATCHRIGHT_BROWSER_ENGINE,
    REAL_CHROME_BROWSER_ENGINE as _REAL_CHROME_BROWSER_ENGINE,
    browser_failure_kind as _browser_failure_kind,
    browser_profile_diagnostics as _browser_profile_diagnostics,
    launch_headless_for_engine as _launch_headless_for_engine,
    normalize_browser_engine as _normalize_browser_engine,
    use_native_real_chrome_context as _use_native_real_chrome_context,
)
from app.acquisition.browser_identity import (
    PlaywrightContextSpec,
    clear_browser_identity_cache,
)
from app.acquisition.browser_identity import build_playwright_context_spec
from app.acquisition.browser_proxy_bridge import Socks5AuthBridge
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
    REAL_CHROME_IGNORE_DEFAULT_ARGS,
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

    def _should_recycle_browser(self) -> bool:
        if self._browser is None:
            return False
        if not getattr(self._browser, "is_connected", lambda: True)():
            return True
        if self._active_contexts > 0:
            return False
        if self._context_recycle_threshold_reached():
            return True
        max_lifetime = int(crawler_runtime_settings.browser_max_lifetime_seconds)
        if max_lifetime > 0 and self._browser_launched_at > 0:
            if time.monotonic() - self._browser_launched_at >= max_lifetime:
                return True
        return False

    def _context_recycle_threshold_reached(self) -> bool:
        max_contexts = int(crawler_runtime_settings.browser_max_contexts_before_recycle)
        return max_contexts > 0 and self._total_contexts_created >= max_contexts

    async def _yield_slot_until_recycle_window(self, timeout_seconds: float) -> bool:
        if (
            self._browser is None
            or not self._context_recycle_threshold_reached()
            or self._active_contexts > 0
        ):
            return False
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        self._semaphore.release()
        while self._active_contexts > 0 and self._context_recycle_threshold_reached():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    "Timed out waiting for browser context slot "
                    f"after {timeout_seconds:.1f}s"
                )
            await asyncio.sleep(min(0.05, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError(
                "Timed out waiting for browser context slot "
                f"after {timeout_seconds:.1f}s"
            )
        await asyncio.wait_for(self._semaphore.acquire(), timeout=remaining)
        return True

    async def _ensure(self) -> None:
        if self._browser is not None and not self._should_recycle_browser():
            return
        async with self._lock:
            if self._should_recycle_browser():
                logger.info(
                    "Recycling browser instance (contexts=%d, lifetime=%.0fs)",
                    self._total_contexts_created,
                    time.monotonic() - self._browser_launched_at
                    if self._browser_launched_at
                    else 0,
                )
                await self._close_locked()
            if self._browser is not None:
                return
            try:
                async_playwright = _async_playwright_manager_for_engine(
                    self.browser_engine
                )
                self._playwright = await _wait_for_browser_step(
                    async_playwright().start(),
                    timeout_seconds=_browser_launch_timeout_seconds(),
                    message="Timed out launching browser driver",
                )
                launch_kwargs = await self._browser_launch_kwargs()
                self._browser = await _wait_for_browser_step(
                    self._playwright.chromium.launch(**launch_kwargs),
                    timeout_seconds=_browser_launch_timeout_seconds(),
                    message="Timed out launching browser",
                )
                self._browser_launched_at = time.monotonic()
                self._total_contexts_created = 0
            except Exception:
                await self._close_locked()
                raise

    async def ensure(self) -> None:
        """Public browser warm-up API."""
        await self._ensure()

    async def _recycle_after_driver_disconnect(self) -> None:
        async with self._lock:
            await self._close_locked()
        await self.ensure()

    async def _browser_launch_kwargs(self) -> dict[str, Any]:
        launch_args = [
            str(value).strip()
            for value in crawler_runtime_settings.browser_launch_args or ()
            if str(value).strip()
        ]
        launch_headless = _launch_headless_for_engine(self.browser_engine)
        if (
            launch_headless
            and bool(crawler_runtime_settings.browser_use_new_headless)
            and "--headless=new" not in launch_args
        ):
            launch_args.append("--headless=new")
            launch_headless = False
        launch_kwargs: dict[str, Any] = {"headless": launch_headless}
        if launch_args:
            launch_kwargs["args"] = launch_args
        self._add_real_chrome_launch_kwargs(launch_kwargs)
        launch_proxy_config = await self._launch_proxy_config_for_browser()
        if launch_proxy_config is not None:
            launch_kwargs["proxy"] = launch_proxy_config
        return launch_kwargs

    def _add_real_chrome_launch_kwargs(self, launch_kwargs: dict[str, Any]) -> None:
        if self.browser_engine != _REAL_CHROME_BROWSER_ENGINE:
            return
        if not self.executable_path:
            raise RuntimeError(
                "Real Chrome executable is not available for browser runtime"
            )
        launch_kwargs["executable_path"] = self.executable_path
        ignore_default_args = [
            str(arg).strip()
            for arg in (REAL_CHROME_IGNORE_DEFAULT_ARGS or ())
            if str(arg).strip()
        ]
        if ignore_default_args:
            launch_kwargs["ignore_default_args"] = ignore_default_args

    async def _open_context_page(
        self,
        *,
        context_options: dict[str, Any],
    ) -> tuple[BrowserContext, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            if self._browser is None:
                raise RuntimeError("Browser runtime failed to initialize")
            context: BrowserContext | None = None
            try:
                context = await _wait_for_browser_step(
                    self._browser.new_context(**cast(Any, context_options)),
                    timeout_seconds=_browser_context_timeout_seconds(),
                    message="Timed out opening browser context",
                )
                self._total_contexts_created += 1
                page = await _wait_for_browser_step(
                    context.new_page(),
                    timeout_seconds=_browser_new_page_timeout_seconds(),
                    message="Timed out opening browser page",
                )
                return context, page
            except Exception as exc:
                last_error = exc
                if context is not None:
                    await _close_browser_context_safely(context)
                if attempt >= 1 or _browser_failure_kind(exc) not in {
                    "browser_driver_closed",
                    "page_closed",
                }:
                    raise
                logger.warning(
                    "Browser runtime disconnected during context bootstrap; recycling runtime"
                )
                await self._recycle_after_driver_disconnect()
        if last_error is not None:
            raise last_error
        raise RuntimeError("Browser runtime failed to create page context")

    async def _launch_proxy_config_for_browser(self) -> dict[str, str] | None:
        if self.launch_proxy_config is None:
            return None
        if self._authenticated_socks5_proxy is None:
            return dict(self.launch_proxy_config)
        if self._socks5_auth_bridge is None:
            bridge_cls = Socks5AuthBridge
            self._socks5_auth_bridge = bridge_cls(self._authenticated_socks5_proxy)
        bridge_proxy = await self._socks5_auth_bridge.start()
        bridge_proxy_config = _build_browser_proxy_config(bridge_proxy)
        if bridge_proxy_config is None:
            raise RuntimeError("SOCKS5 auth bridge failed to expose a browser proxy")
        return bridge_proxy_config

    async def _acquire_context_slot(
        self,
        *,
        phase_timings_ms: dict[str, int] | None,
    ) -> None:
        self._update_queue_count(1)
        slot_timeout_seconds = _browser_context_slot_timeout_seconds()
        slot_wait_started_at = time.perf_counter()
        slot_deadline = time.monotonic() + slot_timeout_seconds
        slot_acquired = False
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=slot_timeout_seconds,
            )
            slot_acquired = True
            await self._yield_slot_until_recycle_window(
                max(0.0, slot_deadline - time.monotonic())
            )
            _record_timing(
                phase_timings_ms,
                "context_slot_wait_ms",
                slot_wait_started_at,
            )
        except asyncio.TimeoutError as exc:
            _record_timing(
                phase_timings_ms,
                "context_slot_wait_ms",
                slot_wait_started_at,
            )
            raise asyncio.TimeoutError(
                "Timed out waiting for browser context slot "
                f"after {slot_timeout_seconds:.1f}s"
            ) from exc
        except BaseException:
            if slot_acquired:
                self._semaphore.release()
            raise
        finally:
            self._update_queue_count(-1)

    async def _ensure_with_timing(
        self,
        *,
        phase_timings_ms: dict[str, int] | None,
    ) -> None:
        should_time_browser_start = (
            self._browser is None or self._should_recycle_browser()
        )
        browser_start_started_at = time.perf_counter()
        await self._ensure()
        if should_time_browser_start:
            _record_timing(
                phase_timings_ms,
                "browser_start_ms",
                browser_start_started_at,
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
        self._update_active_contexts(-1)
        self._semaphore.release()

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        components = (
            ("closing browser runtime", self._browser, "close"),
            ("stopping playwright", self._playwright, "stop"),
            ("closing SOCKS5 auth bridge", self._socks5_auth_bridge, "close"),
        )
        for label, component, close_method in components:
            if component is None:
                continue
            try:
                closed = await await_without_cancelling(
                    getattr(component, close_method)(),
                    timeout_seconds=_browser_close_timeout_seconds(),
                )
                if not closed:
                    logger.warning(
                        "Timed out %s after %.1fs",
                        label,
                        _browser_close_timeout_seconds(),
                    )
            except Exception:
                logger.debug("Failed while %s", label, exc_info=True)
        self._browser = None
        self._playwright = None
        self._socks5_auth_bridge = None
        self._browser_launched_at = 0.0

    def _update_active_contexts(self, delta: int) -> None:
        self._active_contexts = max(0, self._active_contexts + delta)

    def _update_queue_count(self, delta: int) -> None:
        self._queued_count = max(0, self._queued_count + delta)

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
