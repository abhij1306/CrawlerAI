"""test_browser_context cases split by public behavior."""

from __future__ import annotations

from tests.component.browser_context_test_support import (
    _credential_url,
    _secret_mapping,
    acquisition_browser_pool,
    analyze_extractable_content,
    analyze_html,
    asyncio,
    browser_proxy_bridge,
    browser_settle,
    crawler_runtime_settings,
    detail_expansion_extractability,
    is_special_use_domain,
    normalize_domain,
    pytest,
)


@pytest.mark.component
def test_chromium_browser_binary_is_labeled_chromium() -> None:
    assert acquisition_browser_pool._resolve_browser_binary("chromium") == (
        None,
        "chromium",
    )


@pytest.mark.component
def test_meaningful_detail_signals_accept_body_without_paragraph() -> None:
    analysis = analyze_html(
        """
        <html><body><main>
          <h1>Forum Thread</h1>
          <div class="post-body">This answer explains the workaround with enough detail to be useful for extraction.</div>
        </main></body></html>
        """
    )

    assert (
        analyze_extractable_content(analysis.html, analysis=analysis).meaningful_detail
        is True
    )


@pytest.mark.component
def test_detail_extractability_reuses_readiness_document() -> None:
    analysis = analyze_html(
        "<html><body><main><h1>Trail Shoe</h1><p data-price='49'>$49.00</p></main></body></html>"
    )

    result = detail_expansion_extractability(
        document=analysis.document,
        surface="ecommerce_detail",
        requested_fields=["title", "price"],
    )

    assert result["verified"] is True
    assert result["matched_requested_fields"] == ["price", "title"]


@pytest.mark.asyncio
@pytest.mark.component
@pytest.mark.parametrize(
    ("snapshots", "expected_parse_count"),
    (
        (["<html>A</html>", "<html>A</html>"], 1),
        (["<html>A</html>", "<html>B</html>"], 2),
    ),
)
async def test_browser_settle_parses_once_per_unique_snapshot(
    monkeypatch,
    snapshots: list[str],
    expected_parse_count: int,
) -> None:
    parse_count = 0
    original_analyze_html = browser_settle.analyze_html

    def counting_analyze_html(html: str):
        nonlocal parse_count
        parse_count += 1
        return original_analyze_html(html)

    class _Page:
        async def wait_for_function(self, *_args, **_kwargs) -> None:
            return None

    html_reads = iter(snapshots)
    probe_count = 0

    async def get_page_html_impl(_page) -> str:
        return next(html_reads)

    async def probe_browser_readiness(_page, **_kwargs) -> dict[str, object]:
        nonlocal probe_count
        probe_count += 1
        return {
            "is_ready": probe_count > 1,
            "structured_data_present": False,
        }

    monkeypatch.setattr(browser_settle, "analyze_html", counting_analyze_html)
    monkeypatch.setattr(
        crawler_runtime_settings,
        "browser_navigation_optimistic_wait_ms",
        100,
    )

    result = await browser_settle.settle_browser_page(
        _Page(),
        url="https://example.test/table",
        surface="table",
        requested_fields=None,
        timeout_seconds=1,
        readiness_override=None,
        readiness_policy={},
        phase_timings_ms={},
        crawler_runtime_settings=crawler_runtime_settings,
        get_page_html_impl=get_page_html_impl,
        probe_browser_readiness=probe_browser_readiness,
        wait_for_listing_readiness=None,
        expand_detail_content_if_needed=None,
        append_readiness_probe=lambda probes, **probe: probes.append(probe),
        elapsed_ms=lambda _started: 0,
    )

    assert parse_count == expected_parse_count
    assert result[-2] == snapshots[-1]


@pytest.mark.component
def test_meaningful_detail_signals_reject_empty_and_heading_only_body() -> None:
    empty_analysis = analyze_html(
        "<html><body><main><h1>Thread</h1><div></div></main></body></html>"
    )
    heading_only_analysis = analyze_html(
        "<html><body><main><h1>Thread</h1><div>Thread</div></main></body></html>"
    )

    assert (
        analyze_extractable_content(
            empty_analysis.html, analysis=empty_analysis
        ).meaningful_detail
        is False
    )
    assert (
        analyze_extractable_content(
            heading_only_analysis.html, analysis=heading_only_analysis
        ).meaningful_detail
        is False
    )


@pytest.mark.component
def test_meaningful_detail_signals_accept_common_descendant() -> None:
    analysis = analyze_html(
        """
        <html><body><main>
          <h1>Thread</h1>
          <section class="post-body"><span>Useful answer</span></section>
        </main></body></html>
        """
    )

    assert (
        analyze_extractable_content(analysis.html, analysis=analysis).meaningful_detail
        is True
    )


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

    assert analyze_extractable_content(item_list_html).listing is True
    assert analyze_extractable_content(non_list_html).listing is False


@pytest.mark.component
def test_listing_signals_respect_typed_item_threshold(monkeypatch) -> None:
    monkeypatch.setattr(crawler_runtime_settings, "listing_min_items", 3)

    def typed_products(count: int) -> str:
        payloads = "\n".join(
            '<script type="application/ld+json">{"@type":"Product","name":"Item"}</script>'
            for _ in range(count)
        )
        return f"<html><body>{payloads}</body></html>"

    assert analyze_extractable_content(typed_products(2)).listing is False
    assert analyze_extractable_content(typed_products(3)).listing is True
    assert analyze_extractable_content(typed_products(4)).listing is True


@pytest.mark.component
def test_listing_signals_detect_list_item_type() -> None:
    html = """
    <html><body><script type="application/ld+json">
      {"@context":"https://schema.org","@type":"ListItem","name":"Result"}
    </script></body></html>
    """

    assert analyze_extractable_content(html).listing is True


@pytest.mark.component
def test_is_special_use_domain_ignores_ports() -> None:
    assert is_special_use_domain("localhost:3001") is True
    assert is_special_use_domain("http://localhost:3001/products/widget") is True


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
    assert request.validation_url() == "http://example.com:443/"
    assert request.to_upstream_bytes(host="93.184.216.34") == (
        bytes([5, 1, 0, 1, 93, 184, 216, 34, 1, 187])
    )


@pytest.mark.component
def test_socks5_proxy_without_credentials_still_uses_safety_bridge() -> None:
    upstream = browser_proxy_bridge.parse_socks5_upstream_proxy(
        "socks5://proxy.example:1080"
    )

    assert upstream is not None
    assert upstream.host == "proxy.example"
    assert upstream.username == ""


@pytest.mark.asyncio
@pytest.mark.component
async def test_direct_socks_bridge_rejects_private_target_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Writer:
        def __init__(self) -> None:
            self.data = bytearray()

        def write(self, data: bytes) -> None:
            self.data.extend(data)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def _must_not_connect(*_args, **_kwargs):
        raise AssertionError("private target reached connect")

    reader = asyncio.StreamReader()
    reader.feed_data(bytes([5, 1, 0, 5, 1, 0, 1, 127, 0, 0, 1, 0, 80]))
    reader.feed_eof()
    writer = _Writer()
    bridge = browser_proxy_bridge.Socks5AuthBridge()
    monkeypatch.setattr(bridge, "_open_direct", _must_not_connect)

    await bridge._handle_client(reader, writer)

    assert bytes(writer.data[:2]) == bytes([5, 0])
    assert bytes(writer.data[-10:]) == browser_proxy_bridge._failure_response(1)


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
