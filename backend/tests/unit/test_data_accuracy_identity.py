from __future__ import annotations

import json

from app.core.config.extraction_rules import normalize_availability_value
from app.core.records.product_identity import (
    target_offer_group_id,
    target_product_owner_id,
)
from app.core.records.url_identity import selected_variant_axes
from app.core.records.variant_identity import variant_values_support_selection
from app.extraction import Surface, extract
from app.extraction.replay import fixture_request_from_inputs


def _extract(html: str, url: str, *fields: str):
    return extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            html,
            url,
            requested_url=url,
            requested_fields=fields,
        )
    )


def test_requested_product_title_and_url_outrank_family_sibling() -> None:
    url = "https://stockx.com/nike-dunk-low-retro-white-black-2021"
    state = {
        "product": {
            "breadcrumbs": [
                {"name": "Nike Dunk Low Retro Varsity Jacket", "url": "/nike/dunk"},
                {
                    "name": "Nike Dunk Low Retro White Black Panda",
                    "url": url,
                },
            ]
        }
    }
    html = f"""
    <html><head>
      <meta property="og:title" content="Nike Dunk Low Retro White Black Panda">
      <meta property="og:url" content="{url}">
      <script id="__NEXT_DATA__" type="application/json">{json.dumps(state)}</script>
    </head><body><h1>Nike Dunk Low Retro White Black Panda</h1></body></html>
    """

    result = _extract(html, url, "title")

    assert result.records[0]["title"] == "Nike Dunk Low Retro White Black Panda"
    assert result.records[0]["url"] == url


def test_url_slug_is_not_published_from_anti_automation_shell() -> None:
    url = (
        "https://www.amazon.com/Sparkling-Prebiotic-Beverage-Vinegar-Seltzer/"
        "dp/B0F5Y3X8PP/?th=1"
    )
    html = """
    <html><head><title>Amazon.com</title></head><body>
      <p>To discuss automated access to Amazon data, use our APIs.</p>
      <form action="/errors_page/validateCaptcha">
        <button>Continue shopping</button>
      </form>
    </body></html>
    """

    result = _extract(html, url, "title", "brand", "price", "currency")

    assert result.records == ()
    assert result.verdict == "error"
    assert any(
        finding.rule_id == "HTTP_SHELL_TITLE" and finding.blocking
        for finding in result.findings
    )


def test_requested_variant_query_selects_matching_structured_variant() -> None:
    url = (
        "https://shop.test/products/soleil/ME988?fit=Classic"
        "&colorProductCode=CI939&colorCode=BR8825"
    )
    product = {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Soleil pant in linen",
        "productGroupID": "ME988",
        "hasVariant": [
            {
                "@type": "Product",
                "name": "Petite Soleil pant in linen",
                "sku": "CI940-BR8825",
                "url": "https://shop.test/products/soleil/ME988?fit=Petite&colorProductCode=CI940&colorCode=BR8825",
                "color": "Smoked Walnut",
                "offers": {"@type": "Offer", "price": "140", "priceCurrency": "USD"},
            },
            {
                "@type": "Product",
                "name": "Soleil pant in linen",
                "sku": "CI939-BR8825",
                "url": url,
                "color": "Smoked Walnut",
                "offers": {"@type": "Offer", "price": "145", "priceCurrency": "USD"},
            },
        ],
    }

    result = _extract(
        f'<script type="application/ld+json">{json.dumps(product)}</script>',
        url,
        "title",
        "price",
        "currency",
        "variants",
    )

    assert result.records[0]["price"] == "145.00"
    assert result.records[0]["url"] == url


def test_requested_variant_path_is_preserved_as_selected_state() -> None:
    url = "https://shop.test/product/shoe/9984296/color/318988"
    result = _extract("<h1>Trail Shoe</h1>", url, "title", "variants")

    assert result.records[0]["url"] == url
    assert result.records[0].get("variants") == ()


def test_product_color_from_structured_product_stays_product_scoped() -> None:
    url = "https://shop.test/products/trail-shoe"
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Trail Shoe",
        "url": url,
        "color": "Berry",
    }

    result = _extract(
        f'<script type="application/ld+json">{json.dumps(product)}</script>',
        url,
        "title",
        "color",
    )

    assert result.records[0]["color"] == "Berry"
    assert result.records[0].get("variants") == ()


def test_coming_soon_remains_distinct_from_out_of_stock() -> None:
    assert normalize_availability_value("Coming Soon") == "coming_soon"


def test_query_selected_axes_store_stripped_values() -> None:
    assert selected_variant_axes(
        "https://shop.test/products/item?size=%20Large%20&dwvar_item_color=%20Blue%20"
    ) == {"size": "Large", "color": "Blue"}


def test_fragment_path_selected_axes_are_preserved() -> None:
    assert selected_variant_axes("https://shop.test/products/item#/sku/189322") == {
        "sku": "189322"
    }


def test_selected_variant_values_match_alphanumeric_token_sequences() -> None:
    assert variant_values_support_selection(
        ("Classic fit", "CI939-BR8825"), ("classic", "CI939 BR8825")
    )
    assert not variant_values_support_selection(("Classical fit",), ("classic",))
    assert not variant_values_support_selection(("CI939", "BR8825"), ("CI939-BR8825",))


def test_target_offer_group_requires_exact_url_or_product_id() -> None:
    target = "https://shop.test/tea/dp/large"

    assert target_offer_group_id(target, product_id="large")
    assert target_offer_group_id(target, "https://shop.test/tea/dp/large")
    assert not target_offer_group_id(target, f"{target}?sku=small")
    assert target_offer_group_id(f"{target}?sku=large", f"{target}?sku=large")
    assert not target_offer_group_id(f"{target}?sku=large", f"{target}?sku=small")
    assert not target_offer_group_id(target, "https://shop.test/tea/dp/small", "large")


def test_target_product_owner_requires_target_group_and_unique_product() -> None:
    assert (
        target_product_owner_id(True, None, ("product-1", "product-1")) == "product-1"
    )
    assert target_product_owner_id(True, None, ("product-1", "product-2")) is None
    assert target_product_owner_id(False, None, ("product-1",)) is None


def test_target_structured_offer_joins_jsonld_bounds() -> None:
    url = "https://shop.test/tea/dp/large"
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Breakfast Tea",
        "url": url,
        "offers": {
            "@type": "AggregateOffer",
            "url": url,
            "lowPrice": "15.00",
            "highPrice": "20.00",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock",
        },
    }
    state = {
        "product": {
            "name": "Breakfast Tea",
            "entryID": "large",
            "advertisedPrice": "$20.00",
            "strikeThroughPrice": "$25.00",
            "inStock": True,
        }
    }
    html = (
        f'<script type="application/ld+json">{json.dumps(product)}</script>'
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(state)}</script>'
    )

    result = _extract(html, url, "price", "original_price", "currency", "availability")
    record = result.records[0]

    assert record["price"] == "20.00"
    assert record["original_price"] == "25.00"
    assert record["price_min"] == "15.00"
    assert record["price_max"] == "20.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"


def test_exact_target_aggregate_offer_outranks_sibling_offer() -> None:
    url = "https://shop.test/tea/dp/large"
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Breakfast Tea",
        "url": url,
        "offers": {
            "@type": "AggregateOffer",
            "url": url,
            "lowPrice": "20.00",
            "highPrice": "20.00",
            "priceCurrency": "USD",
            "offerCount": 1,
            "offers": [
                {
                    "@type": "Offer",
                    "url": f"{url}?sku=small",
                    "price": "20.00",
                    "priceCurrency": "USD",
                    "availability": "https://schema.org/InStock",
                }
            ],
        },
    }

    result = _extract(
        f'<script type="application/ld+json">{json.dumps(product)}</script>',
        url,
        "price",
        "price_min",
        "price_max",
        "currency",
        "availability",
    )
    record = result.records[0]

    assert record["price"] == "20.00"
    assert record["price_min"] == "20.00"
    assert record["price_max"] == "20.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"


def test_trademark_symbols_are_stripped_from_published_identity() -> None:
    url = "https://example.com/products/millennium-falcon-75192"
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Millennium Falcon® 75192",
        "brand": {"@type": "Brand", "name": "LEGO®"},
    }

    result = _extract(
        f'<script type="application/ld+json">{json.dumps(product)}</script>',
        url,
        "title",
        "brand",
    )
    record = result.records[0]

    assert record["title"] == "Millennium Falcon 75192"
    assert record["brand"] == "LEGO"


def test_trademark_symbol_still_bounds_url_corroborated_brand() -> None:
    """The symbol is removed from output but remains usable as a boundary
    signal, so a URL-corroborated brand is still recoverable from the title."""
    url = "https://www.example.com/products/breville-the-bambino-plus/"
    html = (
        "<html><head>"
        "<title>Breville Bambino® Plus Espresso Machine</title>"
        "</head><body>"
        "<h1>Breville Bambino® Plus Espresso Machine</h1>"
        "</body></html>"
    )

    result = _extract(html, url, "title", "brand")
    record = result.records[0]

    assert record["title"] == "Breville Bambino Plus Espresso Machine"
    assert record["brand"] == "Breville"


def test_site_name_suffix_is_stripped_using_page_host() -> None:
    """The trailing segment is identified as site boilerplate by matching the
    page host, so no retailer vocabulary is involved."""
    url = "https://www.karenmillen.com/products/barrel-leg-trouser"
    html = (
        "<html><head>"
        "<title>Ivory Cotton Barrel Leg Trouser | Karen Millen ROW</title>"
        "</head><body><h1>Ivory Cotton Barrel Leg Trouser | Karen Millen ROW</h1>"
        "</body></html>"
    )

    result = _extract(html, url, "title")

    assert result.records[0]["title"] == "Ivory Cotton Barrel Leg Trouser"


def test_trailing_segment_unrelated_to_host_is_kept() -> None:
    """A colourway or style code after the same separator is product identity,
    not site boilerplate, so it survives."""
    url = "https://www.kitchenaid.com/products/food-processor"
    html = (
        "<html><head><title>13-Cup Food Processor - Contour Silver</title>"
        "</head><body><h1>13-Cup Food Processor - Contour Silver</h1></body></html>"
    )

    result = _extract(html, url, "title")

    assert result.records[0]["title"] == "13-Cup Food Processor - Contour Silver"


def test_identifier_label_prefix_is_not_part_of_the_sku() -> None:
    url = "https://shop.test/products/crosscut-sled"
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Table Saw Crosscut Sled",
        "sku": "Item # 77295",
    }

    result = _extract(
        f'<script type="application/ld+json">{json.dumps(product)}</script>',
        url,
        "sku",
    )

    assert result.records[0]["sku"] == "77295"


def test_structured_product_attributes_are_published() -> None:
    """rating, review count, material, gender, condition, style id and barcode
    all reach the record from a single schema.org product node."""
    url = "https://shop.test/products/trail-shoe"
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Trail Shoe",
        "url": url,
        "productGroupID": "TS-100",
        "gtin13": "0123456789012",
        "material": "Suede",
        "itemCondition": "https://schema.org/NewCondition",
        "audience": {"@type": "PeopleAudience", "suggestedGender": "Male"},
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": "4.5",
            "reviewCount": "218",
        },
    }

    result = _extract(
        f'<script type="application/ld+json">{json.dumps(product)}</script>',
        url,
        "rating",
        "review_count",
        "materials",
        "gender",
        "condition",
        "style_id",
        "barcode",
    )
    record = result.records[0]

    # Published as strings today, like price; the canonical schema declares them
    # numeric. Tracked as a contract gap in the accuracy report.
    assert str(record["rating"]) == "4.5"
    assert str(record["review_count"]) == "218"
    assert record["materials"] == "Suede"
    # schema.org enumerations publish as plain wording, in bare or URL form.
    assert record["gender"] == "Men"
    assert record["condition"] == "New"
    assert record["style_id"] == "TS-100"
    assert record["barcode"] == "0123456789012"


def test_product_declared_sku_survives_a_matching_variant_sku() -> None:
    """The parent-SKU guard must block a promoted variant SKU, not a SKU the
    product node declares for itself."""
    url = "https://shop.test/products/tee"
    product = {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Tee",
        "url": url,
        "sku": "TEE-BASE",
        "hasVariant": [
            {"@type": "Product", "sku": "TEE-BASE", "url": f"{url}?size=s"},
            {"@type": "Product", "sku": "TEE-M", "url": f"{url}?size=m"},
        ],
    }

    result = _extract(
        f'<script type="application/ld+json">{json.dumps(product)}</script>',
        url,
        "sku",
    )

    assert result.records[0]["sku"] == "TEE-BASE"


def test_audience_gender_comes_from_the_requested_pdp_path() -> None:
    """A site may redirect a unisex PDP into a gendered department; the path the
    caller requested states the product they asked for."""
    requested = "https://shop.test/p/chuck-taylor-unisex-high-top-shoe/A16914F.html"
    served = "https://shop.test/p/chuck-taylor-womens-high-top-shoe/A16914F.html"
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            "<h1>Chuck Taylor High Top</h1>",
            served,
            requested_url=requested,
            requested_fields=("gender",),
        )
    )

    assert result.records[0]["gender"] == "Unisex"


def test_gender_is_not_inferred_from_query_state_or_unrelated_tokens() -> None:
    url = "https://shop.test/products/plain-tee?dwvar_color=womens-pink"
    result = _extract("<h1>Plain Tee</h1>", url, "gender")

    assert result.records[0].get("gender") is None


def test_price_that_states_its_own_cents_is_not_rescaled() -> None:
    """A source printing fractional digits states a major-unit price. Without
    this guard an unrelated peer within the corroboration ratio rescales a
    correct 215.00 into 2.15."""
    from app.core.shared.field_coerce_price import repair_price_unit

    assert (
        repair_price_unit(
            "Regular price $215.00",
            source_key=".price",
            currency="USD",
            corroborating_values=("4",),
        )
        is None
    )
    assert (
        repair_price_unit(
            "215.0",
            source_key="/offers/0/price",
            currency="USD",
            corroborating_values=("4",),
        )
        is None
    )
    # A genuine minor-unit integer still repairs against a corroborating peer.
    assert repair_price_unit(
        "21500",
        source_key="/variants/0/price",
        currency="USD",
        corroborating_values=("215.00",),
    ) == ("215.00", "corroborated_price_scale")


def test_primary_offer_inherits_a_unanimous_sibling_availability() -> None:
    """DOM offers often carry price while a structured offer carries stock."""
    url = "https://shop.test/products/crosscut-sled"
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Crosscut Sled",
        "url": url,
        "sku": "77295",
        "offers": {
            "@type": "Offer",
            "url": url,
            "price": "249.99",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock",
        },
    }
    html = (
        f'<script type="application/ld+json">{json.dumps(product)}</script>'
        '<div class="price">$249.99</div>'
    )

    result = _extract(html, url, "price", "currency", "availability")

    assert result.records[0]["availability"] == "in_stock"
