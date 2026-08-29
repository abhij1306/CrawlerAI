from __future__ import annotations

import asyncio

import sys

import time

from types import SimpleNamespace

from unittest.mock import AsyncMock

import httpx

import pytest

from patchright.async_api import Error as PlaywrightError

from app.acquisition.fetch import fetch_context as crawl_fetch_runtime

from app.acquisition.fetch import browser_policy, planned_http

from app.acquisition import (
    browser_background_tasks,
    browser_capture,
    runtime as acquisition_runtime,
)

from app.acquisition.host_protection_memory import HostProtectionPolicy

from app.acquisition.browser_runtime import (
    classify_network_endpoint,
    read_network_payload_body,
    should_capture_network_payload,
)

from app.acquisition.runtime import (
    PageFetchResult,
    http_fetch,
    should_escalate_to_browser_async,
)

from app.core.config.pipeline_reasons import (
    BROWSER_ESCALATION_SKIPPED_INSUFFICIENT_BUDGET,
)


class FakeBodyResponse:
    def __init__(
        self,
        body: bytes | None = None,
        *,
        error: Exception | None = None,
        url: str = "https://example.com/api/data.json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self._error = error
        self.url = url
        self.body_calls = 0
        self.headers = headers or {}

    async def body(self) -> bytes:
        self.body_calls += 1
        if self._error is not None:
            raise self._error
        return self._body or b""


def _default_fetch_context(
    url: str = "https://example.com/products/widget",
    surface: str = "ecommerce_detail",
    **overrides,
):
    return crawl_fetch_runtime._FetchRuntimeContext(
        url=url,
        resolved_timeout=5.0,
        deadline_monotonic=time.perf_counter() + 5.0,
        run_id=None,
        surface=surface,
        traversal_mode=None,
        max_pages=1,
        max_scrolls=1,
        max_records=None,
        on_event=None,
        browser_reason=None,
        requested_fields=[],
        listing_recovery_mode=None,
        proxies=[None],
        proxy_profile={},
        traversal_required=False,
        fetch_mode="browser_only",
        runtime_policy={},
        host_memory_ttl_seconds=crawl_fetch_runtime.crawler_runtime_settings.coerce_host_memory_ttl_seconds(
            None
        ),
        **overrides,
    )


def _page_fetch_result(
    html: str,
    *,
    url: str = "https://example.com/products/widget",
    final_url: str | None = None,
    method: str = "browser",
    status_code: int = 200,
    **overrides,
) -> PageFetchResult:
    return PageFetchResult(
        url=url,
        final_url=final_url or url,
        html=html,
        status_code=status_code,
        method=method,
        **overrides,
    )


def _as_async(fn):
    async def _wrapped(*args, **kwargs):
        await asyncio.sleep(0)
        return fn(*args, **kwargs)

    return _wrapped


@pytest.fixture(autouse=True)
async def _reset_fetch_runtime_state_between_tests(
    monkeypatch: pytest.MonkeyPatch,
):
    await crawl_fetch_runtime.reset_fetch_runtime_state()

    @_as_async
    def _default_load_policy(url: str, *, session=None, ttl_seconds=None):
        del url, session, ttl_seconds
        return HostProtectionPolicy(host="")

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        _default_load_policy,
    )
    try:
        yield
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()


__all__ = [
    "BROWSER_ESCALATION_SKIPPED_INSUFFICIENT_BUDGET",
    "AsyncMock",
    "FakeBodyResponse",
    "HostProtectionPolicy",
    "PageFetchResult",
    "PlaywrightError",
    "SimpleNamespace",
    "_as_async",
    "_default_fetch_context",
    "_page_fetch_result",
    "_reset_fetch_runtime_state_between_tests",
    "acquisition_runtime",
    "asyncio",
    "browser_background_tasks",
    "browser_capture",
    "browser_policy",
    "classify_network_endpoint",
    "crawl_fetch_runtime",
    "http_fetch",
    "httpx",
    "planned_http",
    "pytest",
    "read_network_payload_body",
    "should_capture_network_payload",
    "should_escalate_to_browser_async",
    "sys",
    "time",
]
