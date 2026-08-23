from __future__ import annotations

# ruff: noqa: F403, F405
from .product_intelligence_test_support import *


@pytest.mark.component
def test_product_intelligence_query_uses_mpn_not_source_domain_or_sku() -> None:
    queries = build_search_queries(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "mpn": "04511-2406",
            "sku": "BELK-ONLY-123",
        },
        source_domain_value="belk.com",
    )

    assert queries
    assert queries[0] == 'site:levi.com "04511-2406"'
    assert "site:levi.com" in " ".join(queries)
    assert all("belk.com" not in query for query in queries)
    assert any("levi's" in query for query in queries)
    assert any("04511-2406" in query for query in queries)
    assert any("Men 511 Slim Fit Jeans" in query for query in queries)
    assert all("BELK-ONLY-123" not in query for query in queries)
    assert len(queries) <= 4


@pytest.mark.component
def test_product_intelligence_query_prefers_upc_over_mpn_as_identifier() -> None:
    # When the source product carries a UPC/GTIN, it must be the identifier
    # appended to the brand+title and brand-site queries (strongest match
    # signal), with the MPN/SKU-like token no longer used as the appended id.
    queries = build_search_queries(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "gtin": "0655772019097",
            "mpn": "04511-2406",
            "sku": "BELK-ONLY-123",
        },
        source_domain_value="belk.com",
    )

    assert queries
    # Standalone quoted GTIN stays the first, highest-precision query.
    assert queries[0] == '"0655772019097"'
    # The UPC, not the MPN, is appended to the brand-site and brand+title queries.
    assert 'site:levi.com "0655772019097"' in queries
    assert any(
        query.startswith("levi's Men 511 Slim Fit Jeans") and "0655772019097" in query
        for query in queries
    )
    assert all("04511-2406" not in query for query in queries)
    assert all("BELK-ONLY-123" not in query for query in queries)


@pytest.mark.component
def test_product_intelligence_query_strips_repeated_brand_and_targets_brand_domain() -> (
    None
):
    queries = build_search_queries(
        {
            "brand": "Wrangler\u00ae",
            "title": "Wrangler\u00ae Relaxed Bootcut Jeans",
            "url": "https://www.belk.com/p/wrangler--relaxed-bootcut-jeans-/3200040112342570.html",
        },
        source_domain_value="belk.com",
    )

    assert queries[0] == "site:wrangler.com wrangler Relaxed Bootcut Jeans"
    assert queries[1] == "wrangler Relaxed Bootcut Jeans"
    assert "wrangler wrangler" not in " ".join(queries)


@pytest.mark.component
def test_product_intelligence_query_targets_configured_belk_brand_domains() -> None:
    queries = build_search_queries(
        {
            "brand": "Baggallini",
            "title": "Modern Everywhere Bag",
        },
        source_domain_value="belk.com",
    )

    assert queries[0] == "site:baggallini.com baggallini Modern Everywhere Bag"
    assert all("belk.com" not in query for query in queries)


@pytest.mark.component
def test_product_intelligence_query_keeps_brand_in_all_queries_when_brand_exists() -> (
    None
):
    queries = build_search_queries(
        {
            "brand": "Mamaearth",
            "title": "Vit. C Daily Glow Cream 150g",
            "mpn": "MC150G",
            "sku": "20510856",
        },
        source_domain_value="myntra.com",
    )

    assert queries
    assert any("mamaearth" in query for query in queries)
    assert all("myntra.com" not in query for query in queries)
    assert queries[0] == 'mamaearth Vit. C Daily Glow Cream 150g "MC150G"'
    assert queries[1] == "mamaearth Vit. C Daily Glow Cream 150g"
    assert len(queries) <= 3


@pytest.mark.component
def test_product_intelligence_dtc_score_does_not_promote_short_subset_titles() -> None:
    intelligence = score_candidate(
        source={
            "title": "Samsung Galaxy S24 Ultra 512GB",
            "brand": "Samsung",
        },
        candidate={
            "title": "Samsung Galaxy",
            "brand": "Samsung",
        },
        source_type=SOURCE_TYPE_BRAND_DTC,
    )

    assert intelligence["reasons"]["title_similarity"] < 0.5
    assert intelligence["score"] < 0.8


@pytest.mark.component
def test_product_intelligence_query_prefers_clean_brand_query_before_buy_for_aggregator_sources() -> (
    None
):
    queries = build_search_queries(
        {
            "brand": "Asaya",
            "title": "Even Evermore Cream 50g",
            "mpn": "EEC50G",
            "sku": "31145778",
        },
        source_domain_value="flipkart.com",
    )

    assert queries
    assert queries[0] == 'asaya Even Evermore Cream 50g "EEC50G"'
    assert queries[1] == "asaya Even Evermore Cream 50g"
    assert all("flipkart.com" not in query for query in queries)
    assert len(queries) <= 2


@pytest.mark.component
def test_product_intelligence_query_uses_brandless_fallback_only_when_brand_missing() -> (
    None
):
    queries = build_search_queries(
        {
            "title": "Vit. C Daily Glow Cream 150g",
            "mpn": "MC150G",
            "sku": "20510856",
        },
        source_domain_value="myntra.com",
    )

    assert queries
    assert any("MC150G" in query for query in queries)
    assert all("mamaearth" not in query for query in queries)
    assert queries[0] == '"Vit. C Daily Glow Cream 150g" "MC150G"'
    assert queries[1] == '"Vit. C Daily Glow Cream 150g" buy'
    assert len(queries) == 2


@pytest.mark.component
def test_product_intelligence_query_ignores_numeric_style_but_allows_alphanumeric_style() -> (
    None
):
    numeric_queries = build_search_queries(
        {
            "brand": "Wrangler",
            "title": "Relaxed Bootcut Jeans",
            "style": "3200040112342570",
        },
        source_domain_value="belk.com",
    )
    style_queries = build_search_queries(
        {
            "brand": "Wrangler",
            "title": "Relaxed Bootcut Jeans",
            "style": "1123A257",
        },
        source_domain_value="belk.com",
    )

    assert all("3200040112342570" not in query for query in numeric_queries)
    assert any("1123A257" in query for query in style_queries)


@pytest.mark.component
def test_product_intelligence_query_preserves_possessives_in_title_phrases() -> None:
    queries = build_search_queries(
        {
            "brand": "Levis",
            "title": "Levi's Men's 511 Slim-Fit Jeans",
        },
        source_domain_value="belk.com",
    )

    assert queries
    assert any("Men's 511 Slim-Fit Jeans" in query for query in queries)
    assert all("men s" not in query.casefold() for query in queries)


@pytest.mark.component
def test_product_intelligence_variant_spec_mismatch_caps_score() -> None:
    # Source is a 4-in-1; candidate is a 3-in-1 variant of the same product line.
    # Both titles state the spec, values differ -> flagged and capped below auto-accept.
    result = score_candidate(
        source={
            "title": "Ninja Crispi 4-in-1 Portable Glass Air Fryer",
            "brand": "Ninja",
            "price": 159.99,
        },
        candidate={
            "title": "Ninja Crispi 3-in-1 Glass Air Fryer Portable",
            "brand": "Ninja",
            "price": 149.99,
        },
        source_type="marketplace",
    )

    assert result["reasons"]["variant_mismatch"] is True
    assert result["score"] <= 0.62
    assert result["label"] != "high"


@pytest.mark.component
def test_product_intelligence_brand_title_match_reaches_high_without_identifier() -> (
    None
):
    # Search payloads rarely carry a UPC; a brand-exact + strong-title retailer match
    # must still reach the auto-accept (high) band.
    result = score_candidate(
        source={
            "title": "Ninja Crispi 4-in-1 Portable Glass Air Fryer Cooking System",
            "brand": "Ninja",
            "price": 159.99,
        },
        candidate={
            "title": "Ninja Crispi 4-in-1 Portable Glass Air Fryer Cooking System",
            "brand": "Ninja",
            "price": 159.99,
        },
        source_type="retailer",
    )

    assert result["score"] >= 0.85
    assert result["label"] == "high"
    assert result["reasons"]["variant_mismatch"] is False


@pytest.mark.component
def test_product_intelligence_scorer_returns_breakdown() -> None:
    result = score_candidate(
        source={
            "title": "Levi's 511 Slim Fit Jeans",
            "brand": "Levis",
            "sku": "04511",
            "price": 59.99,
        },
        candidate={
            "title": "Levi's Men's 511 Slim Fit Jeans",
            "brand": "Levi's",
            "sku": "04511",
            "price": 62.0,
        },
        source_type="brand_dtc",
    )

    # Belk SKU is no longer a scoring signal; this brand-DTC + title match still
    # scores high via the brand-DTC floor (brand's own listing always ranks top).
    assert result["score"] >= 0.7
    assert result["reasons"]["brand_match"] is True
    # identifier_match is now GTIN-only; SKU/MPN/style are not identifiers for scoring.
    assert result["reasons"]["identifier_match"] is False
    assert result["reasons"]["gtin_match"] is False
    assert "sku_match" not in result["reasons"]
    assert "mpn_or_style_match" not in result["reasons"]


@pytest.mark.component
def test_product_intelligence_barcode_match_can_reach_high_confidence() -> None:
    result = score_candidate(
        source={
            "title": "Levi's 511 Slim Fit Stretch Jeans",
            "brand": "Levis",
            "gtin": "00194500874886",
            "price": 59.99,
        },
        candidate={
            "title": "Levi's Men's 511 Slim Fit Stretch Jeans",
            "brand": "Levi's",
            "barcode": "00194500874886",
            "price": 58.0,
        },
        source_type="brand_dtc",
    )

    assert result["score"] >= 0.85
    assert result["label"] == "high"
    assert result["reasons"]["gtin_match"] is True
    assert result["reasons"]["identifier_match"] is True


@pytest.mark.component
def test_product_intelligence_price_band_requires_positive_candidate_price() -> None:
    result = score_candidate(
        source={"title": "Levi's 511 Slim Fit Jeans", "brand": "Levis", "price": 59.99},
        candidate={"title": "Levi's 511 Slim Fit Jeans", "brand": "Levi's", "price": 0},
        source_type="brand_dtc",
    )

    assert result["reasons"]["price_band_match"] is False


@pytest.mark.component
def test_product_intelligence_scorer_parses_european_price_formats() -> None:
    result = score_candidate(
        source={"title": "Widget", "brand": "Acme", "price": "1.234,56"},
        candidate={"title": "Widget", "brand": "Acme", "price": "1234.56"},
        source_type="retailer",
    )

    assert result["reasons"]["price_band_match"] is True


@pytest.mark.component
def test_product_intelligence_scorer_uses_shopping_evidence_without_image() -> None:
    intelligence = build_search_result_intelligence(
        source={
            "title": "Crown & Ivy Floral Midi Dress",
            "brand": "Crown & Ivy",
            "sku": "1804101ABC",
            "price": 49.99,
        },
        candidate_payload={
            "provider": "serpapi_shopping",
            "title": "Crown & Ivy Floral Midi Dress",
            "source": "Macy's",
            "price": "$50.00",
            "extracted_price": 50.0,
            "product_id": "shopping-product-id",
            "product_link": "https://www.google.com/search?ibp=oshop&q=dress",
        },
        candidate_url="https://www.macys.com/p/crown-ivy-floral-midi-dress/123.html",
        candidate_domain="macys.com",
        source_type="retailer",
    )

    reasons = intelligence["score_reasons"]
    assert reasons["shopping_product_group"] is True
    assert reasons["brand_match"] is True
    assert reasons["price_band_match"] is True
    assert "image" not in reasons


@pytest.mark.component
def test_product_intelligence_scorer_keeps_title_only_low_without_brand() -> None:
    # No brand match means no confidence floor fires: a title-only match is driven
    # purely by title-similarity weight and can never reach the auto-accept band.
    result = score_candidate(
        source={"title": "Floral Midi Dress", "brand": "", "price": 49.99},
        candidate={"title": "Floral Midi Dress", "brand": "", "price": None},
        source_type="unknown",
    )

    assert result["score"] < 0.6
    assert result["label"] in {"low", "uncertain"}
    assert result["reasons"]["brand_match"] is False
    assert result["reasons"]["identifier_match"] is False


@pytest.mark.component
def test_product_intelligence_scorer_keeps_weak_title_only_uncertain() -> None:
    result = score_candidate(
        source={"title": "Floral Midi Dress", "brand": "", "price": 49.99},
        candidate={"title": "Striped Maxi Skirt", "brand": "", "price": None},
        source_type="unknown",
    )

    assert result["score"] < 0.4
    assert result["label"] == "uncertain"
    assert result["reasons"]["identifier_match"] is False


@pytest.mark.component
def test_product_intelligence_uses_source_brand_when_candidate_title_mentions_it() -> (
    None
):
    intelligence = build_search_result_intelligence(
        source={
            "title": "Wrangler Relaxed Bootcut Jeans",
            "brand": "Wrangler\u00ae",
            "price": 50.0,
        },
        candidate_payload={
            "provider": "serpapi_immersive",
            "title": "Wrangler Men's Relaxed Fit Bootcut Jeans - Light Indigo 42x30",
            "source": "Target",
            "price": "$29.99",
            "product_id": "7366383223444725599",
            "product_link": "https://www.google.com/search?ibp=oshop&q=wrangler",
        },
        candidate_url="https://www.target.com/p/wrangler-men-relaxed-fit-bootcut-jeans/-/A-94371457",
        candidate_domain="target.com",
        source_type="retailer",
    )

    assert intelligence["canonical_record"]["brand"] == "wrangler"
    assert intelligence["canonical_record"]["normalized_brand"] == "wrangler"
    assert intelligence["score_reasons"]["brand_match"] is True
    # Brand-exact + full coverage of the source's distinctive model tokens (relaxed/bootcut/
    # jeans) is a deterministic model-level match, so this lands in the reviewable medium band
    # rather than low. match_basis records why.
    assert intelligence["confidence_label"] == "medium"
    assert intelligence["score_reasons"]["match_basis"] == "model+brand"


@pytest.mark.component
def test_product_intelligence_classification_avoids_suffix_collisions() -> None:
    assert classify_source_type("badamazon.com", {}) == "unknown"
    assert classify_source_type("shop.amazon.com", {}) == "marketplace"


@pytest.mark.component
def test_product_intelligence_classifies_common_aggregator_sources() -> None:
    assert classify_source_type("www.myntra.com", {}) == "retailer"
    assert classify_source_type("www.nykaa.com", {}) == "retailer"
    assert classify_source_type("www.flipkart.com", {}) == "marketplace"


@pytest.mark.component
def test_product_intelligence_classifies_known_mall_mirrors_as_aggregators() -> None:
    assert classify_source_type("thesummitbirmingham.com", {}) == "aggregator"
    assert classify_source_type("www.coolspringsgalleria.com", {}) == "aggregator"


@pytest.mark.component
def test_product_intelligence_normalizes_childrenswear_brand_alias() -> None:
    assert normalize_brand("Ralph Lauren Childrenswear") == "ralph lauren"


@pytest.mark.component
def test_product_intelligence_normalizes_common_brand_aliases() -> None:
    assert normalize_brand("Kenneth Cole Reaction") == "kenneth cole"
    assert normalize_brand("Tommy Bahama®") == "tommy bahama"
    assert (
        normalize_brand("Collection by Michael Strahan ™")
        == "collection by michael strahan"
    )


@pytest.mark.component
def test_product_intelligence_infers_brand_from_source_url() -> None:
    snapshot = extract_product_snapshot(
        {
            "url": "https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
            "title": "Varick Slim Straight Garment-Dyed Jeans",
        }
    )

    assert snapshot["brand"] == "ralph lauren"
    assert snapshot["normalized_brand"] == "ralph lauren"


@pytest.mark.component
def test_product_intelligence_query_uses_brand_and_currency_inferred_from_belk_slug() -> (
    None
):
    snapshot = extract_product_snapshot(
        {
            "url": "https://www.belk.com/p/modern-southern-home--checkerboard-quilt-set/710097411786005.html",
            "title": "Checkerboard Quilt Set",
            "price": "$22.50",
        }
    )
    queries = build_search_queries(snapshot, source_domain_value="belk.com")

    assert snapshot["brand"] == "Modern Southern Home"
    assert snapshot["normalized_brand"] == "modern southern home"
    assert snapshot["currency"] == "USD"
    assert queries
    assert "modern southern home" in queries[0]


@pytest.mark.component
def test_product_intelligence_infers_belk_brand_from_registry() -> None:
    snapshot = extract_product_snapshot(
        {
            "url": "https://www.belk.com/p/crown-ivy-floral-midi-dress/1804101ABC.html",
            "title": "Floral Midi Dress",
            "product_id": "1804101ABC",
        }
    )

    assert snapshot["brand"] == "Crown & Ivy"
    assert snapshot["sku"] == "1804101ABC"
    assert is_private_label(snapshot["brand"]) is True


@pytest.mark.component
def test_product_intelligence_canonicalizes_overlong_known_brand() -> None:
    snapshot = extract_product_snapshot(
        {
            "brand": "Columbia Big & Tall Tamiami™",
            "title": "Columbia Big & Tall Tamiami™ II SS Shirt",
            "url": "https://www.belk.com/p/columbia-big-tall-tamiami-ii-ss-shirt/32054651287053.html",
        }
    )

    assert snapshot["brand"] == "columbia"
    assert snapshot["normalized_brand"] == "columbia"


@pytest.mark.component
def test_product_intelligence_excludes_belk_exclusive_aliases() -> None:
    assert is_private_label("Ocean + Coast") is True
    assert is_private_label("goodness & grace") is True
