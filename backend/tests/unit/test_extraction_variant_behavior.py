# ruff: noqa: F403, F405
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

    events: list[tuple[str, str]] = []

    async def record_event(_context, level: str, message: str) -> None:
        events.append((level, message))

    monkeypatch.setattr(
        record_extraction_stage,
        "expand_sfcc_variant_endpoints",
        fail_expansion,
    )
    monkeypatch.setattr(record_extraction_stage, "_log_pipeline_event", record_event)
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
    assert events and events[0][0] == "warning"


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


def test_variant_identity_merges_sources_and_materializes_child_offer() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Everyday Tee",
      "url": "https://shop.test/products/everyday-tee",
      "hasVariant": [
        {"@type": "Product", "sku": "TEE-BLK-S", "color": "Black", "size": "S"}
      ]
    }
    </script>
    """
    artifacts = {
        "js_state_objects": {
            "variant": {
                "id": "v1",
                "sku": "TEE-BLK-S",
                "color": "Black",
                "size": "S",
                "price": "18.5",
                "currency": "USD",
                "availability": "InStock",
            }
        }
    }
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/everyday-tee",
        artifacts=artifacts,
    )
    variants = result.records[0]["variants"]
    assert variants == [
        {
            "variant_id": "v1",
            "sku": "TEE-BLK-S",
            "price": "18.50",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Black",
            "size": "S",
        }
    ]
    assert result.records[0]["_lineage"]["variants"][0]["price"]


def test_js_state_variant_sku_aliases_materialize_public_sku() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Shoe</h1></main>",
        "https://shop.test/products/runner-shoe",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Runner Shoe",
                    "url": "https://shop.test/products/runner-shoe",
                    "variants": [
                        {
                            "variantId": "runner-blue-9",
                            "skuCode": "NK-RUN-BLU-9",
                            "color": "Blue",
                            "size": "9",
                            "price": "120",
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"][0]["sku"] == "NK-RUN-BLU-9"


def test_nested_variant_options_money_inventory_and_sku_aliases_materialize() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Velvet Lip Color</h1></main>",
        "https://shop.test/products/velvet-lip-color",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Velvet Lip Color",
                    "url": "https://shop.test/products/velvet-lip-color",
                    "variants": [
                        {
                            "variantId": "rose-mini",
                            "skuCode": "LIP-ROSE-MINI",
                            "variationType": "Shade",
                            "variationValue": "Rosewood",
                            "sizeDescription": "0.1 oz",
                            "priceInfo": {
                                "currentPrice": {"amount": "28", "currencyCode": "USD"}
                            },
                            "inventory": {"inventoryStatus": "IN_STOCK"},
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "rose-mini",
            "sku": "LIP-ROSE-MINI",
            "price": "28.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Rosewood",
            "size": "0.1 oz",
        }
    ]


def test_js_state_parent_price_object_preserves_nested_currency_path() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Studio Tread</h1></main>",
        "https://shop.test/products/studio-tread",
        artifacts={
            "js_state_objects": {
                "product": {
                    "productName": "Studio Tread",
                    "url": "https://shop.test/products/studio-tread",
                    "brand": {"name": "Peloton"},
                    "currentPrice": {"amount": "3295.00", "currencyCode": "USD"},
                    "availability": "IN_STOCK",
                }
            }
        },
    )

    record = result.records[0]
    assert record["brand"] == "Peloton"
    assert record["price"] == "3295.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert record["_lineage"]["currency"]["source_path"].endswith(
        "/currentPrice/currencyCode"
    )


def test_variant_offer_inherits_parent_commercial_facts_but_keeps_child_availability() -> (
    None
):
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Court Shoe",
          "url": "https://shop.test/products/court-shoe",
          "offers": {
            "@type": "Offer",
            "price": "95",
            "priceCurrency": "USD",
            "availability": "https://schema.org/OutOfStock"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "COURT-WHT-8",
              "color": "White",
              "size": "8",
              "offers": {
                "@type": "Offer",
                "availability": "https://schema.org/InStock"
              }
            },
            {
              "@type": "Product",
              "sku": "COURT-WHT-9",
              "color": "White",
              "size": "9"
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/court-shoe",
    )

    variants = result.records[0]["variants"]
    assert variants == [
        {
            "variant_id": "COURT-WHT-8",
            "sku": "COURT-WHT-8",
            "price": "95.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "White",
            "size": "8",
        },
        {
            "variant_id": "COURT-WHT-9",
            "sku": "COURT-WHT-9",
            "price": "95.00",
            "currency": "USD",
            "availability": "out_of_stock",
            "color": "White",
            "size": "9",
        },
    ]
    lineage = result.records[0]["_lineage"]["variants"]
    assert lineage[0]["price"]["rule_id"] == "PARENT_OFFER_TO_VARIANT"
    assert lineage[0]["availability"]["rule_id"] != "PARENT_OFFER_TO_VARIANT"
    assert lineage[1]["availability"]["rule_id"] == "PARENT_OFFER_TO_VARIANT"


def test_js_state_later_product_object_backfills_missing_variant_rows() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Bootleg Pants</h1></main>",
        "https://shop.test/products/bootleg-pants",
        artifacts={
            "js_state_objects": {
                "bootstrap": {
                    "name": "Bootleg Pants",
                    "price": "1290",
                    "currency": "USD",
                },
                "hydration": {
                    "product": {
                        "name": "Bootleg Pants",
                        "url": "https://shop.test/products/bootleg-pants",
                        "variants": [
                            {
                                "variantId": "black-s",
                                "sku": "BP-BLK-S",
                                "color": "Black",
                                "size": "S",
                                "price": {"value": "1290"},
                                "currency": "USD",
                            },
                            {
                                "variantId": "black-m",
                                "sku": "BP-BLK-M",
                                "color": "Black",
                                "size": "M",
                                "price": {"value": "1290"},
                                "currency": "USD",
                            },
                        ],
                    }
                },
            }
        },
    )
    assert {row["variant_id"]: row for row in result.records[0]["variants"]} == {
        "black-s": {
            "variant_id": "black-s",
            "sku": "BP-BLK-S",
            "price": "1290.00",
            "currency": "USD",
            "color": "Black",
            "size": "S",
        },
        "black-m": {
            "variant_id": "black-m",
            "sku": "BP-BLK-M",
            "price": "1290.00",
            "currency": "USD",
            "color": "Black",
            "size": "M",
        },
    }


def test_legacy_shopify_product_json_supplies_linked_images_and_variants() -> None:
    html = """
    <html><body>
      <script id="ProductJson--product-template" hidden>
        {
          "id": 7685845516494,
          "title": "40th Anniversary Graphic Womens Short Sleeve Shirt (Black/Red)",
          "handle": "jordan-hj0139-045-40th-anniversary-graphic-womens-short-sleeve-shirt-black-red-1",
          "vendor": "JORDAN",
          "images": [
            "//shop.test/cdn/shop/files/47b157b3d5f17c0ca8657919596ebdd7.jpg"
          ],
          "variants": [
            {"id": 43468991627470, "title": "XS", "option1": "XS", "sku": "20959706", "price": 1998, "available": true},
            {"id": 43468991660238, "title": "S", "option1": "S", "sku": "20959704", "price": 1998, "available": false}
          ],
          "options": ["Size"]
        }
      </script>
    </body></html>
    """
    url = (
        "https://shop.test/products/"
        "jordan-hj0139-045-40th-anniversary-graphic-womens-short-sleeve-shirt-black-red-1"
    )

    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            html,
            url,
            max_records=1,
        )
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://shop.test/cdn/shop/files/47b157b3d5f17c0ca8657919596ebdd7.jpg"
    )
    assert [(row["sku"], row["size"]) for row in record["variants"]] == [
        ("20959706", "XS"),
        ("20959704", "S"),
    ]


def test_network_variant_offer_rows_materialize_with_lineage() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Tee</h1></main>",
        "https://shop.test/products/runner-tee",
        network_payloads=(
            {
                "body": {
                    "data": {
                        "product": {
                            "name": "Runner Tee",
                            "url": "https://shop.test/products/runner-tee",
                            "variants": [
                                {
                                    "variantId": "navy-s",
                                    "sku": "RT-NV-S",
                                    "color": "Navy",
                                    "size": "S",
                                    "price": "35",
                                    "currency": "USD",
                                    "available": True,
                                },
                                {
                                    "variantId": "navy-m",
                                    "sku": "RT-NV-M",
                                    "color": "Navy",
                                    "size": "M",
                                    "price": "35",
                                    "currency": "USD",
                                    "available": False,
                                },
                            ],
                        }
                    }
                }
            },
        ),
    )
    assert {row["variant_id"]: row for row in result.records[0]["variants"]} == {
        "navy-s": {
            "variant_id": "navy-s",
            "sku": "RT-NV-S",
            "price": "35.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Navy",
            "size": "S",
        },
        "navy-m": {
            "variant_id": "navy-m",
            "sku": "RT-NV-M",
            "price": "35.00",
            "currency": "USD",
            "availability": "out_of_stock",
            "color": "Navy",
            "size": "M",
        },
    }
    assert all(row["availability"] for row in result.records[0]["_lineage"]["variants"])
    assert result.recipe_execution is not None


def test_mixed_numeric_and_string_identity_values_do_not_crash() -> None:
    artifacts = {
        "js_state_objects": {
            "product": {
                "title": "Rustic Cotton T-Shirt",
                "sku": 123,
                "price": "29.90",
                "currency": "USD",
            }
        }
    }
    html = '<html><body><h1>Rustic Cotton T-Shirt</h1><div data-sku="123"></div></body></html>'
    result = _extract(
        "ecommerce_detail",
        html,
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        artifacts=artifacts,
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["sku"] in {123, "123"}


def test_boolean_product_title_is_rejected_before_typed_publication() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://shop.test/products/classic-suede",
        artifacts={
            "js_state_objects": {
                "product": {
                    "title": True,
                    "price": "90",
                    "currency": "USD",
                }
            }
        },
    )

    assert result.records
    assert result.records[0].get("title") is not True
    assert not isinstance(result.records[0].get("title"), bool)


def test_integer_variant_url_is_rejected_before_typed_publication() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Old Skool Shoe</h1></main>",
        "https://shop.test/products/old-skool-shoe",
        artifacts={
            "js_state_objects": {
                "variants": [
                    {
                        "__typename": "ProductVariant",
                        "variantId": "black-9",
                        "sku": "OLD-SKOOL-BLK-9",
                        "size": "9",
                        "url": 1079,
                    }
                ]
            }
        },
    )

    variant = result.records[0]["variants"][0]
    assert variant["sku"] == "OLD-SKOOL-BLK-9"
    assert "url" not in variant


def test_valid_string_title_url_and_boolean_availability_remain_unchanged() -> None:
    variant_url = "https://shop.test/products/classic-suede?variant=black-9"
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Fallback Title</h1></main>",
        "https://shop.test/products/classic-suede",
        artifacts={
            "js_state_objects": {
                "product": {
                    "title": "Classic Suede",
                    "price": "90",
                    "currency": "USD",
                    "variants": [
                        {
                            "__typename": "ProductVariant",
                            "variantId": "black-9",
                            "sku": "CLASSIC-BLK-9",
                            "size": "9",
                            "url": variant_url,
                            "available": True,
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["title"] == "Classic Suede"
    assert result.records[0]["variants"] == [
        {
            "variant_id": "black-9",
            "sku": "CLASSIC-BLK-9",
            "price": "90.00",
            "currency": "USD",
            "url": variant_url,
            "availability": "in_stock",
            "size": "9",
        }
    ]


def test_adapter_artifact_flows_through_evidence_engine() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://shop.test/products/adapter-widget",
        artifacts={
            "adapter_artifacts": [
                {
                    "artifact_type": "adapter_json",
                    "adapter_name": "legacy",
                    "body": {
                        "title": "Adapter Widget",
                        "sku": "AD-1",
                        "price": "10.00",
                        "currency": "USD",
                    },
                }
            ]
        },
    )
    assert result.records
    assert result.records[0]["title"] == "Adapter Widget"
    assert result.records[0]["_lineage"]["title"]
    assert result.recipe_execution is not None
