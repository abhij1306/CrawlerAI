from __future__ import annotations

import pytest

from bs4 import BeautifulSoup

from app.services.extract.detail.assembly.final_cleanup import (
    _reconcile_variant_derived_parent_fields,
    repair_ecommerce_detail_record_quality,
    sanitize_variant_row,
)
from app.services.extract.detail.price.core import backfill_detail_price_from_html
from app.services.extract.variant_normalization import normalize_variant_record
from app.services.extract.variant_normalization import backfill, hydration, sanitization
from app.services.extract.variant_normalization.contract import enforce_payload_limits
from app.services.shared.field_coerce import coerce_field_value
from app.services.dom.selector_engine import extract_node_value
from app.services.normalizers import normalize_decimal_price, normalize_value


@pytest.mark.unit
def test_preserve_existing_localized_money_without_jsonld_price() -> None:
    record = {
        "url": "https://fentybeauty.com/en-in/products/body-mist",
        "currency": "INR",
        "price": "INR 1,999",
    }
    html = """
    <html><head>
      <meta property="product:price:currency" content="USD">
    </head><body><h1>Body Mist</h1></body></html>
    """

    backfill_detail_price_from_html(record, html=html)

    assert record["currency"] == "INR"
    assert record["price"] == "INR 1,999"


@pytest.mark.unit
def test_coerce_category_reads_locale_dict_string() -> None:
    assert (
        coerce_field_value(
            "category",
            "{'en': 'LEATHER JACKETS'}",
            "https://www.ssense.com/en-us/men/product/example/1",
        )
        == "LEATHER JACKETS"
    )


@pytest.mark.unit
def test_normalize_additional_images_preserves_url_lists_with_commas() -> None:
    value = normalize_value(
        "additional_images",
        [
            "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-2.jpg",
            "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-3.jpg",
        ],
    )

    assert value == [
        "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-2.jpg",
        "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-3.jpg",
    ]


@pytest.mark.unit
def test_normalize_decimal_price_rejects_ambiguous_integer_text_without_price_context() -> (
    None
):
    assert normalize_decimal_price("126") is None


@pytest.mark.unit
def test_normalize_decimal_price_accepts_currency_context_for_integer_text() -> None:
    assert normalize_decimal_price("$126") == "126"
    assert normalize_decimal_price("Rs. 499") == "499"
    assert normalize_decimal_price("INR 499") == "499"


@pytest.mark.unit
def test_normalize_decimal_price_accepts_price_keyword_context_for_integer_text() -> (
    None
):
    assert normalize_decimal_price("price 126") == "126"


@pytest.mark.unit
def test_normalize_decimal_price_preserves_decimal_strings_without_currency_symbol() -> (
    None
):
    assert normalize_decimal_price("59.99") == "59.99"


@pytest.mark.unit
def test_normalize_decimal_price_supports_suffix_currency_and_decimal_comma() -> None:
    assert normalize_decimal_price("62,99 €") == "62.99"


@pytest.mark.unit
def test_normalize_decimal_price_treats_dot_thousands_as_grouping() -> None:
    assert normalize_decimal_price("€17.000") == "17000"


@pytest.mark.unit
def test_normalize_decimal_price_rejects_negative_values() -> None:
    # Regression: gemini audit DQ-4 — Gucci/Sony emitted -1 / -9 default
    # fallbacks that leaked into exports. Negative prices must become None.
    assert normalize_decimal_price("-1") is None
    assert normalize_decimal_price("-9.99") is None
    assert normalize_decimal_price("$-1") is None
    assert normalize_decimal_price("-$1") is None
    assert normalize_decimal_price("-USD100") is None
    assert normalize_decimal_price("−1") is None
    assert normalize_decimal_price("$−1") is None


@pytest.mark.unit
def test_normalize_integer_field_handles_unicode_minus_as_negative() -> None:
    assert normalize_value("stock_quantity", "−123") == -123


@pytest.mark.unit
def test_normalize_decimal_price_rejects_structured_types() -> None:
    assert normalize_decimal_price({"key": "val"}) is None
    assert normalize_decimal_price([100, 200]) is None
    assert normalize_decimal_price(("100",)) is None
    assert normalize_decimal_price({100, 200}) is None


@pytest.mark.unit
def test_variant_payload_limit_accepts_explicit_max_rows() -> None:
    record = {
        "variants": [
            {"size": "S", "url": "https://example.test/s"},
            {"size": "M", "url": "https://example.test/m"},
            {"size": "L", "url": "https://example.test/l"},
        ],
        "variant_count": 3,
    }

    enforce_payload_limits(record, max_rows=2)

    assert record["variants"] == [
        {"size": "S", "url": "https://example.test/s"},
        {"size": "M", "url": "https://example.test/m"},
    ]
    assert record["variant_count"] == 2


@pytest.mark.unit
def test_normalize_variant_record_drops_geographic_state_dropdown_rows() -> None:
    record: dict[str, object] = {
        "title": "EOS R5 Body",
        "variants": [
            {"state": "Alabama"},
            {"state": "Alaska"},
            {"state": "California"},
            {"state": "Texas"},
        ],
        "variant_count": 4,
    }

    normalize_variant_record(record)

    assert "variants" not in record
    assert "variant_count" not in record


@pytest.mark.unit
def test_repair_ecommerce_detail_reconciles_parent_price_against_unanimous_variants() -> (
    None
):
    # Regression: gemini audit DQ-7 (Selfridges) — parent price 190 with both
    # variants reporting 310 is a stale/unrelated DOM scrape. The reconciler
    # should adopt the unanimous variant price as the parent.
    record: dict[str, object] = {
        "price": "190.00",
        "currency": "GBP",
        "variants": [
            {"price": "310.00", "currency": "GBP", "size": "50ml"},
            {"price": "310.00", "currency": "GBP", "size": "100ml"},
        ],
    }
    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url="https://www.selfridges.com/GB/en/cat/example/",
        requested_page_url="https://www.selfridges.com/GB/en/cat/example/",
    )
    assert record["price"] == "310.00"


@pytest.mark.unit
def test_repair_ecommerce_detail_skips_variant_range_reconcile_when_magnitudes_differ() -> (
    None
):
    # Guard: when parent and variant prices differ by >~2x, the mismatch is
    # more likely a cents/units magnitude issue handled by the dedicated
    # magnitude reconciler. The variant-range reconciler must not overwrite
    # the parent in that case.
    record: dict[str, object] = {
        "price": "282.00",
        "currency": "USD",
        "variants": [
            {"price": "28200", "currency": "USD"},
        ],
    }
    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url="https://example.com/p",
        requested_page_url="https://example.com/p",
    )
    assert record["price"] == "282.00"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("url", "record", "expected_brand"),
    [
        (
            "https://www.endclothing.com/us/47-ny-yankees-clean-up-cap-b-rgw17gws-vn.html",
            {"title": "47 NY Yankees Clean Up Cap", "price": "35.00"},
            "47",
        ),
        (
            "https://www.firstcry.com/babyhug/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail",
            {
                "title": "Babyhug Denim Woven Sleeveless Top & Pant Set With Floral Print - Blue",
                "price": "868.21",
            },
            "Babyhug",
        ),
        (
            "https://www.aesop.com/home-fragrance/candles/aganice-aromatique-candle/HM03.html",
            {"title": "Aganice Aromatique Candle", "price": "120.00"},
            "Aesop",
        ),
        (
            "https://amsterdamvintagewatches.com/shop/rolex-day-date-18038-champagne-5/",
            {
                "title": "Rolex Day-Date 18038 - Amsterdam Vintage Watches",
                "price": "43000.00",
            },
            "Rolex",
        ),
    ],
)
def test_repair_ecommerce_detail_backfills_missing_brand_from_identity(
    url: str,
    record: dict[str, object],
    expected_brand: str,
) -> None:
    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url=url,
        requested_page_url=url,
    )

    assert record["brand"] == expected_brand


@pytest.mark.unit
def test_repair_ecommerce_detail_backfills_game_publisher_brand_from_description() -> (
    None
):
    record: dict[str, object] = {
        "title": "PRAGMATA",
        "price": "59.99",
        "description": "A new sci-fi adventure from Capcom's upcoming lineup.",
    }
    url = "https://www.nintendo.com/us/store/products/pragmata-switch-2/"

    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url=url,
        requested_page_url=url,
    )

    assert record["brand"] == "Capcom"


@pytest.mark.unit
def test_repair_ecommerce_detail_prunes_child_pdp_variants_from_adult_product() -> None:
    url = "https://www.dtlr.com/collections/men/products/jordan-air-jordan-5-retro-white-metallic-mf-white-hq7978-103"
    record: dict[str, object] = {
        "title": "Jordan Air Jordan 5 Retro 'White Metallic'",
        "price": "215.00",
        "variants": [
            {"size": "8", "price": "215", "url": f"{url}?variant=adult"},
            {
                "size": "4",
                "price": "165",
                "color": "Grade School Jf White Hq7980 103",
                "url": "https://www.dtlr.com/collections/men/products/jordan-air-jordan-5-retro-white-metallic-grade-school-jf-white-hq7980-103?variant=gs",
            },
            {
                "size": "5",
                "price": "90",
                "color": "Toddler If White Hq7981 103",
                "url": "https://www.dtlr.com/collections/men/products/jordan-air-jordan-5-retro-white-metallic-toddler-if-white-hq7981-103?variant=td",
            },
        ],
    }

    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url=url,
        requested_page_url=url,
    )

    assert len(record["variants"]) == 1
    assert record["variants"][0]["size"] == "8"
    assert record["variants"][0]["url"] == f"{url}?variant=adult"
    assert record["variant_count"] == 1


@pytest.mark.unit
def test_infer_shared_variant_color_drops_trailing_style_code_tokens() -> None:
    record = {
        "title": "Jordan Air Jordan 5 Retro 'White Metallic'",
        "url": "https://www.dtlr.com/collections/men/products/jordan-air-jordan-5-retro-white-metallic-mf-white-hq7978-103",
        "variants": [
            {"size": "8"},
            {"size": "8.5"},
            {"size": "9"},
        ],
    }

    hydration._hydrate_variant_axes(record)

    assert [variant.get("color") for variant in record["variants"]] == [
        "White",
        "White",
        "White",
    ]


@pytest.mark.unit
def test_repair_ecommerce_detail_drops_color_values_misread_as_sizes() -> None:
    url = "https://www.macys.com/shop/product/tommy-hilfiger-mens-hiday-casualized-hybrid-oxfords"
    record: dict[str, object] = {
        "title": "Tommy Hilfiger Mens Virat Casualized Hybrid Oxfords",
        "variants": [
            {"size": "7M", "color": "Cognac"},
            {"size": "Cognac", "color": "Cognac"},
            {"size": "Black", "color": "Cognac"},
            {"size": "8M", "color": "Black"},
            {"size": "Black", "color": "Black"},
        ],
    }

    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url=url,
        requested_page_url=url,
    )

    assert record["variants"] == [
        {"size": "7M", "color": "Cognac"},
        {"size": "8M", "color": "Black"},
    ]


@pytest.mark.unit
def test_repair_ecommerce_detail_drops_same_url_color_only_variant_cluster() -> None:
    url = "https://colourpop.com/products/going-coconuts-eyeshadow-palette"
    record: dict[str, object] = {
        "title": "Going Coconuts",
        "variants": [
            {"color": "Pink Dreams", "url": f"{url}?variant=31181373636690"},
            {"color": "Blue Moon", "url": f"{url}?variant=31181373636690"},
        ],
    }

    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url=url,
        requested_page_url=url,
    )

    assert "variants" not in record
    assert "variant_count" not in record


@pytest.mark.unit
def test_repair_ecommerce_detail_filters_related_and_low_res_images() -> None:
    url = "https://www.aesop.com/home-fragrance/candles/aganice-aromatique-candle/HM03.html"
    record: dict[str, object] = {
        "title": "Aganice Aromatique Candle",
        "image_url": "https://www.aesop.com/dw/image/v2/AANG_PRD/on/demandware.static/-/Sites-aesop-us-master-catalog/default/dwdbcd8bbe/images/products/HM03/Aesop_Home_Aganice_Aromatique_Candle_Web_Front_2000x2000px.png",
        "additional_images": [
            "https://www.aesop.com/dw/image/v2/AANG_PRD/on/demandware.static/-/Sites-aesop-us-master-catalog/default/dw00834621/images/products/HM03/Aesop_Home_Aganice_Aromatique_Candle_Vessel_&_Carton_Front_2000x2000px.jpg?sw=1536&sh=1536",
            "https://www.aesop.com/dw/image/v2/AANG_PRD/on/demandware.static/-/Sites-aesop-us-master-catalog/default/dwb2be19cc/images/products/FR11/Aesop_Fragrance_Marrakech_Intense_Parfum_10mL_Vial_NGL_2000x2000px.jpg?sw=330&sh=330",
            "https://www.aesop.com/dw/image/v2/AANG_PRD/on/demandware.static/Sites-aesop-us-Site/-/default/dw9315f36d/images/landscape.png?sw=304&sh=250",
        ],
    }

    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url=url,
        requested_page_url=url,
    )

    assert record["additional_images"] == [
        "https://www.aesop.com/dw/image/v2/AANG_PRD/on/demandware.static/-/Sites-aesop-us-master-catalog/default/dw00834621/images/products/HM03/Aesop_Home_Aganice_Aromatique_Candle_Vessel_&_Carton_Front_2000x2000px.jpg?sw=1536&sh=1536"
    ]


@pytest.mark.unit
def test_repair_ecommerce_detail_prefers_active_color_image_and_drops_swatch_thumbs() -> (
    None
):
    url = "https://www.patagonia.com/product/mens-nano-puff-insulated-jacket/84213.html"
    record: dict[str, object] = {
        "title": "Men's Nano Puff Jacket",
        "brand": "Patagonia",
        "color": "Aquatic Blue",
        "image_url": "https://www.patagonia.com/dw/image/v2/BDJB_PRD/on/demandware.static/-/Sites-patagonia-master/default/dw3898a537/images/hi-res/84213_SMDB.jpg?sw=1920",
        "additional_images": [
            "https://www.patagonia.com/dw/image/v2/BDJB_PRD/on/demandware.static/-/Sites-patagonia-master/default/dwb71fb616/images/hi-res/84213_AQT.jpg?sw=1920",
            "https://images.urbndata.com/is/image/Anthropologie/108064080_001_s?fit=constrain&hei=56&qlt=75",
        ],
    }

    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url=url,
        requested_page_url=url,
    )

    assert "84213_AQT" in str(record["image_url"])
    assert all(
        "_s?fit=constrain&hei=56" not in image
        for image in record.get("additional_images", [])
    )


@pytest.mark.unit
def test_normalize_variant_record_keeps_url_when_same_axis_value_is_repeated() -> None:
    record = {
        "variants": [
            {"url": "https://example.com/p?variant=red", "color": "Red", "size": "S"},
            {"url": "https://example.com/p?variant=red", "color": "Red"},
        ],
    }

    normalize_variant_record(record)

    assert all(variant.get("url") for variant in record["variants"])  # nosec B101


@pytest.mark.unit
def test_repair_ecommerce_detail_trims_description_to_url_identity_chunk() -> None:
    url = "https://www.macys.com/shop/product/tommy-hilfiger-mens-hiday-casualized-hybrid-oxfords"
    record: dict[str, object] = {
        "title": "Tommy Hilfiger Mens Virat Casualized Hybrid Oxfords",
        "description": (
            "The Hiday men's lace-up oxford has a classic silhouette. "
            "Subtle branding details have been added. "
            "Elevate everyday style with these Tommy Hilfiger Foray sneakers. "
            "The Florsheim Midtown shoe is a different product."
        ),
    }

    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url=url,
        requested_page_url=url,
    )

    assert "Hiday" in str(record["description"])
    assert "Foray" not in str(record["description"])
    assert "Florsheim" not in str(record["description"])


@pytest.mark.unit
def test_coerce_field_value_category_rejects_url_path_strings() -> None:
    # Regression: gemini audit DQ-8 — Vans exposed a joined URL path
    # ("https: > www.vans.com > en-us > c > shoes > icons > old-skool-5205")
    # as the category field. URL-looking strings must be rejected so the
    # breadcrumb fallback can provide a real category label.
    assert (
        coerce_field_value(
            "category",
            "https: > www.vans.com > en-us > c > shoes > icons > old-skool-5205",
            "",
        )
        is None
    )
    assert coerce_field_value("category", "https://example.com/c/shoes", "") is None
    # But a real breadcrumb path must still pass through.
    assert (
        coerce_field_value("category", "Shoes > Icons > Old Skool", "")
        == "Shoes > Icons > Old Skool"
    )


@pytest.mark.unit
def test_normalize_value_price_preserves_semantic_integer_price_fields() -> None:
    assert normalize_value("price", "126") == "126"


@pytest.mark.unit
def test_normalize_value_price_normalizes_clean_decimal_strings() -> None:
    assert normalize_value("price", "0012.50") == "12.50"


@pytest.mark.unit
def test_normalize_value_unwraps_singleton_barcode_list_and_rounds_rating() -> None:
    assert normalize_value("barcode", "['0840424803104']") == "0840424803104"
    assert normalize_value("rating", "2.399113082039911") == pytest.approx(2.4)


@pytest.mark.unit
def test_coerce_text_fields_join_literal_list_strings() -> None:
    assert (
        coerce_field_value(
            "product_details",
            "['Leather upper with perforated toe box', 'Rubber outsole']",
            "",
        )
        == "Leather upper with perforated toe box; Rubber outsole"
    )


@pytest.mark.unit
def test_normalize_availability_schema_url() -> None:
    assert (
        normalize_value("availability", "https://schema.org/LimitedAvailability")
        == "limited_stock"
    )


@pytest.mark.unit
def test_variant_price_backfill_handles_numeric_string_equivalence() -> None:
    record: dict[str, object] = {
        "price": "10.00",
        "currency": "USD",
        "variants": [
            {"sku": "TEN", "price": 10.0},
            {"sku": "UNKNOWN"},
        ],
    }

    backfill._backfill_variant_context(record)

    assert record["variants"][0]["price"] == pytest.approx(10.0)
    assert record["variants"][1]["price"] == "10.00"


@pytest.mark.unit
def test_variant_price_backfill_treats_numeric_zero_as_distinct() -> None:
    record: dict[str, object] = {
        "price": "10.00",
        "currency": "USD",
        "variants": [
            {"sku": "FREE", "price": 0},
            {"sku": "UNKNOWN"},
        ],
    }

    backfill._backfill_variant_context(record)

    assert record["variants"][0]["price"] == 0
    assert "price" not in record["variants"][1]


@pytest.mark.unit
def test_field_coercion_repairs_source_quality_before_enrichment() -> None:
    assert coerce_field_value("brand", {"0": "Apple"}, "") == "Apple"
    assert coerce_field_value("brand", "8552", "") is None
    assert (
        coerce_field_value("availability", "https://schema.org/LimitedAvailability", "")
        == "limited_stock"
    )
    assert coerce_field_value("rating", {"ratingValue": "4.5"}, "") == pytest.approx(4.5)
    assert coerce_field_value("product_type", {"variationGroup": True}, "") is None


@pytest.mark.unit
def test_variant_option_dom_text_drops_child_price_badges() -> None:
    soup = BeautifulSoup(
        """
        <button role="radio" class="color-option">
          <span>Black</span><span>$382.00</span>
        </button>
        """,
        "html.parser",
    )

    assert extract_node_value(soup.button, "color", "https://example.com") == "Black"


@pytest.mark.unit
def test_normalize_variant_record_preserves_referenced_single_value_axes() -> None:
    record = {
        "variant_axes": {"size": ["Small", "Large"], "scent": ["Lavender"]},
        "variants": [
            {"option_values": {"size": "Small", "scent": "Lavender"}, "sku": "LAV-S"},
            {"option_values": {"size": "Large", "scent": "Lavender"}, "sku": "LAV-L"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"size": "Small", "scent": "Lavender", "sku": "LAV-S"},
        {"size": "Large", "scent": "Lavender", "sku": "LAV-L"},
    ]
    assert record["variant_count"] == 2


@pytest.mark.unit
def test_normalize_variant_record_drops_subset_rows_using_indexed_axis_lookup() -> None:
    record = {
        "variants": [
            {"size": "M"},
            {"size": "M", "color": "Black"},
            {"size": "L"},
            {"size": "L", "color": "Black"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"size": "M", "color": "Black"},
        {"size": "L", "color": "Black"},
    ]
    assert record["variant_count"] == 2


@pytest.mark.unit
def test_normalize_variant_record_drops_parent_sku_alias_rows_using_indexed_lookup() -> (
    None
):
    record = {
        "variants": [
            {"sku": "BOMBAS-BLACK", "size": "M"},
            {"sku": "BOMBAS-BLACK-M", "size": "M", "availability": "InStock"},
            {"sku": "BOMBAS-BLACK-L", "size": "L", "availability": "InStock"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"sku": "BOMBAS-BLACK-M", "size": "M", "availability": "in_stock"},
        {"sku": "BOMBAS-BLACK-L", "size": "L", "availability": "in_stock"},
    ]
    assert record["variant_count"] == 2


@pytest.mark.unit
def test_normalize_variant_record_drops_axisless_rows_and_rejects_foreign_currency() -> (
    None
):
    record = {
        "currency": "GBP",
        "variants": [
            {"sku": "SKU-ONLY", "price": "10.00", "currency": "GBP"},
            {"color": "Black", "sku": "BLACK-1", "price": "10.00", "currency": "GBP"},
            {"size": "M", "sku": "RED-M", "price": "12.00", "currency": "EUR"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"color": "Black", "sku": "BLACK-1", "price": "10.00", "currency": "GBP"}
    ]
    assert record["variant_count"] == 1


@pytest.mark.unit
def test_normalize_variant_record_drops_ui_control_variant_values() -> None:
    record = {
        "variants": [
            {"url": "javascript:void(0)", "size": "Your Cookie Settings"},
            {"size": "Show Reviews with 5 stars"},
            {"color": "Previous"},
            {"color": "Show image 1"},
            {"color": "Enable Keyboard Shortcuts:"},
            {"color": "Now & Every 15 Days"},
            {"size": "Shipping Restrictions : Sales and Export of this item"},
        ],
    }

    normalize_variant_record(record)

    assert "variants" not in record
    assert "variant_count" not in record


@pytest.mark.unit
def test_normalize_variant_record_drops_polluted_parent_scalar_axes() -> None:
    record = {
        "color": "Color",
        "size": "100 Softgels 200 Softgels 365 Softgels",
        "variants": [{"size": "100 Softgels"}, {"size": "200 Softgels"}],
    }

    normalize_variant_record(record)

    assert "color" not in record
    assert "size" not in record
    assert record["variant_count"] == 2


@pytest.mark.unit
def test_repair_ecommerce_detail_backfills_dom_variants_before_sanitizing_noise() -> (
    None
):
    html = """
    <main>
      <h1>Trail Shoe</h1>
      <select name="size">
        <option>Please select</option>
        <option>S</option>
        <option>M</option>
      </select>
    </main>
    """
    record = {
        "title": "Trail Shoe",
        "price": "49.99",
        "currency": "USD",
        "variants": [
            {"size": "Please select", "option_values": {"size": "Please select"}},
        ],
    }

    repair_ecommerce_detail_record_quality(
        record,
        html=html,
        page_url="https://example.com/products/trail-shoe",
        soup=BeautifulSoup(html, "html.parser"),
    )

    assert record["variants"] == [{"size": "S"}, {"size": "M"}]
    assert record["variant_count"] == 2


@pytest.mark.unit
def test_normalize_variant_record_drops_ce4_ui_and_cookie_axis_values() -> None:
    record = {
        "variants": [
            {"size": "Save to Wishlist"},
            {"size": "Saved to wishlist"},
            {"size": "Login to add to account Wishlist"},
            {"size": "necessary"},
            {"size": "functional"},
            {"size": "performance"},
            {"size": "targeting"},
            {"color": "Make Offer"},
            {"color": "Buy Now"},
            {"size": "sign in"},
            {"size": "Link your member number,"},
            {"size": "a lifetime of benefits."},
            {"size": "5 stars"},
            {"size": "-"},
            {"size": "+"},
        ],
    }

    normalize_variant_record(record)

    assert "variants" not in record
    assert "variant_count" not in record


@pytest.mark.unit
def test_normalize_variant_record_strips_learn_more_from_real_size() -> None:
    record = {
        "variants": [
            {
                "url": "https://www.size.co.uk/product/purple-shoe/19738059/?size=7",
                "size": "7 Learn More",
            },
            {
                "url": "https://www.size.co.uk/product/purple-shoe/19738059/?size=7-5",
                "size": "7.5 Learn More",
            },
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {
            "url": "https://www.size.co.uk/product/purple-shoe/19738059/?size=7",
            "size": "7",
        },
        {
            "url": "https://www.size.co.uk/product/purple-shoe/19738059/?size=7-5",
            "size": "7.5",
        },
    ]


@pytest.mark.unit
def test_normalize_variant_record_drops_quantity_size_controls_preserves_real_rows() -> (
    None
):
    record = {
        "variants": [
            {"size": "-", "color": "Black"},
            {"size": "+", "color": "Black"},
            {"size": "8 oz Ceramic", "color": "Black"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [{"size": "8 oz Ceramic", "color": "Black"}]
    assert record["variant_count"] == 1


@pytest.mark.unit
def test_normalize_variant_record_preserves_real_short_axes_after_ui_noise_prune() -> (
    None
):
    record = {
        "variants": [
            {"url": "https://example.com/products/shirt?variant=1", "size": "M"},
            {"url": "https://example.com/products/shirt?variant=2", "color": "Navy"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"size": "M", "url": "https://example.com/products/shirt?variant=1"},
        {"color": "Navy", "url": "https://example.com/products/shirt?variant=2"},
    ]
    assert record["variant_count"] == 2


@pytest.mark.unit
def test_normalize_variant_record_collapses_backmarket_carousel_compare_rows() -> None:
    record = {
        "variants": [
            {"color": "Previous", "storage": "128 GB", "condition": "Compare"},
            {"color": "Show image 1", "storage": "128 GB", "condition": "Compare"},
            {"color": "Next", "storage": "128 GB", "condition": "Compare"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [{"storage": "128 GB"}]
    assert record["variant_count"] == 1


@pytest.mark.unit
def test_normalize_variant_record_promotes_color_values_misfiled_as_size() -> None:
    record = {
        "variants": [
            {"size": "Smoke Green (sold out)"},
            {"size": "Matte Black sold out"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"color": "Smoke Green"},
        {"color": "Matte Black"},
    ]
    assert record["variant_count"] == 2


@pytest.mark.unit
def test_normalize_variant_record_infers_bombas_sizes_from_sku_suffixes() -> None:
    record = {
        "title": "Men's All Sport Ankle Socks",
        "variants": [
            {
                "sku": "A-E-A-129AM3-SADS-01P-BLACK-XL",
                "color": "black onyx",
                "price": "15.00",
            },
            {
                "sku": "A-E-A-129A44-CLAS-01P-BLACK-M",
                "color": "charcoal marl",
                "price": "15.00",
            },
            {
                "sku": "A-E-A-129A44-SOLI-01P-WHITE-L-2024",
                "color": "True White",
                "price": "15.00",
            },
        ],
    }

    normalize_variant_record(record)

    assert [variant.get("size") for variant in record["variants"]] == ["XL", "M", "L"]
    assert [variant.get("color") for variant in record["variants"]] == [
        "black onyx",
        "charcoal marl",
        "True White",
    ]
    assert record["variant_count"] == 3


@pytest.mark.unit
def test_normalize_variant_record_prunes_patagonia_cross_product_size_noise() -> None:
    record = {
        "title": "Men's Nano Puff Jacket",
        "gender": "Men",
        "variants": [
            {"size": "NB-7lb"},
            {"size": "0-3m"},
            {"size": "2T"},
            {"size": "XS"},
            {"size": "S"},
            {"size": "M"},
            {"size": "L"},
            {"size": "Climbing"},
            {"size": "Yoga"},
            {"size": "Runs Small"},
            {"size": "True to Size"},
        ],
    }

    normalize_variant_record(record)

    assert [variant["size"] for variant in record["variants"]] == ["XS", "S", "M", "L"]


@pytest.mark.unit
def test_normalize_variant_record_drops_backmarket_condition_tabs() -> None:
    record = {
        "variants": [
            {"color": "Black", "storage": "128 GB", "condition": "Fair"},
            {"color": "Blue", "storage": "128 GB", "condition": "Good"},
            {"color": "Black", "storage": "128 GB", "condition": "More"},
            {"color": "Black", "storage": "128 GB", "condition": "Condition (476)"},
            {"color": "Black", "storage": "128 GB", "condition": "Quality (383)"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"color": "Black", "storage": "128 GB", "condition": "Fair"},
        {"color": "Blue", "storage": "128 GB", "condition": "Good"},
    ]
    assert record["variant_count"] == 2


@pytest.mark.unit
def test_normalize_variant_record_preserves_separate_suit_sizes_with_dimension_labels() -> (
    None
):
    record = {
        "title": "Italian Seersucker Sutton Suit",
        "variants": [
            {"size": "36S"},
            {"size": "40R"},
            {"size": "28/32"},
            {"size": "34/30"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"size": "36S", "style": "Jacket"},
        {"size": "40R", "style": "Jacket"},
        {"size": "28/32", "style": "Pant"},
        {"size": "34/30", "style": "Pant"},
    ]
    assert record["variant_count"] == 4


@pytest.mark.unit
def test_normalize_variant_record_cleans_code_polluted_parent_color() -> None:
    record = {
        "title": "Jordan Air Jordan 5 Retro 'White Metallic'",
        "color": "Mf White Hq7978 103",
        "variants": [
            {"size": "8", "color": "Mf White Hq7978 103"},
            {"size": "8.5", "color": "Mf White Hq7978 103"},
        ],
    }

    normalize_variant_record(record)

    assert record["color"] == "White"


@pytest.mark.unit
def test_prune_unrecognized_size_rows_does_not_treat_any_style_as_size_dimension() -> (
    None
):
    record = {
        "title": "Sneaker",
        "variants": [
            {"size": "US 8"},
            {"size": "US 9"},
            {"size": "Comfort", "option_values": {"style": "Wide"}},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [{"size": "US 8"}, {"size": "US 9"}]
    assert record["variant_count"] == 2


@pytest.mark.unit
def test_enforce_variant_currency_context_keeps_all_mismatched_variants_for_review() -> (
    None
):
    record = {
        "currency": "INR",
        "variants": [
            {"size": "S", "currency": "USD", "price": "10"},
            {"size": "M", "currency": "EUR", "price": "12"},
        ],
    }

    backfill._enforce_variant_currency_context(record)

    assert record["variants"] == [
        {"size": "S", "currency": "USD", "price": "10"},
        {"size": "M", "currency": "EUR", "price": "12"},
    ]
    assert record["variant_count"] == 2
    assert len(record["variants_currency_mismatch"]) == 2


@pytest.mark.unit
def test_hydrate_variant_size_from_precompiled_sku_suffix_pattern(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        hydration,
        "variant_sku_size_suffix_patterns",
        (hydration.re.compile(r"-(?P<size>xs|xl)$", hydration.re.I),),
    )
    record = {
        "variants": [
            {"sku": "WIDGET-XS"},
            {"sku": "WIDGET-XL"},
        ],
    }

    hydration._hydrate_variant_axes(record)

    assert [variant["size"] for variant in record["variants"]] == ["XS", "XL"]


@pytest.mark.unit
def test_record_url_suffix_after_title_rejects_non_color_suffix_tokens() -> None:
    """SKU codes, product IDs, and structural tokens must not become color values.

    Regression: phase-eight URLs like
    ``/product/lucinda-spot-midi-dress-10015500806.html`` were producing
    ``"10015500806 Html"`` as the inferred shared variant color. URL suffix
    tokens that are pure digits/``html`` get filtered, and any single
    alphanumeric token with an embedded digit is treated as a SKU/style code.
    """
    # Numeric product id + .html suffix (Phase Eight pattern).
    assert (
        hydration._record_url_suffix_after_title(
            {
                "title": "Lucinda Spot Midi Dress",
                "url": "https://www.phase-eight.com/product/lucinda-spot-midi-dress-10015500806.html",
            }
        )
        == ""
    )
    # SKU-style alphanumeric trailing token (savannahs/Pavlova pattern).
    assert (
        hydration._record_url_suffix_after_title(
            {
                "title": "Pavlova 100 Lace Up Blush Satin Boots",
                "url": "https://savannahs.com/products/pavlova-100-lace-up-blush-satin-boots-cl28517s",
            }
        )
        == ""
    )
    # Genuine alphabetic color slug is still preserved (Allbirds Tuke River).
    assert (
        hydration._record_url_suffix_after_title(
            {
                "title": "Men's Wool Runner",
                "url": "https://www.allbirds.com/products/mens-wool-runners-tuke-river",
            }
        )
        == "Tuke River"
    )


@pytest.mark.unit
def test_infer_shared_variant_color_skips_when_url_suffix_is_not_a_color() -> None:
    """End-to-end: variants without color stay clean when URL suffix is a code."""
    record = {
        "title": "Lucinda Spot Midi Dress",
        "url": "https://www.phase-eight.com/product/lucinda-spot-midi-dress-10015500806.html",
        "variants": [
            {"size": "UK 06"},
            {"size": "UK 08"},
            {"size": "UK 10"},
        ],
    }

    hydration._hydrate_variant_axes(record)

    for variant in record["variants"]:
        assert "color" not in variant or not variant["color"]


@pytest.mark.unit
def test_sanitize_variant_axes_normalizes_mixed_case_axis_keys() -> None:
    record = {
        "variants": [
            {"Size": "US 8", "Color": "Black", "sku": "A"},
            {"Size": "US 9", "Color": "Black", "sku": "B"},
        ],
    }

    sanitization._sanitize_variant_axes(record)

    assert record["variants"] == [
        {"sku": "A", "size": "US 8", "color": "Black"},
        {"sku": "B", "size": "US 9", "color": "Black"},
    ]


@pytest.mark.unit
def test_normalize_variant_record_keeps_independent_color_rows_without_selected_parent_color() -> (
    None
):
    record = {
        "title": "Canvas Sneaker",
        "variants": [
            {"color": "Black"},
            {"color": "White"},
            {"size": "US 8"},
            {"size": "US 9"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"color": "Black"},
        {"color": "White"},
        {"size": "US 8"},
        {"size": "US 9"},
    ]


@pytest.mark.unit
def test_normalize_variant_record_drops_foreign_product_titles_misfiled_as_colors() -> (
    None
):
    record = {
        "title": "40th Anniversary Graphic Womens Short Sleeve Shirt",
        "variants": [
            {"color": "Black/Red"},
            {"color": "Flight Muay Thai Mens Shorts (Black/Sail/University Red)"},
            {"color": 'Brooklyn Graphic 9" Mens Shorts (Black/Gray)'},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [{"color": "Black/Red"}]


@pytest.mark.unit
def test_normalize_variant_record_prunes_global_axes_and_collapses_permutations() -> (
    None
):
    variants = []
    for size in ("8 US", "9 US"):
        for site in ("Kith.com", "Kith.eu"):
            for currency in ("AL / L", "AD / EUR"):
                variants.append(
                    {
                        "price": "282",
                        "currency": "USD",
                        "option_values": {
                            "size": size,
                            "select_site": site,
                            "select_currency": currency,
                        },
                    }
                )
    record = {
        "variant_axes": {
            "size": ["8 US", "9 US"],
            "select_site": ["Kith.com", "Kith.eu"],
            "select_currency": ["AL / L", "AD / EUR"],
        },
        "variants": variants,
    }

    normalize_variant_record(record)

    assert record["variant_count"] == 2


@pytest.mark.unit
def test_normalize_variant_record_strips_currently_unavailable_suffixes() -> None:
    record = {
        "variant_axes": {"size": ["12.5 is currently unavailable.", "13"]},
        "variants": [
            {
                "size": "12.5 is currently unavailable.",
                "availability": "out_of_stock",
                "option_values": {"size": "12.5 is currently unavailable."},
            },
            {
                "size": "13",
                "option_values": {"size": "13"},
            },
        ],
    }

    normalize_variant_record(record)

    assert record["variants"][0]["size"] == "12.5"


@pytest.mark.unit
def test_normalize_variant_record_preserves_identity_less_variants_and_drops_selected_variant() -> (
    None
):
    record = {
        "selected_variant": {
            "title": "Selected from adapter",
            "option_values": {"size": "Large"},
        },
        "variants": [
            {"sku": "sku-1", "option_values": {"size": "Large"}},
            {"sku": "sku-2", "option_values": {"size": "XL"}},
        ],
    }

    normalize_variant_record(record)

    assert "selected_variant" not in record
    assert record["variant_count"] == 2
    assert len(record["variants"]) == 2
    assert any(
        variant.get("sku") == "sku-1" and variant.get("size") == "Large"
        for variant in record["variants"]
    )
    assert any(
        variant.get("sku") == "sku-2" and variant.get("size") == "XL"
        for variant in record["variants"]
    )


@pytest.mark.unit
def test_normalize_variant_record_merges_semantic_duplicate_rows_and_size_aliases() -> (
    None
):
    record = {
        "variant_axes": {"size": ["3", "4", "8", "8 US"]},
        "variants": [
            {
                "sku": "13875993",
                "variant_id": "45140428423360",
                "size": "3",
                "price": "284.00",
                "currency": "USD",
                "availability": "out_of_stock",
                "option_values": {"size": "3"},
            },
            {
                "sku": "13875994",
                "variant_id": "45140428456128",
                "size": "4",
                "price": "284.00",
                "currency": "USD",
                "availability": "out_of_stock",
                "option_values": {"size": "4"},
            },
            {
                "size": "3",
                "price": "284.00",
                "currency": "USD",
                "availability": "in_stock",
                "option_values": {"size": "3"},
            },
            {
                "size": "4",
                "price": "284.00",
                "currency": "USD",
                "availability": "in_stock",
                "option_values": {"size": "4"},
            },
            {
                "sku": "13876003",
                "variant_id": "45140428619904",
                "size": "8",
                "price": "284.00",
                "currency": "USD",
                "availability": "out_of_stock",
                "option_values": {"size": "8"},
            },
            {
                "size": "8 US",
                "price": "284.00",
                "currency": "USD",
                "availability": "in_stock",
                "option_values": {"size": "8 US"},
            },
        ],
        "selected_variant": {
            "size": "4",
            "price": "284.00",
            "currency": "USD",
            "availability": "in_stock",
            "option_values": {"size": "4"},
        },
    }

    normalize_variant_record(record)

    assert record["variant_count"] == 3


@pytest.mark.unit
def test_detail_record_quality_repairs_invalid_original_prices_and_selected_variant_availability() -> (
    None
):
    record = {
        "sku": "M20324",
        "url": "https://www.adidas.com/us/stan-smith-shoes/M20324.html",
        "size": "4",
        "price": "100.00",
        "currency": "USD",
        "availability": "out_of_stock",
        "original_price": "1.00",
        "title": "Stan Smith Shoes",
        "variants": [
            {
                "size": "4",
                "price": "100.00",
                "currency": "USD",
                "availability": "out_of_stock",
                "option_values": {"size": "4"},
                "original_price": "1.00",
            },
            {
                "size": "4.5",
                "price": "100.00",
                "currency": "USD",
                "availability": "out_of_stock",
                "option_values": {"size": "4.5"},
                "original_price": "1.00",
            },
        ],
        "selected_variant": {
            "sku": "M20324",
            "size": "4",
            "price": "100.00",
            "currency": "USD",
            "availability": "in_stock",
            "option_values": {"size": "4"},
            "original_price": "1.00",
        },
    }

    normalize_variant_record(record)
    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url="https://www.adidas.com/us/stan-smith-shoes/M20324.html",
    )

    assert record["original_price"] == "100.00"
    assert all("original_price" not in variant for variant in record["variants"])


@pytest.mark.unit
def test_detail_record_quality_does_not_downgrade_in_stock_parent_from_partial_variants() -> (
    None
):
    record = {
        "title": "Example Shoe",
        "price": "100.00",
        "currency": "USD",
        "availability": "in_stock",
        "variants": [
            {
                "size": "8",
                "availability": "out_of_stock",
                "option_values": {"size": "8"},
            },
            {
                "size": "9",
                "availability": "unknown",
                "option_values": {"size": "9"},
            },
        ],
    }

    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url="https://example.com/products/example-shoe",
    )

    assert record["availability"] == "in_stock"


@pytest.mark.unit
def test_reconcile_variant_derived_parent_fields_clears_stale_values_without_variants() -> (
    None
):
    record = {
        "image_url": "https://cdn.example.com/variant.jpg",
        "availability": "out_of_stock",
    }

    _reconcile_variant_derived_parent_fields(
        record,
        variant_parent_image="https://cdn.example.com/variant.jpg",
        variant_parent_availability="out_of_stock",
    )

    assert "image_url" not in record
    assert "availability" not in record


@pytest.mark.unit
def test_detail_record_quality_does_not_overwrite_structured_color_from_description() -> (
    None
):
    record = {
        "title": "Example Jacket",
        "color": "Black",
        "description": "Made with 'Red' leather upper.",
        "_field_sources": {"color": ["structured"]},
    }

    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url="https://example.com/products/example-jacket",
    )

    assert record["color"] == "Black"
    assert record["_field_sources"]["color"] == ["structured"]


@pytest.mark.unit
def test_detail_record_quality_does_not_assign_numeric_prefix_brand_without_url_match() -> (
    None
):
    record = {"title": "123 Example Jacket"}

    repair_ecommerce_detail_record_quality(
        record,
        html="<html></html>",
        page_url="https://example.com/products/example-jacket",
    )

    assert "brand" not in record


@pytest.mark.unit
def test_field_coerce_ignores_non_json_structured_category_text() -> None:
    assert (
        coerce_field_value(
            "category",
            "{not json but user visible category text",
            "https://example.com/products/example",
        )
        == "{not json but user visible category text"
    )


@pytest.mark.unit
def test_sanitize_variant_row_preserves_relative_image_paths() -> None:
    variant = {"size": "8", "image_url": "/images/example-shoe-8.jpg"}

    assert sanitize_variant_row(
        variant,
        identity_url="https://example.com/products/example-shoe",
        title_hint="Example Shoe",
    )
    assert variant["image_url"] == "/images/example-shoe-8.jpg"


@pytest.mark.unit
def test_normalize_variant_record_does_not_invent_color_size_cross_product() -> None:
    record = {
        "color": "Cloud White / Core White / Green",
        "variants": [
            {
                "size": "4",
                "sku": "M20324_530",
                "availability": "in_stock",
                "option_values": {"size": "4"},
            },
            {
                "size": "4.5",
                "sku": "M20324_540",
                "availability": "out_of_stock",
                "option_values": {"size": "4.5"},
            },
            {
                "color": "Cloud White / Core White / Green",
                "url": "https://www.adidas.com/us/stan-smith-shoes/M20324.html",
                "option_values": {"color": "Cloud White / Core White / Green"},
            },
            {
                "color": "Cloud White / Core Black / Green",
                "url": "https://www.adidas.com/us/stan-smith-shoes/M20325.html",
                "option_values": {"color": "Cloud White / Core Black / Green"},
            },
        ],
    }

    normalize_variant_record(record)

    assert all(
        not (variant.get("size") and variant.get("color"))
        for variant in record["variants"]
    )
    assert record.get("variant_count") == 4
    sizes = {
        variant.get("size") for variant in record["variants"] if variant.get("size")
    }
    assert sizes == {"4", "4.5"}
    color_only_values = {
        variant.get("color")
        for variant in record["variants"]
        if variant.get("color") and not variant.get("size")
    }
    assert color_only_values == {
        "Cloud White / Core White / Green",
        "Cloud White / Core Black / Green",
    }


@pytest.mark.unit
def test_normalize_variant_record_drops_numeric_shade_code_size_duplicate() -> None:
    record = {
        "title": "Colorful Eyeshadow",
        "variants": [
            {
                "sku": "2820108",
                "size": "209",
                "color": "209 Mocha Latte",
                "image_url": "https://www.sephora.com/productimages/sku/s2820108-main-hero.jpg",
            },
            {
                "sku": "2819449",
                "size": "601",
                "color": "601 Silver Storm",
                "image_url": "https://www.sephora.com/productimages/sku/s2819449-main-hero.jpg",
            },
        ],
    }

    normalize_variant_record(record)

    assert record["variant_count"] == 2
    assert [variant.get("color") for variant in record["variants"]] == [
        "209 Mocha Latte",
        "601 Silver Storm",
    ]
    assert all("size" not in variant for variant in record["variants"])


@pytest.mark.unit
def test_normalize_variant_record_keeps_parent_scalar_size_without_variants() -> None:
    record = {
        "title": "Colorful Eyeshadow",
        "size": "0.035 oz / 0.99 g",
        "color": "209 Mocha Latte - soft mocha brown matte",
    }

    normalize_variant_record(record)

    assert record["size"] == "0.035 oz / 0.99 g"
    assert record["color"] == "209 Mocha Latte - soft mocha brown matte"


@pytest.mark.unit
def test_variant_choice_container_is_overbroad() -> None:
    from app.services.extract.variant_choice_traversal import (
        _variant_choice_container_is_overbroad,
    )

    # A container with both color and size inputs is overbroad
    html = """
    <div class="overbroad-parent">
        <div class="color-section">
            <input type="radio" name="color-option" data-option-name="color" value="Black">
            <input type="radio" name="color-option" data-option-name="color" value="Cognac">
        </div>
        <div class="size-section">
            <input type="radio" name="size-option" data-option-name="size" value="7M">
            <input type="radio" name="size-option" data-option-name="size" value="8M">
        </div>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(class_="overbroad-parent")
    assert _variant_choice_container_is_overbroad(container) is True

    # A container with only one option name/axis is not overbroad
    html_fine = """
    <div class="fine-parent">
        <input type="radio" name="color-option" data-option-name="color" value="Black">
        <input type="radio" name="color-option" data-option-name="color" value="Cognac">
    </div>
    """
    soup_fine = BeautifulSoup(html_fine, "html.parser")
    container_fine = soup_fine.find(class_="fine-parent")
    assert _variant_choice_container_is_overbroad(container_fine) is False
