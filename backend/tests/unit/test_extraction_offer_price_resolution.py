# ruff: noqa: F403, F405
"""test_extraction_runtime_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *

from tests.unit.extraction_runtime_test_support import (
    ValidationError,
    field_contracts_for_surface,
)


def test_field_contract_registry_marks_default_detail_fields_critical() -> None:
    contracts = {
        row.field: row for row in field_contracts_for_surface(Surface.ECOMMERCE_DETAIL)
    }

    assert contracts["title"].required is True
    assert contracts["title"].criticality == "critical"
    assert contracts["price"].entity_scope == "offer"
    assert contracts["image_url"].entity_scope == "asset"
    assert contracts["variants"].cardinality == "many"


def test_evidence_is_immutable() -> None:
    result = _extract("ecommerce_detail", HTML, "https://shop.test/products/trail-shoe")
    item = result.evidence[0]
    with pytest.raises((ValidationError, TypeError)):
        item.value = "changed"  # type: ignore[misc]
    assert isinstance(item, Evidence)
    assert item.value != "changed"


def test_offer_price_without_currency_is_not_published() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "")
    result = _extract("ecommerce_detail", html, "https://shop.test/products/trail-shoe")
    assert result.records
    public = result.records[0].model_dump(mode="json", exclude_none=True)
    assert "price" not in public
    assert "currency" not in public
    assert "PRICE_WITHOUT_CURRENCY" in {finding.rule_id for finding in result.findings}


def test_offer_price_inherits_currency_from_locale_path_segment() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "").replace(
        "https://shop.test/products/trail-shoe",
        "https://shop.test/en-in/products/trail-shoe",
    )
    result = _extract(
        "ecommerce_detail", html, "https://shop.test/en-in/products/trail-shoe"
    )
    assert result.records
    public = result.records[0].model_dump(mode="json", exclude_none=True)
    assert public.get("price") == "129.00"
    assert public.get("currency") == "INR"
    assert not any(
        row.metadata.get("derived_by") == "currency_from_page_url_hint"
        for row in result.evidence
    )
    assert any(
        row.fact_type == "offer.currency"
        and row.value == "INR"
        and row.rule_id == "currency_from_page_url_hint"
        for row in result.derived_facts
    )


def test_offer_price_inherits_currency_from_cctld() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "").replace(
        "https://shop.test/products/trail-shoe",
        "https://shop.co.in/products/trail-shoe",
    )
    result = _extract(
        "ecommerce_detail", html, "https://shop.co.in/products/trail-shoe"
    )
    assert result.records
    public = result.records[0].model_dump(mode="json", exclude_none=True)
    assert public.get("price") == "129.00"
    assert public.get("currency") == "INR"


def test_uncorroborated_cent_magnitude_price_is_not_silently_repaired() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Tee</h1></main>",
        "https://shop.test/products/runner-tee",
        network_payloads=(
            {
                "body": {
                    "name": "Runner Tee",
                    "url": "https://shop.test/products/runner-tee",
                    "price": "3499",
                    "currency": "USD",
                }
            },
        ),
    )
    assert result.records[0]["price"] == "3499.00"
    assert result.records[0]["currency"] == "USD"


def test_explicit_usd_minor_unit_price_is_converted_to_major_units() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Road Hoodie</h1></main>",
        "https://shop.test/products/road-hoodie",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Road Hoodie",
                        "url": "https://shop.test/products/road-hoodie",
                        "priceInCents": 13875,
                        "currency": "USD",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "138.75"
    facts = _price_repair_facts(result, "explicit_minor_unit_price")
    assert any(fact.value == "138.75" for fact in facts)
    assert any(
        item.fact_type == "offer.price"
        and item.raw_value == 13875
        and "explicit_minor_unit_price" not in item.flags
        for item in result.evidence
    )


def test_explicit_inr_minor_unit_variant_price_is_converted_to_major_units() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Studio Jacket</h1></main>",
        "https://shop.test/products/studio-jacket",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Studio Jacket",
                    "url": "https://shop.test/products/studio-jacket",
                    "variants": [
                        {
                            "variantId": "black-m",
                            "sku": "STUDIO-BLK-M",
                            "size": "M",
                            "priceInPaise": 2820000,
                            "currency": "INR",
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"][0]["price"] == "28200.00"
    facts = _price_repair_facts(result, "explicit_minor_unit_price")
    assert any(fact.value == "28200.00" for fact in facts)
    assert any(
        item.fact_type == "offer.price" and item.raw_value == 2820000 and not item.flags
        for item in result.evidence
    )


def test_nested_variant_minor_unit_price_is_converted_to_major_units() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Road Hoodie</h1></main>",
        "https://shop.test/products/road-hoodie",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Road Hoodie",
                    "url": "https://shop.test/products/road-hoodie",
                    "variants": [
                        {
                            "variantId": "brown-m",
                            "sku": "ROAD-BRN-M",
                            "size": "M",
                            "priceInfo": {
                                "priceInCents": 13875,
                                "currencyCode": "USD",
                            },
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"][0]["price"] == "138.75"
    facts = _price_repair_facts(result, "explicit_minor_unit_price")
    assert any(fact.value == "138.75" for fact in facts)
    assert any(
        item.fact_type == "offer.price"
        and item.raw_value == 13875
        and item.locator.value.endswith("/priceInCents")
        and not item.flags
        for item in result.evidence
    )


def test_zero_decimal_currency_explicit_minor_key_is_not_divided() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Tokyo Jacket</h1></main>",
        "https://shop.test/products/tokyo-jacket",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Tokyo Jacket",
                        "url": "https://shop.test/products/tokyo-jacket",
                        "priceInCents": 13875,
                        "currency": "JPY",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "13875.00"
    assert not _price_repair_facts(result, "explicit_minor_unit_price")


def test_decimal_major_unit_price_remains_unchanged() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Studio Jacket</h1></main>",
        "https://shop.test/products/studio-jacket",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Studio Jacket",
                        "url": "https://shop.test/products/studio-jacket",
                        "price": "28200.50",
                        "currency": "INR",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "28200.50"
    assert not _price_repair_facts(result, "explicit_minor_unit_price")
    assert not _price_repair_facts(result, "corroborated_price_scale")


def test_independent_parent_price_corroborates_variant_minor_unit_scale() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Road Hoodie",
          "url": "https://shop.test/products/road-hoodie",
          "offers": {"price": "138.75", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/road-hoodie",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Road Hoodie",
                    "url": "https://shop.test/products/road-hoodie",
                    "variants": [
                        {
                            "variantId": "brown-m",
                            "sku": "ROAD-BRN-M",
                            "size": "M",
                            "price": 13875,
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "138.75"
    assert result.records[0]["variants"][0]["price"] == "138.75"
    facts = _price_repair_facts(result, "corroborated_price_scale")
    assert any(fact.value == "138.75" for fact in facts)
    repaired_evidence_ids = {
        evidence_id for fact in facts for evidence_id in fact.input_evidence_ids
    }
    assert any(
        item.evidence_id in repaired_evidence_ids
        and item.fact_type == "offer.price"
        and item.raw_value == 13875
        for item in result.evidence
    )


def test_parent_price_band_corroborates_different_variant_minor_unit_prices() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Luna Bag",
          "url": "https://shop.test/products/luna-bag",
          "offers": {"price": "59400", "priceCurrency": "INR"}
        }
        </script>
        """,
        "https://shop.test/products/luna-bag",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Luna Bag",
                    "url": "https://shop.test/products/luna-bag",
                    "variants": [
                        {
                            "variantId": "luna-small",
                            "sku": "LUNA-S",
                            "size": "S",
                            "price": 4170000,
                            "currency": "INR",
                        },
                        {
                            "variantId": "luna-medium",
                            "sku": "LUNA-M",
                            "size": "M",
                            "price": 5250000,
                            "currency": "INR",
                        },
                        {
                            "variantId": "luna-large",
                            "sku": "LUNA-L",
                            "size": "L",
                            "price": 5940000,
                            "currency": "INR",
                        },
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "59400.00"
    assert {row["size"]: row["price"] for row in result.records[0]["variants"]} == {
        "S": "41700.00",
        "M": "52500.00",
        "L": "59400.00",
    }
    repaired_evidence_ids = {
        evidence_id
        for fact in _price_repair_facts(result, "corroborated_price_scale")
        for evidence_id in fact.input_evidence_ids
    }
    assert {
        item.raw_value
        for item in result.evidence
        if item.evidence_id in repaired_evidence_ids
    } >= {4170000, 5250000, 5940000}


def test_parent_currency_outranks_stray_dom_currency_for_variant_scale() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Luna Bag","url":"https://shop.test/products/luna-bag","offers":{"price":"59500","priceCurrency":"INR"}}
        </script>
        <main><h1>Luna Bag</h1><div class="price">USD 595.00</div></main>
        """,
        "https://shop.test/products/luna-bag",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Luna Bag",
                    "url": "https://shop.test/products/luna-bag",
                    "variants": [
                        {
                            "variantId": "luna-small",
                            "sku": "LUNA-S",
                            "size": "S",
                            "price": 4170000,
                            "currency": "INR",
                        },
                        {
                            "variantId": "luna-large",
                            "sku": "LUNA-L",
                            "size": "L",
                            "price": 5950000,
                            "currency": "INR",
                        },
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "59500.00"
    assert {row["size"]: row["price"] for row in result.records[0]["variants"]} == {
        "S": "41700.00",
        "L": "59500.00",
    }


def test_ten_x_peer_does_not_scale_normal_major_unit_price() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Arrival Shorts","url":"https://shop.test/products/arrival-shorts","offers":{"price":"20","priceCurrency":"USD"},"hasVariant":[{"@type":"Product","sku":"ARRIVAL-3XL","size":"3XL","offers":{"price":"20","priceCurrency":"USD"}}]}
        </script>
        """,
        "https://shop.test/products/arrival-shorts",
        artifacts={
            "js_state_objects": {
                "productData": {
                    "name": "Arrival Shorts",
                    "getTheLookProducts": [
                        {
                            "name": "Related Socks",
                            "variants": [
                                {
                                    "variantId": "related-socks",
                                    "sku": "SOCKS-S",
                                    "size": "S",
                                    "price": 2,
                                    "currency": "USD",
                                }
                            ],
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "20.00"
    assert result.records[0]["variants"][0]["price"] == "20.00"


def test_primary_structured_offer_outranks_conflicting_secondary_currency() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <meta property="product:price:amount" content="1400.00">
        <meta property="product:price:currency" content="USD">
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Lip Balm","url":"https://shop.test/en-in/products/lip-balm","image":"https://shop.test/lip-balm.jpg","offers":{"price":"1400","priceCurrency":"INR"}}
        </script>
        <script>
        var meta = {"product":{"id":721,"variants":[{"id":412,"price":180000,"sku":"BALM-BDAY","public_title":"Birthday"}]},"page":{"pageType":"product"}};
        </script>
        """,
        "https://shop.test/en-in/products/lip-balm",
    )

    record = result.records[0]
    assert record["price"] == "1400.00"
    assert record["currency"] == "INR"
    assert record["variants"][0]["price"] == "1800.00"
    assert record["variants"][0]["currency"] == "INR"


def test_uniform_variant_offer_populates_missing_parent_offer() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context":"https://schema.org",
          "@type":"ProductGroup",
          "name":"Kids Tank",
          "url":"https://shop.test/products/kids-tank",
          "image":"https://shop.test/kids-tank.jpg",
          "hasVariant":[
            {"@type":"Product","sku":"TANK-S","size":"S","offers":{"price":"70","priceCurrency":"USD"}},
            {"@type":"Product","sku":"TANK-M","size":"M","offers":{"price":"70","priceCurrency":"USD"}}
          ]
        }
        </script>
        """,
        "https://shop.test/products/kids-tank",
    )

    record = result.records[0]
    assert record["price"] == "70.00"
    assert record["currency"] == "USD"
    assert record["_lineage"]["price"]["rule_id"] == ("uniform_variant_offer_aggregate")


def test_same_offer_formatted_price_corroborates_raw_minor_unit_price() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Air Jordan 5 Retro</h1></main>",
        "https://shop.test/products/air-jordan-5-retro",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Air Jordan 5 Retro",
                        "url": "https://shop.test/products/air-jordan-5-retro",
                        "price": 21500,
                        "formattedPrice": "USD 215.00",
                        "currency": "USD",
                        "variants": [
                            {
                                "variantId": "jordan-8",
                                "sku": "JORDAN-8",
                                "size": "8",
                                "price": 21500,
                                "formattedPrice": "USD 215.00",
                                "currency": "USD",
                            },
                            {
                                "variantId": "jordan-9",
                                "sku": "JORDAN-9",
                                "size": "9",
                                "price": 21500,
                                "formattedPrice": "USD 215.00",
                                "currency": "USD",
                            },
                        ],
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "215.00"
    assert {row["price"] for row in result.records[0]["variants"]} == {"215.00"}
    facts = _price_repair_facts(result, "corroborated_price_scale")
    assert any(fact.value == "215.00" for fact in facts)
    assert any(
        item.fact_type == "offer.price" and item.raw_value == 21500 and not item.flags
        for item in result.evidence
    )


def test_uncorroborated_expensive_inr_price_is_not_divided() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Collector Handbag</h1></main>",
        "https://shop.test/products/collector-handbag",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Collector Handbag",
                        "url": "https://shop.test/products/collector-handbag",
                        "price": 2820000,
                        "currency": "INR",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "2820000.00"


def test_parent_current_price_does_not_scale_variant_original_price() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Road Hoodie",
          "url": "https://shop.test/products/road-hoodie",
          "offers": {"price": "138.75", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/road-hoodie",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Road Hoodie",
                    "url": "https://shop.test/products/road-hoodie",
                    "variants": [
                        {
                            "variantId": "brown-m",
                            "sku": "ROAD-BRN-M",
                            "size": "M",
                            "price": "150",
                            "originalPrice": 13875,
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    variant = result.records[0]["variants"][0]
    assert variant["price"] == "150.00"
    assert variant["original_price"] == "13875.00"
    assert not any(
        fact.rule_id == "corroborated_price_scale"
        for fact in result.derived_facts
        if fact.fact_type == "offer.original_price"
    )
