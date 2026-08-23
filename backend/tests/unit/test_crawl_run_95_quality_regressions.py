"""test_crawl_run_95_regressions cases split by public behavior."""

from __future__ import annotations

from tests.unit.crawl_run_95_test_support import (
    Surface,
    _compacted_description_html,
    _extract,
    _next_data_price_html,
    _square_crop_image_html,
    extract,
    fixture_request_from_inputs,
    json,
)


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
    evidence_by_id = {row.evidence_id: row for row in result.evidence}
    selected_by_id = {row.selected_fact_id: row for row in result.selected_facts}
    assert tuple(
        evidence_by_id[evidence_id].value for evidence_id in lineage["evidence_ids"]
    ) == (high_res,)
    assert selected_by_id[lineage["selected_fact_id"]].evidence_ids == tuple(
        lineage["evidence_ids"]
    )


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
