"""test_browser_context cases split by public behavior."""

from __future__ import annotations

from tests.component.browser_context_test_support import (
    SimpleNamespace,
    _authority_with_credentials,
    _context_spec,
    _credential_url,
    _masked_proxy_display,
    _secret_mapping,
    acquisition_browser_pool,
    acquisition_browser_runtime,
    build_browser_proxy_config,
    cookie_store,
    crawl_fetch_runtime,
    pytest,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_passes_generated_context_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []
    created_pages: list[object] = []
    routed_patterns: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del handler
            routed_patterns.append(pattern)

        async def new_page(self):
            page = object()
            created_pages.append(page)
            return page

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
        lambda **_: _context_spec(
            {
                "user_agent": "Mozilla/5.0 Runtime/145.0",
                "viewport": {"width": 1600, "height": 900},
                "extra_http_headers": {"Accept": "text/html"},
                "locale": "en-US",
                "device_scale_factor": 1.0,
                "has_touch": False,
                "is_mobile": False,
                "service_workers": "block",
                "bypass_csp": False,
            }
        ),
    )

    async with runtime.page() as page:
        assert page in created_pages

    assert captured_kwargs == [
        {
            "user_agent": "Mozilla/5.0 Runtime/145.0",
            "viewport": {"width": 1600, "height": 900},
            "extra_http_headers": {"Accept": "text/html"},
            "locale": "en-US",
            "device_scale_factor": 1.0,
            "has_touch": False,
            "is_mobile": False,
            "service_workers": "block",
            "bypass_csp": False,
        }
    ]
    assert routed_patterns == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_uses_native_context_for_real_chrome(
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
            return SimpleNamespace(context=self)

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "_resolve_browser_binary",
        lambda _engine: ("C:/Chrome/chrome.exe", "C:/Chrome/chrome.exe"),
    )
    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec({"user_agent": "Mozilla/5.0 Runtime/145.0"}),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_real_chrome_native_context",
        True,
    )
    runtime = acquisition_browser_runtime.SharedBrowserRuntime(
        max_contexts=1,
        browser_engine="real_chrome",
    )
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    async with runtime.page():
        pass

    assert captured_kwargs == [{"no_viewport": True}]


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_skips_init_script_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_scripts: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            init_scripts.append(script)

        async def new_page(self):
            return SimpleNamespace(context=self)

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
        lambda **_: _context_spec(init_script="window.__browserforge = true;"),
    )
    async with runtime.page():
        pass

    assert init_scripts == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_uses_socks5_auth_bridge_and_keeps_context_proxy_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_launch_kwargs: list[dict[str, object]] = []
    captured_context_kwargs: list[dict[str, object]] = []
    bridge_start_calls: list[str] = []
    bridge_close_calls: list[str] = []

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
            captured_context_kwargs.append(kwargs)
            return FakeContext()

    class FakePlaywrightInstance:
        def __init__(self) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)

        async def _launch(self, **kwargs):
            captured_launch_kwargs.append(kwargs)
            return FakeBrowser()

        async def stop(self) -> None:
            return None

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance()

    class FakeBridge:
        def __init__(self, upstream) -> None:
            self.upstream = upstream

        async def start(self) -> str:
            bridge_start_calls.append(
                f"{self.upstream.scheme}://{self.upstream.username}:***@{self.upstream.host}:{self.upstream.port}"
            )
            return "socks5://127.0.0.1:8899"

        async def close(self) -> None:
            bridge_close_calls.append("closed")

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(acquisition_browser_pool, "Socks5AuthBridge", FakeBridge)
    monkeypatch.setattr(
        "patchright.async_api.async_playwright",
        lambda: FakePlaywrightManager(),
    )

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(
        max_contexts=1,
        launch_proxy="socks5://user-name:pass-word@31.58.9.4:6077",
    )

    async with runtime.page():
        pass

    assert captured_launch_kwargs == [
        {
            "headless": False,
            "args": [
                "--disable-features=IsolateOrigins,site-per-process",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--window-size=1920,1080",
                "--disable-search-engine-choice-screen",
                "--disable-background-networking",
                "--disable-client-side-phishing-detection",
                "--disable-domain-reliability",
                "--disable-sync",
                "--no-first-run",
                "--headless=new",
            ],
            "proxy": {
                "server": "socks5://127.0.0.1:8899",
            },
        }
    ]
    assert captured_context_kwargs == [{}]
    assert bridge_start_calls == ["socks5://user-name:***@31.58.9.4:6077"]
    await runtime.close()
    assert bridge_close_calls == ["closed"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_rejects_http_proxy_without_pinned_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_launch_kwargs: list[dict[str, object]] = []

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

    class FakePlaywrightInstance:
        def __init__(self) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)

        async def _launch(self, **kwargs):
            captured_launch_kwargs.append(kwargs)
            return FakeBrowser()

        async def stop(self) -> None:
            return None

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        "patchright.async_api.async_playwright",
        lambda: FakePlaywrightManager(),
    )

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(
        max_contexts=1,
        launch_proxy=_credential_url(
            scheme="http",
            username="user-name",
            secret="pass-word",
            host="31.58.9.4",
            port=6077,
        ),
    )

    with pytest.raises(RuntimeError, match="must use socks5"):
        async with runtime.page():
            pass

    assert captured_launch_kwargs == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_launches_real_chrome_headful_for_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_launch_kwargs: list[dict[str, object]] = []

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

    class FakePlaywrightInstance:
        def __init__(self) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)

        async def _launch(self, **kwargs):
            captured_launch_kwargs.append(kwargs)
            return FakeBrowser()

        async def stop(self) -> None:
            return None

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance()

    monkeypatch.setattr(
        acquisition_browser_pool,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        acquisition_browser_pool,
        "_resolve_browser_binary",
        lambda _engine: ("C:/Chrome/chrome.exe", "C:/Chrome/chrome.exe"),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_real_chrome_force_headful",
        True,
    )
    monkeypatch.setattr(
        acquisition_browser_pool,
        "REAL_CHROME_IGNORE_DEFAULT_ARGS",
        ("--enable-automation", "--remote-debugging-pipe"),
    )

    class FakeBridge:
        def __init__(self, upstream=None) -> None:
            assert upstream is None

        async def start(self) -> str:
            return "socks5://127.0.0.1:8899"

        async def close(self) -> None:
            return None

    monkeypatch.setattr(acquisition_browser_pool, "Socks5AuthBridge", FakeBridge)
    monkeypatch.setattr(
        "patchright.async_api.async_playwright",
        lambda: FakePlaywrightManager(),
    )

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(
        max_contexts=1,
        browser_engine="real_chrome",
    )

    async with runtime.page():
        pass

    assert captured_launch_kwargs == [
        {
            "headless": False,
            "args": [
                "--disable-features=IsolateOrigins,site-per-process",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--window-size=1920,1080",
                "--disable-search-engine-choice-screen",
                "--disable-background-networking",
                "--disable-client-side-phishing-detection",
                "--disable-domain-reliability",
                "--disable-sync",
                "--no-first-run",
            ],
            "executable_path": "C:/Chrome/chrome.exe",
            "ignore_default_args": [
                "--enable-automation",
                "--remote-debugging-pipe",
            ],
            "proxy": {"server": "socks5://127.0.0.1:8899"},
        }
    ]


@pytest.mark.component
def test_display_proxy_masks_authenticated_proxy_credentials() -> None:
    assert acquisition_browser_runtime._display_proxy(
        _credential_url(
            scheme="http",
            username="user-name",
            secret="pass-word",
            host="31.58.9.4",
            port=6077,
        )
    ) == _masked_proxy_display(scheme="http", host="31.58.9.4", port=6077)


@pytest.mark.component
def test_build_browser_proxy_config_normalizes_scheme_and_requires_username_for_password() -> (
    None
):
    assert build_browser_proxy_config(
        _credential_url(
            scheme="HTTP",
            username="user",
            secret="pass",
            host="31.58.9.4",
            port=6077,
        )
    ) == {
        "server": "http://31.58.9.4:6077",
        "username": "user",
        **_secret_mapping("pass"),
    }


@pytest.mark.component
def test_display_proxy_redacts_invalid_proxy_credentials() -> None:
    assert (
        acquisition_browser_runtime._display_proxy(
            _authority_with_credentials(
                username="user",
                secret="pass",
                host="31.58.9.4",
                port=6077,
            )
        )
        == "REDACTED"
    )


@pytest.mark.component
def test_storage_state_entry_count_ignores_generators() -> None:
    assert cookie_store._storage_state_entry_count((item for item in range(3))) == 0


@pytest.mark.asyncio
@pytest.mark.component
async def test_block_unneeded_route_allows_fonts_and_protected_challenge_urls() -> None:
    events: list[str] = []

    class FakeRoute:
        def __init__(self, *, resource_type: str, url: str) -> None:
            self.request = SimpleNamespace(resource_type=resource_type, url=url)

        async def abort(self) -> None:
            events.append(f"abort:{self.request.resource_type}:{self.request.url}")

        async def continue_(self) -> None:
            events.append(f"continue:{self.request.resource_type}:{self.request.url}")

    await acquisition_browser_runtime._block_unneeded_route(
        FakeRoute(
            resource_type="font",
            url="https://www.autozone.com/assets/fonts/site-font.woff2",
        )
    )
    await acquisition_browser_runtime._block_unneeded_route(
        FakeRoute(
            resource_type="script",
            url="https://geo.captcha-delivery.com/captcha/?initialCid=abc",
        )
    )

    assert events == [
        "continue:font:https://www.autozone.com/assets/fonts/site-font.woff2",
        "continue:script:https://geo.captcha-delivery.com/captcha/?initialCid=abc",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_block_unneeded_route_ssrf_guard_runs_before_challenge_tokens() -> None:
    """Challenge-vendor URL tokens must not bypass the SSRF host guard.

    The guard previously ran AFTER the protected-challenge early-return, so a
    URL like http://169.254.169.254/latest/meta-data/?akamai=1 was continued
    without host validation — a subresource SSRF bypass.
    """
    events: list[str] = []

    class FakeRoute:
        def __init__(self, *, resource_type: str, url: str) -> None:
            self.request = SimpleNamespace(resource_type=resource_type, url=url)

        async def abort(self) -> None:
            events.append(f"abort:{self.request.url}")

        async def continue_(self) -> None:
            events.append(f"continue:{self.request.url}")

    for url in (
        "http://169.254.169.254/latest/meta-data/?akamai=1",
        "http://127.0.0.1:6379/datadome",
        "http://10.0.0.5/internal?x=captcha-delivery",
    ):
        await acquisition_browser_runtime._block_unneeded_route(
            FakeRoute(resource_type="script", url=url)
        )
    # Legit public challenge vendor URL still flows through.
    await acquisition_browser_runtime._block_unneeded_route(
        FakeRoute(
            resource_type="script",
            url="https://geo.captcha-delivery.com/captcha/?initialCid=abc",
        )
    )

    assert events == [
        "abort:http://169.254.169.254/latest/meta-data/?akamai=1",
        "abort:http://127.0.0.1:6379/datadome",
        "abort:http://10.0.0.5/internal?x=captcha-delivery",
        "continue:https://geo.captcha-delivery.com/captcha/?initialCid=abc",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_block_unneeded_route_aborts_third_party_trackers() -> None:
    events: list[str] = []

    class FakeRoute:
        def __init__(self, *, resource_type: str, url: str) -> None:
            self.request = SimpleNamespace(resource_type=resource_type, url=url)

        async def abort(self) -> None:
            events.append(f"abort:{self.request.resource_type}:{self.request.url}")

        async def continue_(self) -> None:
            events.append(f"continue:{self.request.resource_type}:{self.request.url}")

    await acquisition_browser_runtime._block_unneeded_route(
        FakeRoute(
            resource_type="script",
            url="https://tr.snapchat.com/p?pid=abc",
        )
    )

    assert events == ["abort:script:https://tr.snapchat.com/p?pid=abc"]
