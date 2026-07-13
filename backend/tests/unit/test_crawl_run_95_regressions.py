"""Distilled regressions for the crawl-run-95 architectural fixes.

Each test reproduces the minimal shape of a defect the audit
(``docs/plans/crawlerai-crawl-run-95-architectural-fixes.md``) found in real
crawl artifacts, so the fixes cannot silently regress. Fixtures are synthetic —
the audited HTML lives in the gitignored ``backend/artifacts`` tree and is not
committed.
"""

from __future__ import annotations

import json

import pytest

from app.extraction import Surface, extract
from app.extraction.contracts import CommerceDetailProjection, PublicationEntry
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.result_building import projection_field_states

from tests.unit.extraction_pipeline_test_support import _extract

pytestmark = pytest.mark.unit


def _request(*requested_fields: str):
    return fixture_request_from_inputs(
        Surface("ecommerce_detail"),
        "<html><body><main><h1>x</h1></main></body></html>",
        "https://shop.test/p",
        max_records=1,
        requested_fields=requested_fields or ("title", "price", "currency"),
    )


def test_variant_prices_do_not_publish_parent_commercial_fields() -> None:
    """Slice 1: results 68/90 — published variant offers must not mark the
    public parent (``record.*``) field as published.

    The defect was that ``projection_field_states`` flattened ``variant[...].price``
    into the ``price`` group, so a published variant price reported the page-level
    ``price`` as ``captured_published`` even though ``record.price`` was absent.
    After the fix variant facts are summarized under ``variants.*`` and never
    inflate the parent field's state.
    """
    projection = CommerceDetailProjection(
        record_entity_id="product:1",
        variant_entity_ids=("offer:v1", "offer:v2"),
        entries=(
            PublicationEntry(
                path="record.title",
                entity_id="product:1",
                value="Norvan Trail Shoe",
                selected_fact_id="sel:title",
                disposition="publish",
            ),
            PublicationEntry(
                path="variant[offer:v1].price",
                entity_id="offer:v1",
                value="150.00",
                selected_fact_id="sel:p1",
                disposition="publish",
            ),
            PublicationEntry(
                path="variant[offer:v1].currency",
                entity_id="offer:v1",
                value="USD",
                selected_fact_id="sel:c1",
                disposition="publish",
            ),
            PublicationEntry(
                path="variant[offer:v2].price",
                entity_id="offer:v2",
                value="170.00",
                selected_fact_id="sel:p2",
                disposition="publish",
            ),
            PublicationEntry(
                path="variant[offer:v2].availability",
                entity_id="offer:v2",
                value="InStock",
                selected_fact_id="sel:a2",
                disposition="publish",
            ),
        ),
    )

    states = {
        state.field: state.state
        for state in projection_field_states(
            projection,
            (),
            (),
            _request("title", "price", "currency", "availability"),
            (),
        )
    }

    # Parent commercial fields have no published parent entry -> must be absent.
    assert states["price"] == "not_present_in_captured_sources"
    assert states["currency"] == "not_present_in_captured_sources"
    assert states["availability"] == "not_present_in_captured_sources"

    # The variant facts are summarized separately and remain visible.
    assert states["variants.price"] == "captured_published"
    assert states["variants.currency"] == "captured_published"
    assert states["variants.availability"] == "captured_published"


def test_published_parent_price_still_reports_captured_published() -> None:
    """A genuine ``record.price`` publish entry must still surface as published —
    the Slice 1 split must not suppress real parent facts."""
    projection = CommerceDetailProjection(
        record_entity_id="product:1",
        entries=(
            PublicationEntry(
                path="record.price",
                entity_id="offer:1",
                value="150.00",
                selected_fact_id="sel:p",
                disposition="publish",
            ),
        ),
    )

    states = {
        state.field: state.state
        for state in projection_field_states(projection, (), (), _request("price"), ())
    }

    assert states["price"] == "captured_published"


# --- Slice 2: generic variant-control discovery ---------------------------


_CONTROL_ROLE_HTML = """
<html><body><main>
<h1>Trail Shoe</h1>
<form class="product-form">
  <select name="size" id="product-size"><option value="">Choose</option>
    <option value="9">9</option><option value="10">10</option><option value="11">11</option></select>
  <select name="color" class="product-option-color"><option>Black</option><option>Red</option></select>
</form>
<select id="product-page-sort-select" aria-label="Sort by">
  <option>Featured</option><option>Price: Low to High</option><option>Newest</option></select>
<select name="country_code" id="CountryList">
  <option>United States</option><option>Canada</option><option>Mexico</option></select>
<select name="qty" id="qty-select"><option>1</option><option>2</option><option>3</option></select>
<select id="reviews-filter" data-testid="reviews-filter-dropdown">
  <option>Most recent</option><option>Highest rated</option></select>
</main></body></html>
"""


def _dom_option_values(html: str, page_url: str) -> dict[str, set[str]]:
    from app.extraction.collectors.dom import DomCollector

    request = fixture_request_from_inputs(Surface.ECOMMERCE_DETAIL, html, page_url)
    values: dict[str, set[str]] = {}
    for row in DomCollector().collect(request.capture, request.artifact_reader):
        if row.fact_type.startswith("option.") and row.collector_id == "dom":
            values.setdefault(row.fact_type, set()).add(row.value)
    return values


def test_non_product_select_controls_create_no_option_axes() -> None:
    """Slice 2: sort, country, quantity and review-filter selects must never
    become size/color axes; genuine size/color selects still do (results
    10/17/21/58/70/79/95 lost axes; 11/12/20/25/30/75 kept them)."""
    values = _dom_option_values(_CONTROL_ROLE_HTML, "https://shop.test/p")

    # Legitimate product options survive.
    assert {"9", "10", "11"} <= values.get("option.size", set())
    assert values.get("option.color", set()) == {"Black", "Red"}

    # Control-select values must not have leaked into any option axis.
    leaked = set().union(*values.values()) if values else set()
    for control_value in (
        "Featured",
        "Price: Low to High",
        "United States",
        "Canada",
        "Most recent",
        "Highest rated",
        "1",
        "2",
        "3",
    ):
        assert control_value not in leaked, control_value


def test_control_role_classifier_rejects_and_admits_generically() -> None:
    """The role classifier is site-agnostic: reject-tokens win, product-option
    tokens admit, bare selects stay out."""
    from app.core.config.extraction_rules import (
        control_signal_tokens,
        has_product_option_signal,
        is_rejected_control,
    )

    sort = control_signal_tokens(["oke-sortSelect--reviews", "Sort"])
    assert is_rejected_control(sort)

    country = control_signal_tokens(["country_code", "CountryList"])
    assert is_rejected_control(country)

    size = control_signal_tokens(["size", "product-size"])
    assert not is_rejected_control(size)
    assert has_product_option_signal(size, axis="size")

    colour = control_signal_tokens(["product-option-colour", "Colour"])
    assert not is_rejected_control(colour)
    assert has_product_option_signal(colour, axis="color")

    # Bare/opaque select: no reject signal, but also no product-option signal.
    opaque = control_signal_tokens(["kib-field-29722"])
    assert not is_rejected_control(opaque)
    assert not has_product_option_signal(opaque, axis="")


def test_colour_and_wrapped_select_controls_create_color_axis() -> None:
    html = """
        <html><body><main>
          <h1>Trail Shoe</h1>
          <form class="product-form">
            <label>Colour
              <select name="product-colour">
                <option>Black</option><option>Bone</option>
              </select>
            </label>
            <select data-option-name="Colour"><option>Red</option></select>
            <button data-option-name="colour">Blue</button>
          </form>
        </main></body></html>
        """

    assert _dom_option_values(html, "https://shop.test/p").get(
        "option.color", set()
    ) == {
        "Black",
        "Bone",
        "Red",
        "Blue",
    }


def test_select_label_lookup_ignores_css_special_id_without_crashing() -> None:
    html = """
        <html><body><main>
          <h1>Trail Shoe</h1>
          <label for='product"]colour'>Colour</label>
          <select id='product"]colour'><option>Black</option></select>
        </main></body></html>
        """

    assert _dom_option_values(html, "https://shop.test/p").get(
        "option.color", set()
    ) == {"Black"}


# --- Slice 3: child ownership + commercial projection policy ---------------


def _variant_group_html(*, variants: str, group_offer: str = "") -> str:
    group_offer_block = f'"offers": {group_offer},' if group_offer else ""
    return f"""
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Norvan LD Shoe",
      "url": "https://shop.test/products/norvan",
      "sku": "NORVAN",
      {group_offer_block}
      "hasVariant": [{variants}]
    }}
    </script>
    """


def _variant_json(
    sku: str, size: str, *, price: str = "", availability: str = ""
) -> str:
    offer_fields = ['"priceCurrency": "CAD"']
    if price:
        offer_fields.append(f'"price": "{price}"')
    if availability:
        offer_fields.append(f'"availability": "https://schema.org/{availability}"')
    # Every embedded offer carries the *shared* product URL as its only offer
    # identity — the exact shape that used to collapse all variants into one.
    offer_fields.append('"url": "https://shop.test/products/norvan"')
    return (
        '{"@type": "Product", "sku": "%s", "size": "%s", '
        '"offers": {"@type": "Offer", %s}}' % (sku, size, ", ".join(offer_fields))
    )


def test_embedded_variant_offers_bind_per_variant_not_collapsed() -> None:
    """Slice 3 (results 68/90/23): each ``hasVariant[N].offers`` node shares the
    product URL as its offer identity. They must each bind to their own variant
    (so every variant keeps its price) instead of collapsing into a single offer
    bound to one variant, which left the parent commercial fields blank."""
    variants = ", ".join(
        _variant_json(f"SKU-{i}", str(size), price="260.00", availability="InStock")
        for i, size in enumerate(("7", "8", "9", "10"))
    )
    result = _extract(
        "ecommerce_detail",
        _variant_group_html(variants=variants),
        "https://shop.test/products/norvan",
        requested_fields=("price", "currency", "availability", "variants"),
    )
    record = result.records[0]
    variant_rows = record.get("variants") or ()
    assert len(variant_rows) == 4
    assert all(row.get("price") == "260.00" for row in variant_rows)

    # Complete, uniform catalog -> parent aggregates the shared price/availability.
    assert record.get("price") == "260.00"
    assert record.get("currency") == "CAD"
    assert record.get("availability") == "in_stock"


def test_parent_availability_rolls_up_mixed_variant_states() -> None:
    """Slice 3: a complete catalog whose variants mix ``in_stock`` /
    ``out_of_stock`` / ``limited_stock`` must publish a purchasable parent state
    (``in_stock`` wins) rather than dropping availability because a non-binary
    state (``limited_stock``, result 68) was present."""
    variants = ", ".join(
        (
            _variant_json("SKU-A", "7", price="260.00", availability="InStock"),
            _variant_json("SKU-B", "8", price="260.00", availability="OutOfStock"),
            _variant_json(
                "SKU-C", "9", price="260.00", availability="LimitedAvailability"
            ),
        )
    )
    result = _extract(
        "ecommerce_detail",
        _variant_group_html(variants=variants),
        "https://shop.test/products/norvan",
        requested_fields=("price", "availability", "variants"),
    )
    record = result.records[0]
    assert record.get("availability") == "in_stock"
    assert (
        record["_lineage"]["availability"]["rule_id"]
        == "variant_availability_aggregate"
    )


def test_all_out_of_stock_variants_roll_up_to_out_of_stock() -> None:
    """Rollup precedence only surfaces ``out_of_stock`` when *no* variant is
    buyable — it must not mask a genuinely sold-out catalog as in stock."""
    variants = ", ".join(
        (
            _variant_json("SKU-A", "7", price="260.00", availability="OutOfStock"),
            _variant_json("SKU-B", "8", price="260.00", availability="OutOfStock"),
        )
    )
    result = _extract(
        "ecommerce_detail",
        _variant_group_html(variants=variants),
        "https://shop.test/products/norvan",
        requested_fields=("availability", "variants"),
    )
    assert result.records[0].get("availability") == "out_of_stock"


def test_partial_variant_pricing_publishes_bounded_range_not_a_fake_aggregate() -> None:
    """Slice 3 policy: when only a subset of variants are priced, publish a
    documented bounded ``price_min``/``price_max`` range — never a single value
    pretending the partial coverage is a complete aggregate."""
    variants = ", ".join(
        (
            _variant_json("SKU-A", "7", price="150.00"),
            _variant_json("SKU-B", "8", price="250.00"),
            _variant_json("SKU-C", "9"),  # unpriced -> catalog is incomplete
        )
    )
    result = _extract(
        "ecommerce_detail",
        _variant_group_html(variants=variants),
        "https://shop.test/products/norvan",
        requested_fields=("price", "variants"),
    )
    record = result.records[0]
    # No default variant identified -> no single parent display price fabricated.
    assert record.get("price") is None
    # But the verified priced subset is surfaced as an explicit bounded range.
    assert record.get("price_min") == "150.00"
    assert record.get("price_max") == "250.00"
    assert record["_lineage"]["price_min"]["rule_id"] == "bounded_variant_price_range"


# --- Slice 4: source-aware price-unit consensus ----------------------------


def _next_data_price_html(*, price: str) -> str:
    """A Next.js ``__NEXT_DATA__`` productSummary whose price carries excess
    minor-unit precision (``128.000000``), corroborated by a JSON-LD offer at
    the true magnitude — the exact shape of audit result 81."""
    next_data = (
        '{"props": {"pageProps": {"dehydratedState": {"queries": [{"state": '
        '{"data": {"productSummary": {"name": "Define Jacket", '
        f'"price": "{price}", "currency": "USD", "sku": "PROD-1", '
        '"url": "https://shop.test/p/define/_/prod1"}}}}}]}}}}'
    )
    return f"""
    <html><head><title>Define Jacket</title>
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Define Jacket",
      "sku": "PROD-1",
      "url": "https://shop.test/p/define/_/prod1",
      "offers": {{"@type": "Offer", "price": "128.00", "priceCurrency": "USD",
        "url": "https://shop.test/p/define/_/prod1"}}
    }}
    </script>
    </head>
    <body><main><h1>Define Jacket</h1><span class="price">$128 USD</span></main>
    <script id="__NEXT_DATA__" type="application/json">{next_data}</script>
    </body></html>
    """


def test_over_precise_embedded_price_is_not_multiplied_by_scale() -> None:
    """Slice 4 (result 81): a JS-state price of ``128.000000`` must publish as
    ``128.00`` — never ``128000000`` from deleting the decimal point as if it
    were a thousands separator. This was the only confirmed data-corruption P0."""
    result = _extract(
        "ecommerce_detail",
        _next_data_price_html(price="128.000000"),
        "https://shop.test/p/define/_/prod1",
        requested_fields=("price", "currency"),
    )
    record = result.records[0]
    assert record.get("price") == "128.00"
    assert record.get("currency") == "USD"
    # No raw million-scale value survives anywhere in the resolved facts.
    price_values = {
        str(fact.value)
        for fact in result.derived_facts
        if fact.fact_type == "offer.price"
    } | {str(row.value) for row in result.evidence if row.fact_type == "offer.price"}
    assert not any("128000000" in value for value in price_values)


# --- Slice 5: narrow content rejection -------------------------------------


def _compacted_description_html(*, prose: str, suffix: str) -> str:
    """A JSON-LD product whose description is valid prose followed by a
    separator-less, run-together feature list — the shape of audit result 1,
    where ``...look.\xa0Soft Rock100% Cotton14ozScreen printed`` used to
    invalidate the entire description via ``description_missing_separator``."""
    description = f"{prose} {suffix}"
    return f"""
    <html><head><title>Soft Rock Crewneck</title>
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Soft Rock Crewneck",
      "sku": "SKU-1",
      "url": "https://shop.test/products/soft-rock-crewneck",
      "description": {json.dumps(description)},
      "offers": {{"@type": "Offer", "price": "80.00", "priceCurrency": "USD",
        "url": "https://shop.test/products/soft-rock-crewneck"}}
    }}
    </script>
    </head>
    <body><main><h1>Soft Rock Crewneck</h1></main></body></html>
    """


def test_compacted_feature_suffix_keeps_grounded_prose_head() -> None:
    """Slice 5 (result 1): a description that ends in a compacted, separator-less
    feature list must still publish its grounded prose head instead of being
    dropped whole. The run-together tail is trimmed at the last sentence."""
    prose = (
        "Arriving as part of its Spring collection, the Soft Rock Crewneck "
        "features an eye-catching logo on the chest to round off the "
        "minimalistic look."
    )
    result = _extract(
        "ecommerce_detail",
        _compacted_description_html(
            prose=prose, suffix="Soft Rock100% Cotton14ozScreen printed logo"
        ),
        "https://shop.test/products/soft-rock-crewneck",
        requested_fields=("description",),
    )
    description = result.records[0].get("description")
    assert description is not None
    assert description.endswith("minimalistic look.")
    assert "14oz" not in description
    assert "100% Cotton" not in description


def _square_crop_image_html(*, image_url: str) -> str:
    """A JSON-LD product whose primary image carries a ``_1x1_`` square-crop
    marker and a real ``?width=1440&height=1440`` render — the shape of audit
    result 89, where the ``1x1`` token wrongly rejected a 1440px image."""
    payload = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Retro Matte Lipstick",
            "sku": "M25001",
            "url": "https://shop.test/product/retro-matte",
            "image": image_url,
            "offers": {
                "@type": "Offer",
                "price": "24.00",
                "priceCurrency": "USD",
                "url": "https://shop.test/product/retro-matte",
            },
        }
    )
    return f"""
    <html><head><title>Retro Matte Lipstick</title>
    <script type="application/ld+json">{payload}</script>
    </head>
    <body><main><h1>Retro Matte Lipstick</h1></main></body></html>
    """


def test_square_crop_marker_is_not_treated_as_tracking_pixel() -> None:
    """Slice 5 (result 89): an ``_1x1_`` aspect-ratio crop paired with a real
    1440px render is a product image, not a 1×1 tracking pixel, and must
    publish instead of being rejected by a blanket ``1x1`` token match."""
    image_url = (
        "https://sdcdn.io/mac/us/mac_sku_M25001_1x1_0.png?width=1440&height=1440"
    )
    result = _extract(
        "ecommerce_detail",
        _square_crop_image_html(image_url=image_url),
        "https://shop.test/product/retro-matte",
        requested_fields=("image_url",),
    )
    assert result.records[0].get("image_url") == image_url


def test_genuine_1x1_tracking_pixel_is_still_rejected() -> None:
    """The narrowed rule must keep rejecting a real 1×1 pixel: a standalone
    ``1x1`` dimension with no larger declared size anywhere in the URL."""
    result = _extract(
        "ecommerce_detail",
        _square_crop_image_html(image_url="https://track.test/beacon/1x1.gif"),
        "https://shop.test/product/retro-matte",
        requested_fields=("image_url",),
    )
    assert result.records[0].get("image_url") is None


def test_asset_selection_and_publication_share_high_resolution_lineage() -> None:
    """Slice 5 (result 13): scalar selection and asset publication must name
    the same evidence row. A higher-confidence thumbnail cannot own lineage
    while a larger transform is the URL actually published."""
    page_url = "https://shop.test/products/retro-shoe"
    low_res = "https://cdn.test/images/retro-shoe.jpg?sw=71"
    high_res = "https://cdn.test/images/retro-shoe.jpg?sw=406"
    html = f"""
    <html><head>
      <meta property="og:title" content="Retro Shoe">
      <meta property="og:url" content="{page_url}">
      <meta property="og:image" content="{high_res}">
    </head><body>
      <main itemscope itemtype="https://schema.org/Product">
        <h1 itemprop="name">Retro Shoe</h1>
        <img itemprop="image" src="{low_res}">
      </main>
    </body></html>
    """

    result = _extract(
        "ecommerce_detail",
        html,
        page_url,
        requested_fields=("image_url",),
    )

    assert result.records[0].get("image_url") == high_res
    lineage = result.records[0]["_lineage"]["image_url"]
    assert lineage["binding_id"] == "field.image_url"
    assert lineage["source_path"]


def test_url_confirmed_product_keeps_direct_brand_despite_title_slug_mismatch() -> None:
    """Slice 5 (result 59): a model title can differ lexically from its URL
    slug. The product's canonical URL still confirms ownership of its direct
    structured brand evidence."""
    page_url = "https://shop.test/cameras/products/ilce-9m3?sku=ilce-9m3-in5"
    payload = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ProductGroup",
            "name": "α9 III with global shutter",
            "productGroupID": "ilce-9m3",
            "brand": {"@type": "Brand", "name": "Optix"},
            "url": "https://shop.test/cameras/products/ilce-9m3",
        }
    )
    result = _extract(
        "ecommerce_detail",
        f'<html><head><script type="application/ld+json">{payload}</script>'
        "</head><body><h1>ILCE-9M3</h1></body></html>",
        page_url,
        requested_fields=("brand",),
    )

    assert result.records[0].get("brand") == "Optix"


def test_top_level_jsonld_brand_survives_matching_child_offer_urls() -> None:
    """Slice 5 (result 79): matching offer URLs select their top-level Product
    ancestor. They must not scope out the ancestor's direct brand."""
    page_url = "https://shop.test/product.do?pid=887835012"
    payload = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Linen-Cotton Relaxed Taper Pants",
            "brand": {"@type": "Brand", "name": "Clothier"},
            "offers": [
                {
                    "@type": "Offer",
                    "price": "47.00",
                    "priceCurrency": "USD",
                    "sku": "8878350120002",
                    "url": "https://shop.test/product.do?pid=8878350120002",
                }
            ],
        }
    )
    result = _extract(
        "ecommerce_detail",
        f'<html><head><script type="application/ld+json">{payload}</script>'
        "</head><body><h1>Linen-Cotton Relaxed Taper Pants</h1></body></html>",
        page_url,
        requested_fields=("brand",),
    )

    assert result.records[0].get("brand") == "Clothier"


def test_standalone_jsonld_variant_keeps_direct_product_brand() -> None:
    """Slice 5 (result 92): product-level brand on a standalone Product with
    ``isVariantOf`` remains attached to the selected parent product."""
    page_url = "https://shop.test/products/soleil-pant/ME988?fit=Classic"
    payload = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Soleil pant in linen",
            "brand": "Atelier",
            "sku": "CI939-BR8825",
            "url": (
                "https://shop.test/products/soleil-pant/ME988"
                "?colorProductCode=CI939&fit=Classic"
            ),
            "isVariantOf": {
                "@type": "ProductGroup",
                "name": "Soleil pant in linen",
                "productGroupID": "ME988",
                "url": page_url,
                "sku": "CI939-BR8825",
            },
        }
    )
    result = _extract(
        "ecommerce_detail",
        f'<html><head><script type="application/ld+json">{payload}</script>'
        "</head><body><h1>Soleil pant in linen</h1></body></html>",
        page_url,
        requested_fields=("brand",),
    )

    assert result.records[0].get("brand") == "Atelier"


def test_routine_partial_without_requested_high_value_field_does_not_route_review() -> (
    None
):
    """Slice 6: missing optional/default fields may be honest partial output,
    not automatic operator work."""
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head><title>Pink Shorts</title></head>
          <body><h1>Pink Shorts</h1></body>
        </html>
        """,
        "https://shop.test/product/pink-shorts/123",
    )

    assert result.verdict == "partial"
    assert result.diagnostics.review_required is False
    assert result.diagnostics.trust_state == "partial"


def test_requested_high_value_field_missing_after_capture_routes_review() -> None:
    """Slice 6: requested high-value gaps route after enabled stages are spent."""
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        """
        <html>
          <head><title>Pink Shorts</title></head>
          <body><h1>Pink Shorts</h1></body>
        </html>
        """,
        "https://shop.test/product/pink-shorts/123",
        requested_fields=("price",),
    )
    request = request.model_copy(
        update={
            "capture": request.capture.model_copy(update={"browser_attempted": True})
        }
    )

    result = extract(request)

    assert result.verdict == "partial"
    assert result.retry_request is None
    assert result.diagnostics.review_required is True
    assert result.diagnostics.trust_state == "needs_review"


def test_semantic_shell_uses_terminal_capture_outcome_after_browser_spent() -> None:
    """Slice 6: browser-spent shell output reports one terminal capture outcome
    and routes review instead of looking like clean transport."""
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        """
        <html>
          <head><title>Access denied. We invite you to return at a later time to complete your purchase.</title></head>
          <body><h1>Access denied. We invite you to return at a later time to complete your purchase.</h1></body>
        </html>
        """,
        "https://shop.test/products/bootleg-pants/1AJUPQ",
    )
    request = request.model_copy(
        update={
            "capture": request.capture.model_copy(update={"browser_attempted": True})
        }
    )

    result = extract(request)

    assert result.verdict == "error"
    assert result.transport_outcome == "semantic_shell"
    assert result.data_integrity == "defect"
    assert result.retry_request is not None
    assert result.retry_request.required is False
    assert result.diagnostics.review_required is True
    assert result.diagnostics.trust_state == "needs_review"


def test_http_not_found_uses_terminal_capture_outcome_without_review() -> None:
    """Slice 6: static not-found pages stay terminal rejected output, not
    operator review."""
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        """
        <html>
          <head><title>Pink Shorts</title></head>
          <body><h1>Pink Shorts</h1></body>
        </html>
        """,
        "https://shop.test/product/pink-shorts/123",
    )
    request = request.model_copy(
        update={"capture": request.capture.model_copy(update={"http_status": 404})}
    )

    result = extract(request)

    assert result.verdict == "error"
    assert result.transport_outcome == "not_found"
    assert result.diagnostics.review_required is False
    assert result.diagnostics.trust_state == "rejected"
