from __future__ import annotations

# ruff: noqa: F403, F405
from .product_intelligence_test_support import *


@pytest.mark.component
def test_product_intelligence_request_accepts_max_sources_and_url_aliases() -> None:
    request = ProductIntelligenceDiscoveryRequest.model_validate(
        {
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/1.html",
                    "data": {"title": "Wallet"},
                }
            ],
            "options": {
                "max_sources": 17,
                "max_urls": 1,
                "search_provider": "serpapi",
            },
        }
    )

    assert request.options.max_source_products == 17
    assert request.options.max_candidates_per_product == 1


@pytest.mark.component
def test_product_intelligence_search_result_snapshot_keeps_description() -> None:
    snapshot = extract_search_result_snapshot(
        {
            "title": "Varick Slim Straight Jean",
            "snippet": "Garment-dyed denim with a slim straight fit.",
            "price": "$125.00",
        },
        url="https://www.ralphlauren.com/p/varick.html",
        domain="ralphlauren.com",
    )

    assert snapshot["description"] == "Garment-dyed denim with a slim straight fit."
    assert snapshot["price"] == pytest.approx(125.0)
    assert snapshot["currency"] == "USD"


@pytest.mark.component
def test_product_intelligence_search_result_snapshot_infers_known_brand_from_compact_domain() -> (
    None
):
    snapshot = extract_search_result_snapshot(
        {"title": "Bifold RFID Wallet", "snippet": "Leather wallet."},
        url="https://www.kennethcole.com/collections/kenneth-cole-reaction",
        domain="kennethcole.com",
    )

    assert snapshot["brand"] == "kenneth cole"
    assert snapshot["normalized_brand"] == "kenneth cole"


@pytest.mark.component
def test_product_intelligence_search_result_snapshot_tries_brand_from_title_marker() -> (
    None
):
    snapshot = extract_search_result_snapshot(
        {
            "title": "Crown & Ivy™ Hydrangea Vase",
            "snippet": "Ceramic vase for spring decor.",
            "price": "$39.99",
        },
        url="https://www.belk.com/p/crown-ivy-hydrangea-vase/760161676226SPH0073IJ.html",
        domain="belk.com",
    )

    assert snapshot["brand"] == "Crown & Ivy™"
    assert snapshot["normalized_brand"] == "crown ivy"
    assert snapshot["currency"] == "USD"


@pytest.mark.component
def test_product_intelligence_settings_accepts_serp_api_key_alias() -> None:
    settings = ProductIntelligenceSettings(_env_file=None, SERP_API_KEY="serp-secret")

    assert settings.serpapi_key == "serp-secret"


@pytest.mark.component
def test_product_intelligence_settings_default_provider_is_serpapi() -> None:
    settings = ProductIntelligenceSettings(_env_file=None)

    assert settings.default_search_provider == "serpapi"


@pytest.mark.component
def test_product_intelligence_settings_accepts_google_native_provider() -> None:
    settings = ProductIntelligenceSettings(
        _env_file=None,
        default_search_provider="google_native",
    )

    assert settings.default_search_provider == "google_native"


@pytest.mark.component
def test_product_intelligence_settings_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        ProductIntelligenceSettings(_env_file=None, default_search_provider="bogus")


@pytest.mark.component
def test_product_intelligence_settings_rejects_legacy_duckduckgo_provider() -> None:
    with pytest.raises(ValueError):
        ProductIntelligenceSettings(
            _env_file=None, default_search_provider="duckduckgo"
        )


@pytest.mark.component
def test_parse_google_native_results_extracts_redirect_targets() -> None:
    html = """
    <html><body>
      <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget&sa=U"><h3>Widget</h3></a>
      <a href="https://www.google.com/preferences"><h3>Settings</h3></a>
    </body></html>
    """

    results = parse_google_native_results(html, limit=5)

    assert results[0].url == "https://shop.example.com/p/widget"
    assert results[0].payload["provider"] == "google_native"


@pytest.mark.component
def test_parse_google_native_results_skips_anchors_without_h3() -> None:
    """Non-product anchors without h3 must be ignored."""
    html = """
    <html><body>
      <a href="https://www.amazon.com/sponsored">Sponsored amazon link</a>
      <a href="https://en.wikipedia.org/wiki/Widget">People also ask: what is a widget?</a>
      <a href="https://www.nike.com/t/run-defy-womens-road-running-shoes/HM9593">
        Nike Run Defy Women's Road Running Shoes
      </a>
      <div class="result">
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget&sa=U">
          <h3>Widget Pro Edition</h3>
        </a>
      </div>
    </body></html>
    """

    results = parse_google_native_results(html, limit=5)

    assert [result.url for result in results] == [
        "https://www.nike.com/t/run-defy-womens-road-running-shoes/HM9593",
        "https://shop.example.com/p/widget",
    ]


@pytest.mark.component
def test_parse_google_native_results_prefers_h3_over_anchor_text() -> None:
    html = """
    <html><body>
      <div class="result">
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget&sa=U">
          <h3>Widget Pro Edition</h3>
          <span>shop.example.com &rsaquo; p &rsaquo; widget</span>
        </a>
      </div>
    </body></html>
    """

    results = parse_google_native_results(html, limit=5)

    assert results[0].payload["title"] == "Widget Pro Edition"


@pytest.mark.component
def test_parse_google_native_results_extracts_thumbnail_from_result_container() -> None:
    html = """
    <html><body>
      <div class="result-block">
        <img src="https://example.com/thumb.jpg" alt="thumb">
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget&sa=U">
          <h3>Widget</h3>
        </a>
      </div>
    </body></html>
    """

    results = parse_google_native_results(html, limit=5)

    assert results[0].payload["thumbnail"] == "https://example.com/thumb.jpg"


@pytest.mark.component
def test_google_native_block_detection_flags_google_unusual_traffic_page() -> None:
    html = """
    <html><body>
      <p>Our systems have detected unusual traffic from your computer network.</p>
      <p>This page checks to see if it's really you sending the requests.</p>
    </body></html>
    """

    assert google_native_blocked("https://www.google.com/sorry/index", html) is True


@pytest.mark.component
def test_google_native_thumbnail_flows_into_snapshot_image_url() -> None:
    snapshot = extract_search_result_snapshot(
        {
            "provider": "google_native",
            "title": "Widget",
            "thumbnail": "https://example.com/thumb.jpg",
        },
        url="https://shop.example.com/p/widget",
        domain="example.com",
    )

    assert snapshot["image_url"] == "https://example.com/thumb.jpg"


@pytest.mark.component
def test_google_native_intelligence_keeps_provider_label() -> None:
    intelligence = build_search_result_intelligence(
        source={"title": "Nike Air Max", "brand": "Nike"},
        candidate_payload={"provider": "google_native", "title": "Nike Air Max"},
        candidate_url="https://www.nike.com/in/w/air-max",
        candidate_domain="nike.com",
        source_type="brand_dtc",
    )

    assert intelligence["cleanup_source"] == "deterministic_google_native"


@pytest.mark.asyncio
@pytest.mark.component
async def test_google_native_session_reuses_single_page_across_queries(
    monkeypatch,
) -> None:
    actions: list[str] = []
    current_url = GOOGLE_NATIVE_HOME_URL
    last_query = ""
    html_by_query: dict[str, str] = {}

    class _Locator:
        async def fill(self, value: str) -> None:
            nonlocal last_query
            last_query = value
            actions.append(f"fill:{value}")

        async def press(self, value: str) -> None:
            actions.append(f"press:{value}")

    class _Page:
        async def goto(self, url: str, *, wait_until: str, timeout: int):
            nonlocal current_url
            current_url = url
            actions.append(f"goto:{url}")

        def locator(self, selector: str):
            actions.append(f"locator:{selector}")
            return _Locator()

        async def wait_for_timeout(self, timeout_ms: int) -> None:
            actions.append(f"wait:{timeout_ms}")

        @property
        def url(self) -> str:
            return current_url

    class _Runtime:
        def page(self, **kwargs):
            actions.append(f"page-acquired:{kwargs.get('domain')}")

            class _Context:
                async def __aenter__(self):
                    return _Page()

                async def __aexit__(self, exc_type, exc, tb):
                    actions.append("page-released")
                    return None

            return _Context()

    async def _fake_runtime(*, browser_engine: str):
        actions.append(f"engine:{browser_engine}")
        return _Runtime()

    async def _fake_html(_page):
        return html_by_query.get(
            last_query,
            """
            <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget"><h3>Widget</h3></a>
            """,
        )

    monkeypatch.setattr(
        "app.intelligence.discovery.get_browser_runtime",
        _fake_runtime,
    )
    monkeypatch.setattr(
        "app.intelligence.discovery.get_page_html",
        _fake_html,
    )

    async with google_native_session() as run_query:
        html_by_query["blue shoe"] = """
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fwidget"><h3>Widget</h3></a>
        """
        html_by_query["red shoe"] = """
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fother"><h3>Other Widget</h3></a>
        """
        html_by_query["green shoe"] = """
        <a href="/url?q=https%3A%2F%2Fshop.example.com%2Fp%2Fthird"><h3>Third Widget</h3></a>
        """
        first = await run_query("blue shoe", 3)
        second = await run_query("red shoe", 3)
        third = await run_query("green shoe", 3)

    assert actions.count("page-acquired:google.com") == 1
    assert actions.count("page-released") == 1
    assert actions.count(f"goto:{GOOGLE_NATIVE_HOME_URL}") == 3
    assert "fill:blue shoe" in actions
    assert "fill:red shoe" in actions
    assert "fill:green shoe" in actions
    assert actions.count("press:Enter") == 3
    assert first[0].url == "https://shop.example.com/p/widget"
    assert second and third


@pytest.mark.asyncio
@pytest.mark.component
async def test_google_native_session_stops_after_google_sorry_page(monkeypatch) -> None:
    actions: list[str] = []
    current_url = GOOGLE_NATIVE_HOME_URL
    last_query = ""
    html_by_query: dict[str, str] = {}

    class _Locator:
        async def fill(self, value: str) -> None:
            nonlocal last_query
            last_query = value
            actions.append(f"fill:{value}")

        async def press(self, value: str) -> None:
            actions.append(f"press:{value}")

    class _Page:
        async def goto(self, url: str, *, wait_until: str, timeout: int):
            nonlocal current_url
            current_url = url
            actions.append(f"goto:{url}")

        def locator(self, selector: str):
            actions.append(f"locator:{selector}")
            return _Locator()

        async def wait_for_timeout(self, timeout_ms: int) -> None:
            actions.append(f"wait:{timeout_ms}")

        @property
        def url(self) -> str:
            return current_url

    class _Runtime:
        def page(self, **kwargs):
            actions.append(f"page-acquired:{kwargs.get('domain')}")

            class _Context:
                async def __aenter__(self):
                    return _Page()

                async def __aexit__(self, exc_type, exc, tb):
                    actions.append("page-released")
                    return None

            return _Context()

    async def _fake_runtime(*, browser_engine: str):
        actions.append(f"engine:{browser_engine}")
        return _Runtime()

    async def _fake_html(_page):
        return html_by_query.get(last_query, "")

    monkeypatch.setattr(
        "app.intelligence.discovery.get_browser_runtime",
        _fake_runtime,
    )
    monkeypatch.setattr(
        "app.intelligence.discovery.get_page_html",
        _fake_html,
    )
    html_by_query["blue shoe"] = """
    <html><body>
      <p>Our systems have detected unusual traffic from your computer network.</p>
      <p>This page checks to see if it's really you sending the requests.</p>
    </body></html>
    """

    async with google_native_session() as run_query:
        first = await run_query("blue shoe", 3)
        second = await run_query("red shoe", 3)

    assert first == []
    assert second == []
    assert actions.count(f"goto:{GOOGLE_NATIVE_HOME_URL}") == 1
    assert "fill:blue shoe" in actions
    assert "fill:red shoe" not in actions


@pytest.mark.component
def test_product_intelligence_llm_prompt_registered() -> None:
    task = get_prompt_task("product_intelligence_enrichment")

    assert task is not None
    assert task["system_file"] == "product_intelligence_enrichment.system.txt"


@pytest.mark.component
def test_product_intelligence_brand_inference_prompt_registered() -> None:
    task = get_prompt_task("product_intelligence_brand_inference")

    assert task is not None
    assert task["system_file"] == "product_intelligence_brand_inference.system.txt"
    assert task["user_file"] == "product_intelligence_brand_inference.user.txt"
