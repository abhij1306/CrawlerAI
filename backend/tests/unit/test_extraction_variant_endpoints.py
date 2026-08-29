# ruff: noqa: F403, F405
"""test_extraction_variant_behavior cases split by public behavior."""

from __future__ import annotations

from app.core.config.run_events import RunEventKind
from tests.unit.extraction_pipeline_test_support import *


def test_network_product_id_selects_requested_detail_product() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main></main>",
        "https://shop.test/men/product/adidas-originals/black-samba-og-sneakers/15199881",
        network_payloads=(
            {
                "body": {
                    "products": [
                        {
                            "productId": "18701561",
                            "productName": "Black & White Out Of Office Calf Leather Sneakers",
                            "brandName": "Off-White",
                            "finalPrice": 429,
                            "currency": "USD",
                        },
                        {
                            "productId": "15199881",
                            "productName": "Black Samba OG Sneakers",
                            "brandName": "adidas Originals",
                            "finalPrice": 100,
                            "currency": "USD",
                        },
                    ]
                }
            },
        ),
    )

    assert result.records[0]["title"] == "Black Samba OG Sneakers"
    assert result.records[0]["brand"] == "adidas Originals"


def test_url_mismatched_product_title_cannot_win_detail_resolution() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/json">
        {"products":[{"productName":"Black Warped Logo Short Sleeve T-shirt","brand":"ASICS"}]}
        </script>
        """,
        "https://shop.test/men/product/adidas-originals/black-samba-og-sneakers/15199881",
    )

    assert result.records[0]["title"] == "black samba og sneakers"


def test_related_product_root_cannot_overwrite_selected_detail_entity() -> None:
    html = """
    <script type="application/ld+json">
    [
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Selected Trail Shoe",
        "url": "https://shop.test/products/selected-trail-shoe",
        "sku": "SEL-1",
        "offers": {"@type": "Offer", "price": "120", "priceCurrency": "USD"}
      },
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Related Day Pack",
        "url": "https://shop.test/products/day-pack",
        "sku": "REL-1",
        "offers": {"@type": "Offer", "price": "999", "priceCurrency": "USD"}
      }
    ]
    </script>
    """
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/selected-trail-shoe",
    )
    assert result.target.status == "resolved"
    assert result.records[0]["title"] == "Selected Trail Shoe"
    assert result.records[0]["price"] == "120.00"
    assert result.records[0]["url"] == "https://shop.test/products/selected-trail-shoe"


def test_noisy_variant_root_cannot_outrank_complete_offer_product() -> None:
    html = """
    <script type="application/ld+json">
    [
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Soleil pant in linen",
        "url": "https://shop.test/products/soleil-pant",
        "sku": "CI939-BR8825",
        "offers": {"@type": "Offer", "price": "14273", "priceCurrency": "INR"}
      },
      {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Linen",
        "url": "https://shop.test/products/linen",
        "hasVariant": [
          {"@type": "Product", "color": "WT0002", "url": "https://api.shop.test/99107606086.html"}
        ]
      }
    ]
    </script>
    """
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/soleil-pant?colorCode=BR8825",
    )
    assert result.records[0]["title"] == "Soleil pant in linen"
    assert result.records[0]["price"] == "14273.00"
    assert not result.records[0].get("variants")


def test_commercial_dom_size_controls_materialize_variants() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Classic Shorts</h1>
          <button data-size="XS" data-sku="SHORT-XS" data-price="£25.00"
                  data-currency="GBP" data-stock="1">XS</button>
          <button data-size="S" data-sku="SHORT-S" data-price="£25.00"
                  data-currency="GBP" data-stock="0">S</button>
        </main>
        """,
        "https://shop.test/products/classic-shorts",
    )

    variants = result.records[0]["variants"]
    assert {(row["size"], row["availability"]) for row in variants} == {
        ("S", "out_of_stock"),
        ("XS", "in_stock"),
    }
    assert result.records[0].get("sku") is None


def test_dom_option_data_sku_is_variant_scoped() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Everyday Tee</h1>
          <input type="radio" name="size" value="S" data-sku="variant-101">
          <input type="radio" name="size" value="M" data-sku="variant-102">
        </main>
        <script>
        var meta = {"product":{"id":721,"title":"Everyday Tee","variants":[
          {"id":"variant-101","sku":"TEE-S","option1":"S"},
          {"id":"variant-102","sku":"TEE-M","option1":"M"}
        ]}};
        </script>
        """,
        "https://shop.test/products/everyday-tee",
    )

    assert result.records[0].get("sku") is None
    dom_skus = [
        row
        for row in result.evidence
        if row.collector_id == "dom" and row.value in {"variant-101", "variant-102"}
    ]
    assert {row.fact_type for row in dom_skus} == {"variant.sku"}
    assert {row.subject_scope for row in dom_skus} == {"variant"}
    assert len({row.subject_id for row in dom_skus}) == 2
    assert all(row.relation_type == "product_variant" for row in dom_skus)
    assert result.graph.entity_counts["variant"] == 2


def test_structured_endpoint_axes_share_the_url_identity_mapping() -> None:
    assert structured_variant_state.variant_endpoint_url_axis_values(
        "https://shop.test/Product-Variation"
        "?dwvar_item_colorProductCode=CI939"
        "&attribute_colorCode=BR8825"
        "&attribute_sku=TEE-S"
    ) == {"style": "CI939", "color": "BR8825", "sku": "TEE-S"}


def test_standard_selected_markers_emit_tri_state_without_synthesizing_variants() -> (
    None
):
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Everyday Tee</h1>
          <div role="radiogroup" aria-label="Color">
            <button role="radio" value="Red" aria-selected="false"
                    class="selected">Red</button>
            <button role="radio" value="Blue" aria-pressed="true">Blue</button>
            <button role="radio" value="Green" aria-current="page">Green</button>
          </div>
          <select name="color"><option selected>Black</option></select>
          <input type="radio" name="color" value="White" checked>
        </main>
        """,
        "https://shop.test/products/everyday-tee",
    )

    states = {
        row.entity_hint.option_values["color"]: row.value
        for row in result.evidence
        if row.fact_type == "variant.selected"
        and row.metadata.get("dom_selection_signal") is True
        and row.entity_hint is not None
    }
    assert states == {
        "Red": False,
        "Blue": True,
        "Green": True,
        "Black": True,
        "White": True,
    }
    assert not result.records[0].get("variants")
    assert result.records[0].get("color") is None


def test_one_dom_selected_option_binds_existing_variant_matrix() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context":"https://schema.org", "@type":"ProductGroup",
          "name":"Everyday Tee", "variesBy":["https://schema.org/color"],
          "hasVariant":[
            {"@type":"Product", "sku":"TEE-RED", "color":"Red",
             "offers":{"price":"10", "priceCurrency":"USD"}},
            {"@type":"Product", "sku":"TEE-BLUE", "color":"Blue",
             "offers":{"price":"20", "priceCurrency":"USD"}}
          ]
        }
        </script>
        <main><h1>Everyday Tee</h1>
          <div role="radiogroup" aria-label="Color">
            <button role="radio" value="Red" aria-checked="false">Red</button>
            <button role="radio" value="Blue" aria-checked="true">Blue</button>
          </div>
        </main>
        """,
        "https://shop.test/products/everyday-tee",
    )

    assert result.records[0]["color"] == "Blue"
    assert result.records[0]["price"] == "20.00"


def test_duplicate_unlabelled_aria_options_bind_one_unique_matrix_axis() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context":"https://schema.org", "@type":"ProductGroup",
          "name":"Everyday Tee", "variesBy":["https://schema.org/color"],
          "hasVariant":[
            {"@type":"Product", "sku":"TEE-RED", "color":"Red"},
            {"@type":"Product", "sku":"TEE-BLUE", "color":"Blue"}
          ]
        }
        </script>
        <main><h1>Everyday Tee</h1>
          <div role="radiogroup">
            <a role="radio" title="Red" aria-checked="false"></a>
            <a role="radio" title="Blue" aria-checked="true"></a>
          </div>
          <div role="radiogroup">
            <a role="radio" title="Red" aria-checked="false"></a>
            <a role="radio" title="Blue" aria-checked="true"></a>
          </div>
        </main>
        """,
        "https://shop.test/products/everyday-tee",
    )

    assert result.records[0]["color"] == "Blue"


def test_multiple_dom_selected_options_fail_closed() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context":"https://schema.org", "@type":"ProductGroup",
          "name":"Everyday Tee", "variesBy":["https://schema.org/color"],
          "hasVariant":[
            {"@type":"Product", "sku":"TEE-RED", "color":"Red"},
            {"@type":"Product", "sku":"TEE-BLUE", "color":"Blue"}
          ]
        }
        </script>
        <main><h1>Everyday Tee</h1>
          <button data-option-name="color" value="Red" aria-pressed="true">Red</button>
          <button data-option-name="color" value="Blue" aria-pressed="true">Blue</button>
        </main>
        """,
        "https://shop.test/products/everyday-tee",
    )

    assert result.records[0].get("color") is None


def test_url_axis_wins_while_dom_selection_refines_another_axis() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context":"https://schema.org", "@type":"ProductGroup",
          "name":"Everyday Tee",
          "variesBy":["https://schema.org/color", "https://schema.org/size"],
          "hasVariant":[
            {"@type":"Product", "sku":"RED-S", "color":"Red", "size":"S",
             "offers":{"price":"10", "priceCurrency":"USD"}},
            {"@type":"Product", "sku":"RED-M", "color":"Red", "size":"M",
             "offers":{"price":"12", "priceCurrency":"USD"}},
            {"@type":"Product", "sku":"BLUE-M", "color":"Blue", "size":"M",
             "offers":{"price":"20", "priceCurrency":"USD"}}
          ]
        }
        </script>
        <main><h1>Everyday Tee</h1>
          <button data-option-name="color" value="Blue" aria-pressed="true">Blue</button>
          <input type="radio" name="size" value="M" checked>
        </main>
        """,
        "https://shop.test/products/everyday-tee?color=Red",
    )

    assert result.records[0]["color"] == "Red"
    assert result.records[0]["size"] == "M"
    assert result.records[0]["price"] == "12.00"


def test_dom_option_controls_do_not_materialize_sellable_variants() -> None:
    html = """
    <main>
      <h1>Everyday Tee</h1>
      <select name="size">
        <option>Select size</option>
        <option>S</option>
        <option>M</option>
      </select>
      <button data-option-name="color">Black</button>
    </main>
    """
    result = _extract(
        "ecommerce_detail", html, "https://shop.test/products/everyday-tee"
    )
    assert result.records
    assert not result.records[0].get("variants")
    option_evidence = [
        item for item in result.evidence if item.fact_type.startswith("option.")
    ]
    assert option_evidence
    assert result.graph.entity_counts["option"] == 3


def test_demandware_dom_variation_buttons_materialize_selected_color_sizes() -> None:
    html = """
    <main>
      <h1>Rib Racerback Tank</h1>
      <button data-attr-id="color" data-dvalue="Medium Heather Grey"
              aria-label="Select Color Medium Heather Grey"
              data-url="/on/demandware.store/Sites-shop-Site/default/Product-Variation?dwvar_112768921NG0_color=&pid=112768921NG0&quantity=1">
        Medium Heather Grey
      </button>
      <button class="select-size" data-attr-id="size" data-attr-value="XS"
              value="/on/demandware.store/Sites-shop-Site/default/Product-Variation?dwvar_112768921NG0_color=Medium%20Heather%20Grey&dwvar_112768921NG0_size=XS&pid=112768921NG0&quantity=1"
              data-json='{"displayValue":"XS","selectable":true,"selected":false}'>
        XS
      </button>
      <button class="select-size" data-attr-id="size" data-attr-value="S"
              value="/on/demandware.store/Sites-shop-Site/default/Product-Variation?dwvar_112768921NG0_color=Medium%20Heather%20Grey&dwvar_112768921NG0_size=S&pid=112768921NG0&quantity=1"
              data-json='{"displayValue":"S","selectable":false,"selected":false}'>
        S
      </button>
    </main>
    """

    result = _extract(
        "ecommerce_detail",
        html,
        "https://www.example.test/p/tank/112768921NG0.html",
    )

    variants = result.records[0]["variants"]
    assert [(row["color"], row["size"], row["availability"]) for row in variants] == [
        ("Medium Heather Grey", "S", "out_of_stock"),
        ("Medium Heather Grey", "XS", "in_stock"),
    ]
    assert all("variant_id" not in row and "sku" not in row for row in variants)


def test_demandware_attribute_json_string_flags_use_boolean_semantics() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Rib Racerback Tank</h1>
          <button data-attr-id="color" data-dvalue="Medium Heather Grey"
                  data-url="/on/demandware.store/Sites-shop-Site/default/Product-Variation?dwvar_1_color=&pid=1">
            Medium Heather Grey
          </button>
          <button class="select-size" data-attr-id="size" data-attr-value="XS"
                  value="/on/demandware.store/Sites-shop-Site/default/Product-Variation?dwvar_1_color=Medium%20Heather%20Grey&dwvar_1_size=XS"
                  data-json='{"displayValue":"XS","selectable":"0","selected":"false"}'>
            XS
          </button>
        </main>
        """,
        "https://www.example.test/p/tank/112768921NG0.html",
    )

    variants = result.records[0]["variants"]
    assert len(variants) == 1
    assert variants[0]["availability"] == "out_of_stock"
    assert variants[0]["color"] == "Medium Heather Grey"
    assert variants[0]["size"] == "XS"
    assert all("selected" not in row for row in variants)


def test_sfcc_product_variation_endpoint_values_materialize_confirmed_matrix() -> None:
    html = """
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "VS Iconic Rib Racerback Tank Top",
        "sku": "112768921NG0",
        "offers": {
          "@type": "Offer",
          "price": "2104",
          "priceCurrency": "INR"
        }
      }
    </script>
    <main>
      <h1>VS Iconic Rib Racerback Tank Top</h1>
      <button data-attr-id="color"
              data-url="/on/demandware.store/Sites-vsfa-Site/default/Product-Variation?dwvar_112768921NG0_color=Pure%20Black&pid=112768921NG0">
        Pure Black
      </button>
      <button data-attr-id="color"
              data-url="/on/demandware.store/Sites-vsfa-Site/default/Product-Variation?dwvar_112768921NG0_color=Medium%20Heather%20Grey&pid=112768921NG0">
        Medium Heather Grey
      </button>
    </main>
    """
    payload = {
        "product": {
            "id": "112768921NG0",
            "name": "VS Iconic Rib Racerback Tank Top",
            "url": "https://www.victoriassecret.in/p/vs-iconic-rib-racerback-tank-top/112768921NG0.html",
            "price": {"sales": {"value": 2104, "currency": "INR"}},
            "variationAttributes": [
                {
                    "attributeId": "color",
                    "values": [
                        {
                            "id": "Pure Black",
                            "displayValue": "Pure Black",
                            "selectable": True,
                            "url": "/on/demandware.store/Sites-vsfa-Site/default/Product-Variation?dwvar_112768921NG0_color=Pure%20Black&pid=112768921NG0",
                        }
                    ],
                },
                {
                    "attributeId": "size",
                    "values": [
                        {
                            "id": "XS",
                            "displayValue": "XS",
                            "selectable": True,
                            "url": "/on/demandware.store/Sites-vsfa-Site/default/Product-Variation?dwvar_112768921NG0_color=Pure%20Black&dwvar_112768921NG0_size=XS&pid=112768921NG0",
                        },
                        {
                            "id": "S",
                            "displayValue": "S",
                            "selectable": False,
                            "url": "/on/demandware.store/Sites-vsfa-Site/default/Product-Variation?dwvar_112768921NG0_color=Pure%20Black&dwvar_112768921NG0_size=S&pid=112768921NG0",
                        },
                    ],
                },
            ],
        }
    }

    result = _extract(
        "ecommerce_detail",
        html,
        "https://www.victoriassecret.in/p/vs-iconic-rib-racerback-tank-top/112768921NG0.html",
        network_payloads=({"body": payload},),
    )

    variants = result.records[0]["variants"]
    assert [(row["color"], row["size"], row["availability"]) for row in variants] == [
        ("Pure Black", "S", "out_of_stock"),
        ("Pure Black", "XS", "in_stock"),
    ]
    assert all(
        row["price"] == "2104.00" and row["currency"] == "INR" for row in variants
    )
    assert not any(row.get("color") == "Medium Heather Grey" for row in variants)


@pytest.mark.asyncio
async def test_sfcc_variant_endpoint_expansion_discovers_same_origin_urls(
    monkeypatch,
) -> None:
    page_url = "https://www.victoriassecret.in/p/tank/112768921NG0.html"
    html = """
    <button data-url="/on/demandware.store/Sites-vsfa-Site/default/Product-Variation?dwvar_112768921NG0_color=Pure%20Black&pid=112768921NG0"></button>
    <button value="https://evil.test/on/demandware.store/Sites-vsfa-Site/default/Product-Variation?dwvar_112768921NG0_color=Blue&pid=112768921NG0"></button>
    """
    fetched: list[str] = []

    async def safe_url(_url: str) -> bool:
        return True

    async def fake_fetch(url: str) -> dict[str, object]:
        fetched.append(url)
        return {"url": url, "method": "GET", "body": {"product": {"id": "p"}}}

    monkeypatch.setattr(variant_endpoint_expansion, "_safe_public_url", safe_url)

    payloads = await variant_endpoint_expansion.expand_sfcc_variant_endpoints(
        page_url=page_url,
        html_text=html,
        fetch_endpoint=fake_fetch,
    )

    assert fetched == [
        "https://www.victoriassecret.in/on/demandware.store/Sites-vsfa-Site/default/Product-Variation?dwvar_112768921NG0_color=Pure%20Black&pid=112768921NG0"
    ]
    assert payloads == [
        {
            "url": fetched[0],
            "method": "GET",
            "body": {"product": {"id": "p"}},
        }
    ]


@pytest.mark.asyncio
async def test_sfcc_variant_endpoint_expansion_failure_is_best_effort(
    monkeypatch,
) -> None:
    expansion_kwargs: dict[str, object] = {}

    async def fail_expansion(**kwargs) -> list[dict[str, object]]:
        expansion_kwargs.update(kwargs)
        raise RuntimeError("endpoint unavailable")

    events: list[dict[str, object]] = []

    async def record_event(_context, **kwargs) -> None:
        events.append(kwargs)

    monkeypatch.setattr(
        record_extraction_stage,
        "expand_sfcc_variant_endpoints",
        fail_expansion,
    )
    monkeypatch.setattr(record_extraction_stage, "_record_pipeline_event", record_event)
    context = SimpleNamespace(
        surface="ecommerce_detail",
        url="https://shop.test/products/ABC123",
        config=SimpleNamespace(proxy_list=["http://fallback-proxy.test:8080"]),
    )
    acquisition_result = SimpleNamespace(
        final_url=context.url,
        html="<main></main>",
        network_payloads=[],
        acquisition_diagnostics={},
        request=SimpleNamespace(proxy_list=["http://run-proxy.test:8080"]),
    )

    await record_extraction_stage._expand_variant_endpoint_payloads(
        context,
        acquisition_result,
    )

    assert acquisition_result.network_payloads == []
    assert (
        acquisition_result.acquisition_diagnostics[
            "sfcc_variant_endpoint_expansion_error"
        ]
        == "RuntimeError"
    )
    assert expansion_kwargs["proxy"] == "http://run-proxy.test:8080"
    assert events == [
        {
            "kind": RunEventKind.EXTRACTION_VARIANT_EXPANSION_FAILED,
            "facts": {"exception_type": "RuntimeError"},
        }
    ]


@pytest.mark.asyncio
async def test_sfcc_variant_endpoint_fetch_threads_proxy_to_fallback(
    monkeypatch,
) -> None:
    seen: list[tuple[str, str | None]] = []

    async def get_client(*, proxy: str | None = None):
        seen.append(("httpx", proxy))
        return object()

    async def request_json(_client, _url: str):
        raise httpx.ConnectError("network failure")

    async def curl_fetch(_url: str, _timeout: float, *, proxy=None):
        seen.append(("curl", proxy))
        return SimpleNamespace(
            html='{"product": {"id": "ABC123"}}',
            status_code=200,
            content_type="application/json",
        )

    monkeypatch.setattr(
        variant_endpoint_expansion, "get_shared_http_client", get_client
    )
    monkeypatch.setattr(variant_endpoint_expansion, "_request_json", request_json)
    monkeypatch.setattr(variant_endpoint_expansion, "curl_fetch", curl_fetch)

    payload = await variant_endpoint_expansion._fetch_variant_endpoint(
        "https://shop.test/Product-Variation?pid=ABC123",
        proxy="http://proxy.test:8080",
    )

    assert payload is not None
    assert seen == [
        ("httpx", "http://proxy.test:8080"),
        ("curl", "http://proxy.test:8080"),
    ]


@pytest.mark.asyncio
async def test_sfcc_variant_endpoint_policy_value_error_does_not_fallback(
    monkeypatch,
) -> None:
    async def get_client(*, proxy: str | None = None):
        return object()

    async def request_json(_client, _url: str):
        raise ValueError("variant endpoint redirects are not allowed")

    async def unexpected_curl(*_args, **_kwargs):
        raise AssertionError("curl fallback must not run")

    monkeypatch.setattr(
        variant_endpoint_expansion, "get_shared_http_client", get_client
    )
    monkeypatch.setattr(variant_endpoint_expansion, "_request_json", request_json)
    monkeypatch.setattr(variant_endpoint_expansion, "curl_fetch", unexpected_curl)

    with pytest.raises(ValueError, match="redirects are not allowed"):
        await variant_endpoint_expansion._fetch_variant_endpoint(
            "https://shop.test/Product-Variation?pid=ABC123"
        )


@pytest.mark.asyncio
async def test_sfcc_variant_endpoint_error_status_does_not_fallback(
    monkeypatch,
) -> None:
    async def get_client(*, proxy: str | None = None):
        return object()

    async def request_json(_client, url: str):
        return httpx.Response(503, request=httpx.Request("GET", url))

    async def unexpected_curl(*_args, **_kwargs):
        raise AssertionError("curl fallback must not run")

    monkeypatch.setattr(
        variant_endpoint_expansion, "get_shared_http_client", get_client
    )
    monkeypatch.setattr(variant_endpoint_expansion, "_request_json", request_json)
    monkeypatch.setattr(variant_endpoint_expansion, "curl_fetch", unexpected_curl)

    assert (
        await variant_endpoint_expansion._fetch_variant_endpoint(
            "https://shop.test/Product-Variation?pid=ABC123"
        )
        is None
    )


def test_sfcc_candidate_rejects_foreign_dwvar_product_code() -> None:
    assert not variant_endpoint_expansion._candidate_matches_page_product(
        "https://shop.test/Product-Variation?dwvar_XYZ999_color=Blue",
        page_codes=frozenset({"abc123"}),
    )
    assert variant_endpoint_expansion._candidate_matches_page_product(
        "https://shop.test/Product-Variation?dwvar_ABC123_color=Blue",
        page_codes=frozenset({"abc123"}),
    )


def test_nuxt_devalue_inline_containers_respect_depth_limit(monkeypatch) -> None:
    monkeypatch.setattr(variant_policy, "EMBEDDED_STATE_MAX_DEPTH", 2)
    data = [{"level_1": {"level_2": {"too_deep": "value"}}}]

    assert structured_variant_state.decode_nuxt_devalue(data, 0) == {
        "level_1": {"level_2": None}
    }
