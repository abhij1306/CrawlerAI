"""test_crawl_fetch_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_fetch_runtime_test_support import (
    _as_async,
    _default_fetch_context,
    _page_fetch_result,
    crawl_fetch_runtime,
    pytest,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_real_chrome_success_updates_host_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usable_fetches: list[dict[str, object]] = []

    @_as_async
    def _fake_note_host_usable_fetch(value: str | None, **kwargs):
        usable_fetches.append({"value": value, **kwargs})

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "note_host_usable_fetch",
        _fake_note_host_usable_fetch,
    )
    context = _default_fetch_context()
    result = _page_fetch_result(
        "<html><body>Widget</body></html>",
        blocked=False,
        browser_diagnostics={"browser_engine": "real_chrome"},
    )

    await crawl_fetch_runtime._update_host_result_memory(context, result=result)

    assert usable_fetches == [
        {
            "value": "https://example.com/products/widget",
            "method": "browser:real_chrome",
            "proxy_used": False,
            "ttl_seconds": crawl_fetch_runtime.crawler_runtime_settings.coerce_host_memory_ttl_seconds(
                None
            ),
        }
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_patchright_success_updates_host_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usable_fetches: list[dict[str, object]] = []

    @_as_async
    def _fake_note_host_usable_fetch(value: str | None, **kwargs):
        usable_fetches.append({"value": value, **kwargs})

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "note_host_usable_fetch",
        _fake_note_host_usable_fetch,
    )
    context = _default_fetch_context()
    result = _page_fetch_result(
        "<html><body>Widget</body></html>",
        blocked=False,
        browser_diagnostics={"browser_engine": "patchright"},
    )

    await crawl_fetch_runtime._update_host_result_memory(context, result=result)

    assert usable_fetches == [
        {
            "value": "https://example.com/products/widget",
            "method": "browser:patchright",
            "proxy_used": False,
            "ttl_seconds": crawl_fetch_runtime.crawler_runtime_settings.coerce_host_memory_ttl_seconds(
                None
            ),
        }
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_location_required_diagnostics_do_not_write_hard_block_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hard_blocks: list[dict[str, object]] = []
    usable_fetches: list[dict[str, object]] = []

    @_as_async
    def _fake_note_host_hard_block(value: str | None, **kwargs):
        hard_blocks.append({"value": value, **kwargs})

    @_as_async
    def _fake_note_host_usable_fetch(value: str | None, **kwargs):
        usable_fetches.append({"value": value, **kwargs})

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "note_host_hard_block",
        _fake_note_host_hard_block,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "note_host_usable_fetch",
        _fake_note_host_usable_fetch,
    )
    context = _default_fetch_context()
    result = _page_fetch_result(
        "<html><body>Choose your location</body></html>",
        blocked=True,
        browser_diagnostics={
            "browser_engine": "real_chrome",
            "browser_outcome": "location_required",
            "failure_reason": "location_required",
        },
    )

    await crawl_fetch_runtime._update_host_result_memory(context, result=result)

    assert hard_blocks == []
    assert usable_fetches == []
