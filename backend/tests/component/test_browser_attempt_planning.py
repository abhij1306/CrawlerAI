"""test_crawl_fetch_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_fetch_runtime_test_support import (
    HostProtectionPolicy,
    _default_fetch_context,
    browser_policy,
    crawl_fetch_runtime,
    pytest,
)


@pytest.mark.component
def test_browser_engine_attempts_uses_patchright_by_default() -> None:
    context = _default_fetch_context()

    attempts = crawl_fetch_runtime._browser_engine_attempts(
        context=context,
        host_policy=HostProtectionPolicy(host="example.com"),
    )

    assert attempts == ["patchright"]


@pytest.mark.component
def test_browser_engine_attempts_uses_real_chrome_after_patchright_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_real_chrome_enabled",
        True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "real_chrome_browser_available",
        lambda: True,
    )
    context = _default_fetch_context()

    attempts = crawl_fetch_runtime._browser_engine_attempts(
        context=context,
        host_policy=HostProtectionPolicy(
            host="example.com",
            patchright_blocked=True,
            prefer_browser=True,
            last_block_vendor="datadome",
        ),
    )

    assert attempts == ["real_chrome", "patchright"]


@pytest.mark.component
def test_browser_engine_attempts_uses_real_chrome_for_blocked_commerce_detail_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_real_chrome_enabled",
        True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "real_chrome_browser_available",
        lambda: True,
    )
    context = _default_fetch_context(
        url="https://shop.example.com/products/widget",
        surface="ecommerce_detail",
    )

    attempts = crawl_fetch_runtime._browser_engine_attempts(
        context=context,
        host_policy=HostProtectionPolicy(
            host="shop.example.com",
            patchright_blocked=True,
            prefer_browser=True,
        ),
    )

    assert attempts == ["real_chrome", "patchright"]


@pytest.mark.component
def test_browser_engine_attempts_keeps_forced_patchright_explicit_when_unavailable() -> (
    None
):
    context = _default_fetch_context(forced_browser_engine="patchright")

    attempts = crawl_fetch_runtime._browser_engine_attempts(
        context=context,
        host_policy=HostProtectionPolicy(host="example.com"),
    )

    assert attempts == ["patchright"]


@pytest.mark.component
def test_browser_engine_attempts_does_not_escalate_from_patchright_block_memory_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_real_chrome_enabled",
        True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "real_chrome_browser_available",
        lambda: True,
    )
    context = _default_fetch_context()

    attempts = crawl_fetch_runtime._browser_engine_attempts(
        context=context,
        host_policy=HostProtectionPolicy(
            host="example.com",
            patchright_blocked=True,
            prefer_browser=False,
        ),
    )

    assert attempts == ["patchright"]


@pytest.mark.component
def test_saved_real_chrome_contract_skips_patchright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_real_chrome_enabled",
        True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime, "real_chrome_browser_available", lambda: True
    )
    context = _default_fetch_context(forced_browser_engine="real_chrome")

    attempts = crawl_fetch_runtime._browser_engine_attempts(
        context=context,
        host_policy=HostProtectionPolicy(host="example.com"),
    )

    assert attempts == ["real_chrome"]


@pytest.mark.component
def test_durable_vendor_block_limits_browser_engine_attempts() -> None:
    attempts = browser_policy.durable_vendor_block_engine_attempts(
        engine_attempts=["real_chrome", "patchright"],
        host_policy=HostProtectionPolicy(
            host="example.com",
            prefer_browser=True,
            last_block_vendor="datadome",
            last_block_method="browser:real_chrome",
        ),
        forced_engine=None,
    )

    assert attempts == ["patchright"]


@pytest.mark.component
def test_durable_vendor_block_keeps_http_block_engine_attempts() -> None:
    attempts = browser_policy.durable_vendor_block_engine_attempts(
        engine_attempts=["patchright", "real_chrome"],
        host_policy=HostProtectionPolicy(
            host="example.com",
            prefer_browser=True,
            last_block_vendor="akamai",
            last_block_method="curl_cffi",
        ),
        forced_engine=None,
    )

    assert attempts == ["patchright", "real_chrome"]
