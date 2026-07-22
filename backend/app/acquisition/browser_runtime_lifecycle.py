"""Browser process lifecycle for ``SharedBrowserRuntime`` (launch/recycle/close).

Extracted from ``app.acquisition.browser_pool`` as a cohesive collaborator; the
runtime class keeps only orchestration and its public interface. Module-level
helpers and patchable names (``Socks5AuthBridge``,
``REAL_CHROME_IGNORE_DEFAULT_ARGS``, ``_async_playwright_manager_for_engine``,
``_wait_for_browser_step``, timeout getters) are resolved through the
``browser_pool`` module object at call time so existing monkeypatch-based tests
keep working against the same module namespace as before the extraction.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from app.acquisition.browser_background_tasks import await_without_cancelling
from app.acquisition.browser_diagnostics import (
    REAL_CHROME_BROWSER_ENGINE as _REAL_CHROME_BROWSER_ENGINE,
    launch_headless_for_engine as _launch_headless_for_engine,
    resolve_browser_pool as _browser_pool,
)
from app.core.config.runtime_settings import crawler_runtime_settings

if TYPE_CHECKING:
    from app.acquisition import browser_pool

logger = logging.getLogger(__name__)


def should_recycle_browser(runtime: browser_pool.SharedBrowserRuntime) -> bool:
    if runtime._browser is None:
        return False
    if not getattr(runtime._browser, "is_connected", lambda: True)():
        return True
    if runtime._active_contexts > 0:
        return False
    if context_recycle_threshold_reached(runtime):
        return True
    max_lifetime = int(crawler_runtime_settings.browser_max_lifetime_seconds)
    if max_lifetime > 0 and runtime._browser_launched_at > 0:
        if time.monotonic() - runtime._browser_launched_at >= max_lifetime:
            return True
    return False


def context_recycle_threshold_reached(runtime: browser_pool.SharedBrowserRuntime) -> bool:
    max_contexts = int(crawler_runtime_settings.browser_max_contexts_before_recycle)
    return max_contexts > 0 and runtime._total_contexts_created >= max_contexts


async def yield_slot_until_recycle_window(
    runtime: browser_pool.SharedBrowserRuntime, timeout_seconds: float
) -> bool:
    if (
        runtime._browser is None
        or not context_recycle_threshold_reached(runtime)
        or runtime._active_contexts > 0
    ):
        return False
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    runtime._semaphore.release()
    while (
        runtime._active_contexts > 0 and context_recycle_threshold_reached(runtime)
    ):
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
    await asyncio.wait_for(runtime._semaphore.acquire(), timeout=remaining)
    return True


async def ensure_browser_runtime(runtime: browser_pool.SharedBrowserRuntime) -> None:
    if runtime._browser is not None and not should_recycle_browser(runtime):
        return
    async with runtime._lock:
        if should_recycle_browser(runtime):
            logger.info(
                "Recycling browser instance (contexts=%d, lifetime=%.0fs)",
                runtime._total_contexts_created,
                time.monotonic() - runtime._browser_launched_at
                if runtime._browser_launched_at
                else 0,
            )
            await close_browser_runtime_locked(runtime)
        if runtime._browser is not None:
            return
        try:
            async_playwright = _browser_pool()._async_playwright_manager_for_engine(
                runtime.browser_engine
            )
            runtime._playwright = await _browser_pool()._wait_for_browser_step(
                async_playwright().start(),
                timeout_seconds=_browser_pool()._browser_launch_timeout_seconds(),
                message="Timed out launching browser driver",
            )
            launch_kwargs = await browser_launch_kwargs(runtime)
            runtime._browser = await _browser_pool()._wait_for_browser_step(
                runtime._playwright.chromium.launch(**launch_kwargs),
                timeout_seconds=_browser_pool()._browser_launch_timeout_seconds(),
                message="Timed out launching browser",
            )
            runtime._browser_launched_at = time.monotonic()
            runtime._total_contexts_created = 0
        except Exception:
            await close_browser_runtime_locked(runtime)
            raise


async def recycle_after_driver_disconnect(runtime: browser_pool.SharedBrowserRuntime) -> None:
    async with runtime._lock:
        await close_browser_runtime_locked(runtime)
    await runtime.ensure()


async def browser_launch_kwargs(runtime: browser_pool.SharedBrowserRuntime) -> dict[str, Any]:
    launch_args = [
        str(value).strip()
        for value in crawler_runtime_settings.browser_launch_args or ()
        if str(value).strip()
    ]
    launch_headless = _launch_headless_for_engine(runtime.browser_engine)
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
    add_real_chrome_launch_kwargs(runtime, launch_kwargs)
    launch_proxy_config = await launch_proxy_config_for_browser(runtime)
    if launch_proxy_config is not None:
        launch_kwargs["proxy"] = launch_proxy_config
    return launch_kwargs


def add_real_chrome_launch_kwargs(
    runtime: browser_pool.SharedBrowserRuntime, launch_kwargs: dict[str, Any]
) -> None:
    if runtime.browser_engine != _REAL_CHROME_BROWSER_ENGINE:
        return
    if not runtime.executable_path:
        raise RuntimeError(
            "Real Chrome executable is not available for browser runtime"
        )
    launch_kwargs["executable_path"] = runtime.executable_path
    ignore_default_args = [
        str(arg).strip()
        for arg in (_browser_pool().REAL_CHROME_IGNORE_DEFAULT_ARGS or ())
        if str(arg).strip()
    ]
    if ignore_default_args:
        launch_kwargs["ignore_default_args"] = ignore_default_args


async def launch_proxy_config_for_browser(
    runtime: browser_pool.SharedBrowserRuntime,
) -> dict[str, str] | None:
    if runtime.launch_proxy_config is None:
        return None
    if runtime._authenticated_socks5_proxy is None:
        return dict(runtime.launch_proxy_config)
    if runtime._socks5_auth_bridge is None:
        bridge_cls = _browser_pool().Socks5AuthBridge
        runtime._socks5_auth_bridge = bridge_cls(runtime._authenticated_socks5_proxy)
    bridge_proxy = await runtime._socks5_auth_bridge.start()
    bridge_proxy_config = _browser_pool()._build_browser_proxy_config(bridge_proxy)
    if bridge_proxy_config is None:
        raise RuntimeError("SOCKS5 auth bridge failed to expose a browser proxy")
    return bridge_proxy_config


async def close_browser_runtime_locked(runtime: browser_pool.SharedBrowserRuntime) -> None:
    components = (
        ("closing browser runtime", runtime._browser, "close"),
        ("stopping playwright", runtime._playwright, "stop"),
        ("closing SOCKS5 auth bridge", runtime._socks5_auth_bridge, "close"),
    )
    for label, component, close_method in components:
        if component is None:
            continue
        try:
            closed = await await_without_cancelling(
                getattr(component, close_method)(),
                timeout_seconds=_browser_pool()._browser_close_timeout_seconds(),
            )
            if not closed:
                logger.warning(
                    "Timed out %s after %.1fs",
                    label,
                    _browser_pool()._browser_close_timeout_seconds(),
                )
        except Exception:
            logger.debug("Failed while %s", label, exc_info=True)
    runtime._browser = None
    runtime._playwright = None
    runtime._socks5_auth_bridge = None
    runtime._browser_launched_at = 0.0
