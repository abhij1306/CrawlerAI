from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from app.core.config import settings
from app.services.acquisition import cookie_store
from app.services.acquisition.browser_diagnostics import (
    CHROMIUM_BROWSER_ENGINE as _CHROMIUM_BROWSER_ENGINE,
    PATCHRIGHT_BROWSER_ENGINE as _PATCHRIGHT_BROWSER_ENGINE,
    REAL_CHROME_BROWSER_ENGINE as _REAL_CHROME_BROWSER_ENGINE,
    browser_failure_kind as _browser_failure_kind,
    browser_profile_diagnostics as _browser_profile_diagnostics,
    launch_headless_for_engine as _launch_headless_for_engine,
    normalize_browser_engine as _normalize_browser_engine,
    use_native_real_chrome_context as _use_native_real_chrome_context,
)
from app.services.acquisition.browser_identity import (
    PlaywrightContextSpec,
    build_playwright_context_spec,
    clear_browser_identity_cache,
)
from app.services.acquisition.browser_page_helpers import object_int as _int_or_zero
from app.services.acquisition.browser_proxy_bridge import (
    Socks5AuthBridge,
    parse_socks5_upstream_proxy,
)
from app.services.acquisition.browser_proxy_config import (
    build_browser_proxy_config as _build_browser_proxy_config,
    normalized_proxy_value as _normalized_proxy_value,
)
from app.services.acquisition.browser_storage_state import (
    DOMAIN_STORAGE_PERSIST_ATTR as _DOMAIN_STORAGE_PERSIST_ATTR,
    RUN_STORAGE_PERSIST_ATTR as _RUN_STORAGE_PERSIST_ATTR,
    persist_context_storage_state,
)
from app.services.config.browser_fingerprint_profiles import (
    NATIVE_REAL_CHROME_CONTEXT_OPTIONS,
    REAL_CHROME_IGNORE_DEFAULT_ARGS,
)
from app.services.config.network_capture import (
    BLOCKED_BROWSER_RESOURCE_TYPES,
    BLOCKED_BROWSER_ROUTE_TOKENS,
    PROTECTED_CHALLENGE_ROUTE_TOKENS,
)
from app.services.config.runtime_settings import crawler_runtime_settings

if TYPE_CHECKING:
    from patchright.async_api import Browser, BrowserContext, Playwright

logger = logging.getLogger(__name__)


def _facade_attr(name: str, default):
    import sys

    facade = sys.modules.get("app.services.acquisition.browser_runtime")
    return getattr(facade, name, default) if facade is not None else default



class BrowserRuntimePool:
    def __init__(self) -> None:
        self.direct: dict[str, SharedBrowserRuntime] = {}
        self.proxied: dict[tuple[str, str], SharedBrowserRuntime] = {}
        self.lock = asyncio.Lock()
        self.popup_guard_tasks: set[asyncio.Task[Any]] = set()

_BROWSER_POOL = BrowserRuntimePool()


def register_popup_guard_task(task: asyncio.Task[Any]) -> None:
    _BROWSER_POOL.popup_guard_tasks.add(task)
    task.add_done_callback(_BROWSER_POOL.popup_guard_tasks.discard)


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

def _real_chrome_candidate_paths() -> tuple[str, ...]:
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
    for candidate in _real_chrome_candidate_paths():
        if Path(candidate).is_file():
            return candidate
    return None

def real_chrome_browser_available() -> bool:
    return real_chrome_executable_path() is not None

def _resolve_browser_binary(engine: str) -> tuple[str | None, str]:
    normalized_engine = _normalize_browser_engine(engine)
    if normalized_engine == _PATCHRIGHT_BROWSER_ENGINE:
        return None, _PATCHRIGHT_BROWSER_ENGINE
    if normalized_engine == _CHROMIUM_BROWSER_ENGINE:
        return None, _PATCHRIGHT_BROWSER_ENGINE
    executable_path = real_chrome_executable_path()
    if executable_path is None:
        return None, _REAL_CHROME_BROWSER_ENGINE
    return executable_path, executable_path

def _async_playwright_manager_for_engine(engine: str):
    normalized_engine = _normalize_browser_engine(engine)
    if normalized_engine in {_PATCHRIGHT_BROWSER_ENGINE, _CHROMIUM_BROWSER_ENGINE}:
        try:
            playwright_factory = _facade_attr(
                "_patchright_async_playwright_factory",
                _patchright_async_playwright_factory,
            )
            return playwright_factory()
        except Exception as exc:
            raise RuntimeError(
                "Patchright package is not available for browser runtime"
            ) from exc
    try:
        playwright_factory = _facade_attr(
            "_patchright_async_playwright_factory",
            _patchright_async_playwright_factory,
        )
        return playwright_factory()
    except Exception as exc:
        raise RuntimeError(
            "Patchright package is not available for real_chrome browser runtime"
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
        resolve_binary = _facade_attr("_resolve_browser_binary", _resolve_browser_binary)
        self.executable_path, self.browser_binary = resolve_binary(
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
        self._counter_lock = asyncio.Lock()
        self._stats_lock = asyncio.Lock()
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
        max_contexts = int(crawler_runtime_settings.browser_max_contexts_before_recycle)
        if max_contexts > 0 and self._total_contexts_created >= max_contexts:
            return True
        max_lifetime = int(crawler_runtime_settings.browser_max_lifetime_seconds)
        if max_lifetime > 0 and self._browser_launched_at > 0:
            if time.monotonic() - self._browser_launched_at >= max_lifetime:
                return True
        return False

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
            async_playwright = _async_playwright_manager_for_engine(self.browser_engine)
            self._playwright = await async_playwright().start()
            launch_args = [
                str(value).strip()
                for value in list(crawler_runtime_settings.browser_launch_args or ())
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
            launch_kwargs: dict[str, Any] = {
                "headless": launch_headless,
            }
            if launch_args:
                launch_kwargs["args"] = launch_args
            if self.browser_engine == _REAL_CHROME_BROWSER_ENGINE:
                if not self.executable_path:
                    raise RuntimeError(
                        "Real Chrome executable is not available for browser runtime"
                    )
                launch_kwargs["executable_path"] = self.executable_path
                real_chrome_ignore_args = _facade_attr(
                    "REAL_CHROME_IGNORE_DEFAULT_ARGS",
                    REAL_CHROME_IGNORE_DEFAULT_ARGS,
                )
                ignore_default_args = [
                    str(arg).strip()
                    for arg in (real_chrome_ignore_args or ())
                    if str(arg).strip()
                ]
                if ignore_default_args:
                    launch_kwargs["ignore_default_args"] = ignore_default_args
            launch_proxy_config = await self._launch_proxy_config_for_browser()
            if launch_proxy_config is not None:
                launch_kwargs["proxy"] = launch_proxy_config
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            self._browser_launched_at = time.monotonic()
            async with self._counter_lock:
                self._total_contexts_created = 0

    async def ensure(self) -> None:
        """Public browser warm-up API."""
        await self._ensure()

    async def _recycle_after_driver_disconnect(self) -> None:
        async with self._lock:
            await self._close_locked()
        await self.ensure()

    async def _open_context_page(
        self,
        *,
        context_options: dict[str, Any],
        context_spec: PlaywrightContextSpec,
    ) -> tuple[BrowserContext, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            if self._browser is None:
                raise RuntimeError("Browser runtime failed to initialize")
            context: BrowserContext | None = None
            try:
                context = await self._browser.new_context(**cast(Any, context_options))
                await _configure_context_routes(context)
                async with self._counter_lock:
                    self._total_contexts_created += 1
                page = await context.new_page()
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
            bridge_cls = _facade_attr("Socks5AuthBridge", Socks5AuthBridge)
            self._socks5_auth_bridge = bridge_cls(
                self._authenticated_socks5_proxy
            )
        bridge_proxy = await self._socks5_auth_bridge.start()
        bridge_proxy_config = _build_browser_proxy_config(bridge_proxy)
        if bridge_proxy_config is None:
            raise RuntimeError("SOCKS5 auth bridge failed to expose a browser proxy")
        return bridge_proxy_config

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
                context_options=dict(NATIVE_REAL_CHROME_CONTEXT_OPTIONS),
                init_script=None,
            )
        browser_major_version = None
        if self._browser is not None:
            raw_version = str(getattr(self._browser, "version", "") or "")
            try:
                browser_major_version = int(raw_version.split(".", 1)[0])
            except ValueError:
                browser_major_version = None
        spec_builder = _facade_attr(
            "build_playwright_context_spec",
            build_playwright_context_spec,
        )
        spec = spec_builder(
            run_id=run_id,
            browser_major_version=browser_major_version,
            locality_profile=locality_profile,
            browser_engine=self.browser_engine,
        )
        return PlaywrightContextSpec(
            context_options=dict(spec.context_options),
            init_script=None,
        )

    def _build_context_options(
        self,
        *,
        run_id: int | None = None,
        locality_profile: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        return dict(
            self._build_context_spec(
                run_id=run_id,
                locality_profile=locality_profile,
            ).context_options
        )

    @asynccontextmanager
    async def page(
        self,
        *,
        proxy: str | None = None,
        run_id: int | None = None,
        domain: str | None = None,
        locality_profile: dict[str, object] | None = None,
        allow_storage_state: bool = True,
    ):
        normalized_proxy = _normalized_proxy_value(proxy)
        if self.launch_proxy is None:
            if normalized_proxy is not None:
                raise RuntimeError(
                    "Proxied browser pages require a launch-owned browser runtime"
                )
        elif normalized_proxy not in {None, self.launch_proxy}:
            raise RuntimeError("Browser runtime proxy does not match requested proxy")
        self.touch()
        await self._ensure()
        await self._update_queue_count(1)
        try:
            await self._semaphore.acquire()
        except Exception:
            await self._update_queue_count(-1)
            raise
        await self._update_queue_count(-1)
        if self._browser is None:
            self._semaphore.release()
            raise RuntimeError("Browser runtime failed to initialize")
        context: BrowserContext | None = None
        await self._update_active_contexts(1)
        try:
            context_spec = self._build_context_spec(
                run_id=run_id,
                locality_profile=locality_profile,
            )
            context_options = dict(context_spec.context_options)
            allow_domain_storage_state = bool(
                allow_storage_state
                and (
                    self.launch_proxy is None
                    or bool(
                        crawler_runtime_settings.browser_proxy_domain_storage_enabled
                    )
                )
            )
            if allow_storage_state:
                storage_state = await cookie_store.load_storage_state_for_run(
                    run_id,
                    browser_engine=self.browser_engine,
                )
                if not storage_state and allow_domain_storage_state:
                    storage_state = await cookie_store.load_storage_state_for_domain(
                        domain,
                        browser_engine=self.browser_engine,
                    )
                if storage_state:
                    context_options["storage_state"] = storage_state
            context, page = await self._open_context_page(
                context_options=context_options,
                context_spec=context_spec,
            )
            yield page
        finally:
            await self._update_active_contexts(-1)
            if context is not None:
                persist_storage_state = _facade_attr(
                    "persist_context_storage_state",
                    persist_context_storage_state,
                )
                await persist_storage_state(
                    context,
                    run_id=run_id,
                    domain=domain,
                    browser_engine=self.browser_engine,
                    persist_run_storage_state=bool(
                        getattr(context, _RUN_STORAGE_PERSIST_ATTR, True)
                    ),
                    persist_domain_storage_state=bool(
                        allow_domain_storage_state
                        and bool(getattr(context, _DOMAIN_STORAGE_PERSIST_ATTR, True))
                    ),
                    timeout_seconds=_browser_context_timeout_seconds(),
                )
                await _close_browser_context_safely(context)
            self._semaphore.release()

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        if self._browser is not None:
            try:
                await asyncio.wait_for(
                    self._browser.close(),
                    timeout=_browser_close_timeout_seconds(),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Timed out closing browser runtime after %.1fs",
                    _browser_close_timeout_seconds(),
                )
            except Exception:
                logger.debug("Failed to close browser", exc_info=True)
        if self._playwright is not None:
            try:
                await asyncio.wait_for(
                    self._playwright.stop(),
                    timeout=_browser_close_timeout_seconds(),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Timed out stopping playwright after %.1fs",
                    _browser_close_timeout_seconds(),
                )
            except Exception:
                logger.debug("Failed to stop playwright", exc_info=True)
        if self._socks5_auth_bridge is not None:
            try:
                await asyncio.wait_for(
                    self._socks5_auth_bridge.close(),
                    timeout=_browser_close_timeout_seconds(),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Timed out closing SOCKS5 auth bridge after %.1fs",
                    _browser_close_timeout_seconds(),
                )
            except Exception:
                logger.debug("Failed to close SOCKS5 auth bridge", exc_info=True)
        self._browser = None
        self._playwright = None
        self._socks5_auth_bridge = None
        self._browser_launched_at = 0.0

    async def _update_active_contexts(self, delta: int) -> None:
        async with self._stats_lock:
            self._active_contexts = max(0, self._active_contexts + delta)

    async def _update_queue_count(self, delta: int) -> None:
        async with self._stats_lock:
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

async def _configure_context_routes(context: Any) -> None:
    try:
        await context.route("**/*", _block_unneeded_route)
    except Exception:
        logger.debug("Failed to install browser request blocking", exc_info=True)

async def _block_unneeded_route(route: Any) -> None:
    request = getattr(route, "request", None)
    resource_type = str(getattr(request, "resource_type", "") or "").lower()
    request_url = str(getattr(request, "url", "") or "").lower()
    if any(token in request_url for token in PROTECTED_CHALLENGE_ROUTE_TOKENS):
        try:
            await route.continue_()
            return
        except Exception:
            logger.debug(
                "Browser request continue failed for protected challenge url=%s",
                request_url,
                exc_info=True,
            )
            return
    should_abort = resource_type in BLOCKED_BROWSER_RESOURCE_TYPES or any(
        token in request_url for token in BLOCKED_BROWSER_ROUTE_TOKENS
    )
    if should_abort:
        try:
            await route.abort()
            return
        except Exception:
            logger.debug(
                "Browser request abort failed for resource_type=%s url=%s; attempting continue",
                resource_type,
                request_url,
                exc_info=True,
            )
            try:
                await route.continue_()
                return
            except Exception:
                logger.debug(
                    "Browser request continue failed after abort failure for resource_type=%s url=%s",
                    resource_type,
                    request_url,
                    exc_info=True,
                )
                return
    try:
        await route.continue_()
    except Exception:
        logger.debug(
            "Browser request continue failed for resource_type=%s url=%s",
            resource_type,
            request_url,
            exc_info=True,
        )

async def temporary_browser_page(
    *,
    proxy: str,
    run_id: int | None = None,
    domain: str | None = None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
    locality_profile: dict[str, object] | None = None,
    allow_storage_state: bool = True,
):
    runtime = await get_browser_runtime(proxy=proxy, browser_engine=browser_engine)
    async with runtime.page(
        run_id=run_id,
        domain=domain,
        locality_profile=locality_profile,
        allow_storage_state=allow_storage_state,
    ) as page:
        yield page

async def _evict_idle_browser_runtimes_locked() -> None:
    idle_ttl_seconds = max(
        0, int(crawler_runtime_settings.browser_runtime_pool_idle_ttl_seconds)
    )
    max_entries = max(1, int(crawler_runtime_settings.browser_runtime_pool_max_entries))
    pools = (
        ("direct", _BROWSER_POOL.direct),
        ("proxied", _BROWSER_POOL.proxied),
    )
    candidates: list[tuple[str, str | tuple[str, str], SharedBrowserRuntime]] = []
    for pool_name, pool in pools:
        for key, runtime in list(pool.items()):
            active_and_queued, _last_used = runtime.eviction_key()
            if active_and_queued > 0:
                continue
            if idle_ttl_seconds > 0 and runtime.idle_seconds() >= idle_ttl_seconds:
                if pool_name == "direct":
                    normalized_key: str | tuple[str, str] = str(key)
                elif isinstance(key, tuple) and len(key) == 2:
                    normalized_key = (str(key[0]), str(key[1]))
                else:
                    continue
                candidates.append((pool_name, normalized_key, runtime))
    while sum(len(pool) for _pool_name, pool in pools) - len(candidates) >= max_entries:
        candidate_keys = {(pool_name, key) for pool_name, key, _runtime in candidates}
        remaining: list[tuple[str, str | tuple[str, str], SharedBrowserRuntime]] = []
        for pool_name, pool in pools:
            for key, runtime in list(pool.items()):
                if runtime.eviction_key()[0] != 0:
                    continue
                normalized_remaining_key: str | tuple[str, str]
                if pool_name == "direct":
                    normalized_remaining_key = str(key)
                elif isinstance(key, tuple) and len(key) == 2:
                    normalized_remaining_key = (str(key[0]), str(key[1]))
                else:
                    continue
                if (pool_name, normalized_remaining_key) in candidate_keys:
                    continue
                remaining.append((pool_name, normalized_remaining_key, runtime))
        if not remaining:
            break
        remaining.sort(key=lambda item: item[2].eviction_key())
        candidates.append(remaining[0])
    for pool_name, key, runtime in candidates:
        if pool_name == "direct":
            _BROWSER_POOL.direct.pop(str(key), None)
        else:
            proxied_key = key if isinstance(key, tuple) and len(key) == 2 else None
            if proxied_key is not None:
                _BROWSER_POOL.proxied.pop(proxied_key, None)
        await runtime.close()

async def get_browser_runtime(
    *,
    proxy: str | None = None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
) -> SharedBrowserRuntime:
    normalized_proxy = _normalized_proxy_value(proxy)
    normalized_engine = _normalize_browser_engine(browser_engine)
    if normalized_proxy is None:
        runtime = _BROWSER_POOL.direct.get(normalized_engine)
        if runtime is not None:
            runtime.touch()
            return runtime
    else:
        runtime = _BROWSER_POOL.proxied.get((normalized_engine, normalized_proxy))
        if runtime is not None:
            runtime.touch()
            return runtime
    async with _BROWSER_POOL.lock:
        if normalized_proxy is None:
            runtime = _BROWSER_POOL.direct.get(normalized_engine)
            if runtime is None:
                await _evict_idle_browser_runtimes_locked()
                runtime = SharedBrowserRuntime(
                    max_contexts=settings.browser_pool_size,
                    browser_engine=normalized_engine,
                )
                _BROWSER_POOL.direct[normalized_engine] = runtime
            runtime.touch()
            return runtime
        await _evict_idle_browser_runtimes_locked()
        runtime = _BROWSER_POOL.proxied.get((normalized_engine, normalized_proxy))
        if runtime is None:
            runtime = SharedBrowserRuntime(
                max_contexts=settings.browser_pool_size,
                launch_proxy=normalized_proxy,
                browser_engine=normalized_engine,
            )
            _BROWSER_POOL.proxied[(normalized_engine, normalized_proxy)] = runtime
        runtime.touch()
        return runtime

async def shutdown_browser_runtime() -> None:
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
    for runtime in runtimes:
        await runtime.close()
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
    if not runtimes:
        max_size = max(1, int(settings.browser_pool_size))
        return {
            "ready": False,
            "size": 0,
            "max_size": max_size,
            "active": 0,
            "queued": 0,
            "capacity": max_size,
        }
    snapshots = [runtime.snapshot() for runtime in runtimes]
    max_size = sum(
        _snapshot_count(snapshot, "max_size", "capacity") for snapshot in snapshots
    )
    capacity = sum(
        _snapshot_count(snapshot, "capacity", "max_size") for snapshot in snapshots
    )
    return {
        "ready": any(bool(snapshot.get("ready")) for snapshot in snapshots),
        "size": sum(_int_or_zero(snapshot.get("size")) for snapshot in snapshots),
        "max_size": max_size,
        "active": sum(_int_or_zero(snapshot.get("active")) for snapshot in snapshots),
        "queued": sum(_int_or_zero(snapshot.get("queued")) for snapshot in snapshots),
        "capacity": capacity,
        "total_contexts_created": sum(
            _int_or_zero(snapshot.get("total_contexts_created"))
            for snapshot in snapshots
        ),
        "browser_lifetime_seconds": max(
            _int_or_zero(snapshot.get("browser_lifetime_seconds"))
            for snapshot in snapshots
        ),
    }

def _log_shutdown_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.debug("Browser runtime shutdown task was cancelled")
    except Exception:
        logger.exception("Browser runtime shutdown task failed")

def _browser_context_timeout_seconds() -> float:
    return max(
        0.1,
        float(crawler_runtime_settings.browser_context_timeout_ms) / 1000,
    )

def _browser_close_timeout_seconds() -> float:
    return max(
        0.1,
        float(crawler_runtime_settings.browser_close_timeout_ms) / 1000,
    )

async def _close_browser_context_safely(context: Any) -> None:
    try:
        await asyncio.wait_for(
            context.close(),
            timeout=_browser_close_timeout_seconds(),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Timed out closing browser context after %.1fs",
            _browser_close_timeout_seconds(),
        )
    except asyncio.CancelledError:
        logger.warning("Browser context close was cancelled")
    except Exception:
        logger.debug("Failed to close browser context", exc_info=True)


browser_pool_state = _BROWSER_POOL
block_unneeded_route = _block_unneeded_route
real_chrome_candidate_paths = _real_chrome_candidate_paths
resolve_browser_binary = _resolve_browser_binary
patchright_async_playwright_factory = _patchright_async_playwright_factory

def _snapshot_count(snapshot: dict[str, object], *keys: str) -> int:
    for key in keys:
        value = snapshot.get(key)
        if value is not None:
            return _int_or_zero(value)
    return 0
