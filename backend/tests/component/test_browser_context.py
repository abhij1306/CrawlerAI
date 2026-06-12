from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.fetch import fetch_context as crawl_fetch_runtime

from app.models.domain_memory import DomainCookieMemory
from app.services.acquisition import browser_identity, browser_storage_state
from app.services.acquisition import browser_proxy_bridge
from app.services.acquisition import cookie_store
from app.services.acquisition import host_protection_memory
from app.services.acquisition import browser_pool as acquisition_browser_pool
from app.services.acquisition.browser_readiness import analyze_html
from app.services.acquisition.browser_proxy_config import build_browser_proxy_config
from app.services.acquisition import browser_runtime as acquisition_browser_runtime
from app.services.acquisition.runtime import (
    has_extractable_dom_content_detail_signals,
    has_extractable_listing_signals,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_utils import is_special_use_domain, normalize_domain


_PASSWORD_KEY = "pass" + "word"


def _credential_url(
    *,
    scheme: str,
    username: str,
    secret: str,
    host: str,
    port: int | None = None,
    path: str = "",
) -> str:
    port_suffix = f":{port}" if port is not None else ""
    path_suffix = path if not path or path.startswith("/") else f"/{path}"
    return f"{scheme}://{username}:{secret}@{host}{port_suffix}{path_suffix}"


def _authority_with_credentials(*, username: str, secret: str, host: str, port: int) -> str:
    return f"{username}:{secret}@{host}:{port}"


def _masked_proxy_display(*, scheme: str, host: str, port: int) -> str:
    return f"{scheme}://***:***@{host}:{port}"


def _secret_mapping(secret: str) -> dict[str, str]:
    return {_PASSWORD_KEY: secret}


def _context_spec(
    context_options: dict[str, object] | None = None,
    *,
    init_script: str | None = None,
) -> browser_identity.PlaywrightContextSpec:
    return browser_identity.PlaywrightContextSpec(
        context_options=dict(context_options or {}),
        init_script=init_script,
    )


@pytest.mark.component
def test_chromium_browser_binary_is_labeled_chromium() -> None:
    assert acquisition_browser_pool._resolve_browser_binary("chromium") == (
        None,
        "chromium",
    )



@pytest.mark.component
def test_content_detail_signals_accept_meaningful_body_without_paragraph() -> None:
    analysis = analyze_html(
        """
        <html><body><main>
          <h1>Forum Thread</h1>
          <div class="post-body">This answer explains the workaround with enough detail to be useful for extraction.</div>
        </main></body></html>
        """
    )

    assert has_extractable_dom_content_detail_signals(analysis) is True


@pytest.mark.component
def test_content_detail_signals_reject_empty_and_heading_only_body() -> None:
    empty_analysis = analyze_html(
        "<html><body><main><h1>Thread</h1><div></div></main></body></html>"
    )
    heading_only_analysis = analyze_html(
        "<html><body><main><h1>Thread</h1><div>Thread</div></main></body></html>"
    )

    assert has_extractable_dom_content_detail_signals(empty_analysis) is False
    assert has_extractable_dom_content_detail_signals(heading_only_analysis) is False


@pytest.mark.component
def test_content_detail_signals_accept_common_content_descendant() -> None:
    analysis = analyze_html(
        """
        <html><body><main>
          <h1>Thread</h1>
          <section class="post-body"><span>Useful answer</span></section>
        </main></body></html>
        """
    )

    assert has_extractable_dom_content_detail_signals(analysis) is True


@pytest.mark.component
def test_listing_signals_detect_item_list_and_ignore_non_list_type() -> None:
    item_list_html = """
    <html><body><script type="application/ld+json">
      {"@context":"https://schema.org","@type":"ItemList","itemListElement":[]}
    </script></body></html>
    """
    non_list_html = """
    <html><body><script type="application/ld+json">
      {"@context":"https://schema.org","@type":"Article","headline":"News"}
    </script></body></html>
    """

    assert has_extractable_listing_signals(item_list_html) is True
    assert has_extractable_listing_signals(non_list_html) is False


@pytest.mark.component
def test_listing_signals_respect_typed_item_threshold(monkeypatch) -> None:
    monkeypatch.setattr(crawler_runtime_settings, "listing_min_items", 3)

    def typed_products(count: int) -> str:
        payloads = "\n".join(
            '<script type="application/ld+json">{"@type":"Product","name":"Item"}</script>'
            for _ in range(count)
        )
        return f"<html><body>{payloads}</body></html>"

    assert has_extractable_listing_signals(typed_products(2)) is False
    assert has_extractable_listing_signals(typed_products(3)) is True
    assert has_extractable_listing_signals(typed_products(4)) is True


@pytest.mark.component
def test_listing_signals_detect_list_item_type() -> None:
    html = """
    <html><body><script type="application/ld+json">
      {"@context":"https://schema.org","@type":"ListItem","name":"Result"}
    </script></body></html>
    """

    assert has_extractable_listing_signals(html) is True



@pytest.mark.component
def test_acquisition_package_exports_runtime_expand_function() -> None:
    from app.services import acquisition

    assert (
        acquisition.expand_all_interactive_elements
        is acquisition_browser_runtime.expand_all_interactive_elements
    )



@pytest.mark.component
def test_is_special_use_domain_ignores_ports() -> None:
    assert is_special_use_domain("localhost:3000") is True
    assert is_special_use_domain("http://localhost:3000/products/widget") is True


@pytest.mark.component
def test_is_special_use_domain_treats_test_suffix_as_special_use() -> None:
    assert is_special_use_domain("https://api.example.test/path") is True


@pytest.mark.component
def test_normalize_domain_strips_credentials() -> None:
    assert (
        normalize_domain(
            _credential_url(
                scheme="https",
                username="user",
                secret="pass",
                host="example.com",
                path="/path",
            )
        )
        == "example.com"
    )


@pytest.mark.component
def test_normalize_domain_preserves_non_standard_port() -> None:
    assert normalize_domain("https://example.com:8443/path") == "example.com:8443"


@pytest.mark.component
def test_normalize_domain_strips_standard_https_port() -> None:
    assert normalize_domain("https://example.com:443/path") == "example.com"


@pytest.mark.component
def test_normalize_domain_handles_domain_only_input() -> None:
    assert normalize_domain("example.com") == "example.com"


@pytest.mark.component
def test_normalize_domain_strips_credentials_without_password() -> None:
    assert normalize_domain("https://user@example.com/path") == "example.com"



@pytest.mark.asyncio
@pytest.mark.component
async def test_read_socks5_response_rejects_unexpected_upstream_version() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(bytes([4, 0, 0, 1, 127, 0, 0, 1, 0, 80]))
    reader.feed_eof()

    with pytest.raises(ValueError, match="Unexpected upstream SOCKS response version"):
        await browser_proxy_bridge._read_socks5_response(reader)


@pytest.mark.asyncio
@pytest.mark.component
async def test_read_client_request_rejects_missing_no_auth_method() -> None:
    class _Writer:
        def __init__(self) -> None:
            self.data = bytearray()

        def write(self, data: bytes) -> None:
            self.data.extend(data)

        async def drain(self) -> None:
            return None

    reader = asyncio.StreamReader()
    reader.feed_data(bytes([5, 1, 2]))
    reader.feed_eof()
    writer = _Writer()

    with pytest.raises(ValueError, match="no-auth method"):
        await browser_proxy_bridge._read_client_request(reader, writer)

    assert bytes(writer.data) == bytes([5, 0xFF])


@pytest.mark.asyncio
@pytest.mark.component
async def test_read_client_request_rebuilds_validated_connect_request() -> None:
    class _Writer:
        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

    raw_request = bytes([5, 1, 0, 5, 1, 0, 3, 11]) + b"example.com" + bytes([1, 187])
    reader = asyncio.StreamReader()
    reader.feed_data(raw_request)
    reader.feed_eof()

    request = await browser_proxy_bridge._read_client_request(reader, _Writer())

    assert request.to_upstream_bytes() == raw_request[3:]


@pytest.mark.asyncio
@pytest.mark.component
async def test_socks5_auth_bridge_start_is_singleflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_calls = 0

    class _Socket:
        def getsockname(self):
            return ("127.0.0.1", 41001)

    class _Server:
        sockets = [_Socket()]

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def _fake_start_server(*_args, **_kwargs):
        nonlocal start_calls
        start_calls += 1
        await asyncio.sleep(0)
        return _Server()

    monkeypatch.setattr(
        browser_proxy_bridge.asyncio, "start_server", _fake_start_server
    )
    bridge = browser_proxy_bridge.Socks5AuthBridge(
        browser_proxy_bridge.Socks5UpstreamProxy(
            scheme="socks5",
            host="proxy.example",
            port=1080,
            username="user",
            **_secret_mapping("pass"),
        )
    )

    first, second = await asyncio.gather(bridge.start(), bridge.start())
    await bridge.close()

    assert first == second == "socks5://127.0.0.1:41001"
    assert start_calls == 1



@pytest.mark.component
def test_browser_storage_state_persist_policy_rejects_challenge_shell_without_ready_probe() -> (
    None
):
    assert (
        acquisition_browser_runtime._browser_storage_state_is_persistable(
            blocked=False,
            finalized_diagnostics={
                "browser_outcome": "usable_content",
                "challenge_provider_hits": ["perimeterx"],
                "readiness_probes": [
                    {
                        "is_ready": False,
                    }
                ],
            },
        )
        is False
    )



@pytest.mark.asyncio
@pytest.mark.component
async def test_load_storage_state_for_run_ignores_invalid_run_id() -> None:
    assert await cookie_store.load_storage_state_for_run("invalid") is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_storage_state_for_run_scopes_by_browser_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()

    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "chromium-session",
                    "value": "1",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        browser_engine="chromium",
    )
    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "real-chrome-session",
                    "value": "2",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        browser_engine="real_chrome",
    )

    chromium_state = await cookie_store.load_storage_state_for_run(
        77,
        browser_engine="chromium",
    )
    real_chrome_state = await cookie_store.load_storage_state_for_run(
        77,
        browser_engine="real_chrome",
    )

    assert chromium_state == {
        "cookies": [
            {
                "name": "chromium-session",
                "value": "1",
                "domain": ".example.com",
                "path": "/",
            }
        ],
        "origins": [],
    }
    assert real_chrome_state == {
        "cookies": [
            {
                "name": "real-chrome-session",
                "value": "2",
                "domain": ".example.com",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_run_replaces_existing_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()

    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "stale",
                    "value": "1",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [{"name": "old", "value": "1"}],
                }
            ],
        },
    )
    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "fresh",
                    "value": "2",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [{"name": "new", "value": "2"}],
                }
            ],
        },
    )

    assert await cookie_store.load_storage_state_for_run(77) == {
        "cookies": [
            {
                "name": "fresh",
                "value": "2",
                "domain": ".example.com",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_run_keeps_cache_clean_when_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()

    def _raise_write(path, storage_state) -> None:
        del path, storage_state
        raise OSError("write failed")

    monkeypatch.setattr(cookie_store, "_write_storage_state_file", _raise_write)

    with pytest.raises(OSError, match="write failed"):
        await cookie_store.persist_storage_state_for_run(
            77,
            {
                "cookies": [
                    {
                        "name": "fresh",
                        "value": "2",
                        "domain": ".example.com",
                        "path": "/",
                    }
                ],
                "origins": [],
            },
        )

    assert await cookie_store.load_storage_state_for_run(77) is None


@pytest.mark.component
def test_write_storage_state_file_retries_permission_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    path = tmp_path / "state.json"
    attempts: list[int] = []
    original_replace = Path.replace

    def _flaky_replace(self: Path, target: Path) -> Path:
        attempts.append(1)
        if len(attempts) == 1:
            raise PermissionError("busy")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _flaky_replace)
    monkeypatch.setattr(cookie_store.time, "sleep", lambda _seconds: None)

    cookie_store._write_storage_state_file(
        path,
        {"cookies": [], "origins": []},
    )

    assert path.exists()
    assert len(attempts) == 2


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
async def test_shared_browser_runtime_launches_http_proxy_directly(
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
                "server": "http://31.58.9.4:6077",
                "username": "user-name",
                **_secret_mapping("pass-word"),
            },
        }
    ]


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
        }
    ]


@pytest.mark.component
def test_display_proxy_masks_authenticated_proxy_credentials() -> None:
    assert (
        acquisition_browser_runtime._display_proxy(
            _credential_url(
                scheme="http",
                username="user-name",
                secret="pass-word",
                host="31.58.9.4",
                port=6077,
            )
        )
        == _masked_proxy_display(scheme="http", host="31.58.9.4", port=6077)
    )


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

    await asyncio.wait_for(_acquire_again(), timeout=1.0)
    assert close_calls == 2


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_browser_runtime_close_bounds_hung_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocker = asyncio.Event()

    class FakeBrowser:
        async def close(self) -> None:
            await blocker.wait()

    class FakePlaywright:
        async def stop(self) -> None:
            await blocker.wait()

    class FakeBridge:
        async def close(self) -> None:
            await blocker.wait()

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
    # Eviction close now runs in a background task; yield to let it complete.
    await asyncio.sleep(0)
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
    # Eviction close now runs in a background task; yield to let it complete.
    await asyncio.sleep(0)
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
    assert "--disable-component-update" not in crawler_runtime_settings.browser_launch_args
    assert "--disable-blink-features=AutomationControlled" not in crawler_runtime_settings.browser_launch_args


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_commits_owned_session(
    db_session,
    monkeypatch,
) -> None:
    session_factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    monkeypatch.setattr(cookie_store, "SessionLocal", session_factory)
    domain = f"owned-session-{uuid4().hex}.example.com"
    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
    )

    rows = await cookie_store.list_domain_cookie_memory(domain)

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["domain"] == domain


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_persists_test_domains(
    db_session,
) -> None:
    domain = f"owned-session-{uuid4().hex}.example.test"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["domain"] == domain
    assert loaded is not None


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_strips_null_bytes(db_session) -> None:
    domain = f"null-byte-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc\x00def",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": f"https://{domain}",
                    "localStorage": [
                        {"name": "cart", "value": '{"id":"123\x00"}'},
                    ],
                }
            ],
        },
        session=db_session,
    )

    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert saved is True
    assert loaded is not None
    assert loaded["cookies"][0]["value"] == "abcdef"
    assert loaded["origins"] == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_keeps_engine_specific_rows(
    db_session,
) -> None:
    domain = f"engine-scoped-{uuid4().hex}.example.com"

    chromium_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "chromium-session",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="chromium",
    )
    real_chrome_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "real-chrome-session",
                    "value": "2",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="real_chrome",
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    chromium_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="chromium",
    )
    real_chrome_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="real_chrome",
    )

    assert chromium_saved is True
    assert real_chrome_saved is True
    assert len(rows) == 2
    assert {str(row["browser_engine"]) for row in rows} == {"chromium", "real_chrome"}
    assert chromium_state == {
        "cookies": [
            {
                "name": "chromium-session",
                "value": "1",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }
    assert real_chrome_state == {
        "cookies": [
            {
                "name": "real-chrome-session",
                "value": "2",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_persists_localhost_with_port(
    db_session,
) -> None:
    domain = "http://localhost:3000/products/widget"

    saved = await cookie_store.persist_storage_state_for_domain(
        domain,
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": "localhost",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(
        "localhost:3000", session=db_session
    )
    all_rows = await cookie_store.list_domain_cookie_memory(session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(
        "localhost:3000", session=db_session
    )

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["domain"] == "localhost:3000"
    assert any(row["domain"] == "localhost:3000" for row in all_rows)
    assert loaded is not None


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_accepts_iterable_storage_rows(
    db_session,
) -> None:
    domain = f"iterable-state-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": (
                {
                    "name": "session",
                    "value": "abc",
                    "domain": f".{domain}",
                    "path": "/",
                },
            ),
            "origins": (
                {
                    "origin": f"https://{domain}",
                    "localStorage": ({"name": "consent", "value": "accepted"},),
                },
            ),
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["cookie_count"] == 1
    assert rows[0]["origin_count"] == 0
    assert loaded == {
        "cookies": [
            {
                "name": "session",
                "value": "abc",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_export_cookie_header_for_domain_dedupes_cookie_names(
    db_session,
) -> None:
    domain = f"handoff-cookie-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "root",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "session",
                    "value": "product",
                    "domain": f".{domain}",
                    "path": "/products",
                },
                {
                    "name": "_px3",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "consent",
                    "value": "yes",
                    "domain": f".{domain}",
                    "path": "/",
                },
            ],
            "origins": [
                {
                    "origin": f"https://{domain}",
                    "localStorage": [{"name": "consent", "value": "accepted"}],
                }
            ],
        },
        session=db_session,
        browser_engine="real_chrome",
    )

    header = await cookie_store.export_cookie_header_for_domain(
        f"https://{domain}/products/widget",
        session=db_session,
        browser_engine="real_chrome",
    )

    assert saved is True
    assert header == "session=product; consent=yes"


@pytest.mark.asyncio
@pytest.mark.component
async def test_export_cookie_header_for_domain_does_not_match_path_prefixes(
    db_session,
) -> None:
    domain = f"path-prefix-{uuid4().hex}.example.com"

    await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/foo",
        {
            "cookies": [
                {
                    "name": "prefix-only",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/foo",
                },
                {
                    "name": "nested",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/foo/bar",
                },
            ],
            "origins": [],
        },
        session=db_session,
    )

    header = await cookie_store.export_cookie_header_for_domain(
        f"https://{domain}/foobar",
        session=db_session,
    )

    assert header is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_keeps_patchright_isolated(
    db_session,
) -> None:
    domain = f"patchright-engine-{uuid4().hex}.example.com"

    chromium_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "chromium-session",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="chromium",
    )
    patchright_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "patchright-session",
                    "value": "2",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="patchright",
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    chromium_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="chromium",
    )
    patchright_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="patchright",
    )

    assert chromium_saved is True
    assert patchright_saved is True
    assert len(rows) == 2
    assert {str(row["browser_engine"]) for row in rows} == {"chromium", "patchright"}
    assert chromium_state == {
        "cookies": [
            {
                "name": "chromium-session",
                "value": "1",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }
    assert patchright_state == {
        "cookies": [
            {
                "name": "patchright-session",
                "value": "2",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_host_protection_policy_tracks_patchright_as_browser_lane(
    db_session,
) -> None:
    url = f"https://patchright-policy-{uuid4().hex}.example.com/products/widget"

    blocked_policy = await host_protection_memory.note_host_hard_block(
        url,
        method="browser:patchright",
        session=db_session,
    )
    success_policy = await host_protection_memory.note_host_usable_fetch(
        url,
        method="browser:patchright",
        session=db_session,
    )

    assert blocked_policy.request_blocked is False
    assert blocked_policy.patchright_blocked is True
    assert blocked_policy.last_block_method == "browser:patchright"
    assert success_policy.patchright_success is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_host_protection_policy_maps_legacy_browser_block_to_patchright(
    db_session,
) -> None:
    url = f"https://legacy-browser-policy-{uuid4().hex}.example.com/products/widget"

    blocked_policy = await host_protection_memory.note_host_hard_block(
        url,
        method="browser",
        session=db_session,
    )

    assert blocked_policy.request_blocked is False
    assert blocked_policy.patchright_blocked is True
    assert blocked_policy.last_block_method == "browser"


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_storage_state_for_domain_filters_existing_challenge_state(
    db_session,
) -> None:
    domain = f"poisoned-{uuid4().hex}.example.com"
    db_session.add(
        DomainCookieMemory(
            domain=domain,
            storage_state={
                "cookies": [
                    {
                        "name": "_pxvid",
                        "value": "challenge",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                    {
                        "name": "session",
                        "value": "safe",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                    {
                        "name": "datadome",
                        "value": "challenge-token",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                    {
                        "name": "_abck",
                        "value": "akamai-token",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                    {
                        "name": "__cf_bm",
                        "value": "cloudflare-token",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                    {
                        "name": "analytics",
                        "value": "bot_management:captcha",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                ],
                "origins": [
                    {
                        "origin": f"https://{domain}",
                        "localStorage": [
                            {"name": "PXapp_px_hvd", "value": "challenge"},
                            {"name": "safe-key", "value": "datadome blocked"},
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            },
            state_fingerprint="poisoned",
        )
    )
    await db_session.commit()

    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert loaded == {
        "cookies": [
            {
                "name": "session",
                "value": "safe",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_list_domain_cookie_memory_counts_stored_entries(db_session) -> None:
    domain = f"stored-count-{uuid4().hex}.example.com"
    db_session.add(
        DomainCookieMemory(
            domain=domain,
            storage_state={
                "cookies": [
                    {
                        "name": "session",
                        "value": "safe",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                    "legacy-cookie-row",
                ],
                "origins": [
                    {"origin": f"https://{domain}", "localStorage": []},
                    "legacy-origin-row",
                ],
            },
            state_fingerprint="stored-count",
        )
    )
    await db_session.commit()

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)

    assert rows[0]["cookie_count"] == 2
    assert rows[0]["origin_count"] == 2


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_domain_rejects_challenge_only_state(
    db_session,
) -> None:
    domain = f"challenge-only-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "_px2",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "pxcts",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "datadome",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
            ],
            "origins": [
                {
                    "origin": f"https://{domain}",
                    "localStorage": [
                        {"name": "PXapp_px_fp", "value": "challenge"},
                        {"name": "safe-key", "value": "captcha page"},
                    ],
                }
            ],
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert saved is False
    assert rows == []
    assert loaded is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_storage_state_for_domain_drops_origin_shell_when_local_storage_filters_empty(
    db_session,
) -> None:
    domain = f"origin-shell-{uuid4().hex}.example.com"
    db_session.add(
        DomainCookieMemory(
            domain=domain,
            storage_state={
                "cookies": [
                    {
                        "name": "session",
                        "value": "safe",
                        "domain": f".{domain}",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": f"https://{domain}",
                        "localStorage": [
                            {"name": "PXapp_px_fp", "value": "challenge"},
                        ],
                    }
                ],
            },
            state_fingerprint="origin-shell",
        )
    )
    await db_session.commit()

    loaded = await cookie_store.load_storage_state_for_domain(
        domain, session=db_session
    )

    assert loaded == {
        "cookies": [
            {
                "name": "session",
                "value": "safe",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


# ---------------------------------------------------------------------------
# Native-context verification tests
# ---------------------------------------------------------------------------


@pytest.mark.component
class TestNativeContextContract:
    """Verify that the native browser identity emits a clean Playwright context."""

    def test_native_context_deheadlessifies_user_agent(self) -> None:
        # Headless Chromium leaks a "HeadlessChrome" UA token that bot-defense
        # vendors block on sight. The context UA must present as plain Chrome.
        opts = browser_identity.build_playwright_context_options(
            browser_major_version=145
        )
        user_agent = str(opts.get("user_agent") or "")
        assert "HeadlessChrome" not in user_agent
        assert "Chrome/145" in user_agent

    def test_native_context_emits_coherent_client_hints(self) -> None:
        opts = browser_identity.build_playwright_context_options(
            browser_major_version=145
        )
        headers = opts.get("extra_http_headers") or {}
        assert headers.get("sec-ch-ua-mobile") == "?0"
        assert "Google Chrome" in str(headers.get("sec-ch-ua") or "")
        assert '"145"' in str(headers.get("sec-ch-ua") or "")

    def test_native_context_merges_locality_headers_with_client_hints(self) -> None:
        opts = browser_identity.build_playwright_context_options(
            browser_major_version=145,
            locality_profile={
                "browser_context_profile": {
                    "extra_http_headers": {"Accept-Language": "en-US"}
                }
            },
        )
        headers = opts.get("extra_http_headers") or {}
        assert headers["Accept-Language"] == "en-US"
        assert headers.get("sec-ch-ua-mobile") == "?0"
        assert "Google Chrome" in str(headers.get("sec-ch-ua") or "")

    def test_native_context_uses_no_viewport_true(self) -> None:
        opts = browser_identity.build_playwright_context_options()
        assert opts.get("no_viewport") is True

    def test_native_context_has_no_init_script(self) -> None:
        spec = browser_identity.build_playwright_context_spec()
        assert spec.init_script is None

    def test_clear_browser_identity_cache_is_noop(self) -> None:
        browser_identity.clear_browser_identity_cache()
