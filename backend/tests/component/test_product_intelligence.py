from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_intelligence import (
    ProductIntelligenceCandidate,
    ProductIntelligenceJob,
    ProductIntelligenceMatch,
    ProductIntelligenceSourceProduct,
)
from app.models.crawl_run import CrawlRecord
from app.schemas.product_intelligence import ProductIntelligenceDiscoveryRequest
from app.services.config.product_intelligence import (
    GOOGLE_NATIVE_HOME_URL,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT,
    SOURCE_TYPE_BRAND_DTC,
    ProductIntelligenceSettings,
    product_intelligence_settings,
)
from app.services.llm.config_service import get_prompt_task
from app.services.product_intelligence.discovery import (
    SearchResult,
    google_native_blocked,
    google_native_session,
    parse_google_native_results,
    parse_serpapi_immersive_results,
    parse_serpapi_shopping_results,
    build_search_queries,
    classify_source_type,
    discover_candidates,
)
from app.services.product_intelligence import discovery as discovery_module
from app.services.product_intelligence.matching import (
    build_search_result_intelligence,
    extract_product_snapshot,
    extract_search_result_snapshot,
    is_private_label,
    normalize_brand,
    score_candidate,
)
from app.services.llm.circuit_breaker import LLMErrorCategory
from app.services.llm.types import LLMTaskResult
from app.services.product_intelligence.service import (
    backfill_candidate_brand,
    poll_candidate_and_score,
    resolve_source_snapshot,
    create_product_intelligence_job,
    discover_product_intelligence_candidates,
)


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
def test_product_intelligence_query_strips_repeated_brand_and_targets_brand_domain() -> None:
    queries = build_search_queries(
        {
            "brand": "Wrangler�",
            "title": "Wrangler� Relaxed Bootcut Jeans",
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
def test_product_intelligence_query_keeps_brand_in_all_queries_when_brand_exists() -> None:
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
def test_product_intelligence_query_prefers_clean_brand_query_before_buy_for_aggregator_sources() -> None:
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
def test_product_intelligence_query_uses_brandless_fallback_only_when_brand_missing() -> None:
    queries = build_search_queries(
        {
            "title": "Vit. C Daily Glow Cream 150g",
            "mpn": "MC150G",
            "sku": "20510856",
        },
        source_domain_value="myntra.com",
    )

    assert queries
    assert any('MC150G' in query for query in queries)
    assert all("mamaearth" not in query for query in queries)
    assert queries[0] == '"Vit. C Daily Glow Cream 150g" "MC150G"'
    assert queries[1] == '"Vit. C Daily Glow Cream 150g" buy'
    assert len(queries) == 2


@pytest.mark.component
def test_product_intelligence_query_ignores_numeric_style_but_allows_alphanumeric_style() -> None:
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
def test_product_intelligence_brand_title_match_reaches_high_without_identifier() -> None:
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
def test_product_intelligence_uses_source_brand_when_candidate_title_mentions_it() -> None:
    intelligence = build_search_result_intelligence(
        source={
            "title": "Wrangler Relaxed Bootcut Jeans",
            "brand": "Wrangler�",
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
    assert normalize_brand("Collection by Michael Strahan ™") == "collection by michael strahan"


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
def test_product_intelligence_query_uses_brand_and_currency_inferred_from_belk_slug() -> None:
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
    assert 'modern southern home' in queries[0]


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
def test_product_intelligence_search_result_snapshot_infers_known_brand_from_compact_domain() -> None:
    snapshot = extract_search_result_snapshot(
        {"title": "Bifold RFID Wallet", "snippet": "Leather wallet."},
        url="https://www.kennethcole.com/collections/kenneth-cole-reaction",
        domain="kennethcole.com",
    )

    assert snapshot["brand"] == "kenneth cole"
    assert snapshot["normalized_brand"] == "kenneth cole"


@pytest.mark.component
def test_product_intelligence_search_result_snapshot_tries_brand_from_title_marker() -> None:
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
        ProductIntelligenceSettings(_env_file=None, default_search_provider="duckduckgo")


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
async def test_google_native_session_reuses_single_page_across_queries(monkeypatch) -> None:
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
        "app.services.product_intelligence.discovery.get_browser_runtime",
        _fake_runtime,
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.get_page_html",
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
        "app.services.product_intelligence.discovery.get_browser_runtime",
        _fake_runtime,
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.get_page_html",
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


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_skips_llm_when_brand_present(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_run_prompt_task(*args, **kwargs):
        calls.append(kwargs.get("task_type", ""))
        raise AssertionError("LLM must not be called when brand already resolved")

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,  # never used because LLM path is gated off
        raw={"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "url": "https://www.belk.com/p/1.html"},
        llm_enabled=True,
    )

    assert snapshot["brand"] == "Levis"
    assert snapshot["normalized_brand"] == "levi's"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_skips_llm_when_disabled(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called when llm_enabled is False")

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,
        raw={"title": "Wundermost Bodysuit", "url": "https://shop.example.com/products/wundermost.html"},
        llm_enabled=False,
    )

    assert snapshot["brand"] == ""
    assert snapshot["normalized_brand"] == ""


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_uses_llm_brand_when_confident(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        captured["task_type"] = task_type
        captured["domain"] = domain
        captured["variables"] = variables
        return LLMTaskResult(
            payload={"brand": "Lululemon", "confidence": 0.92, "rationale": "DTC URL match"},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,
        raw={
            "title": "Wundermost Bodysuit",
            "url": "https://www.lululemon.com/products/p/wundermost-bodysuit.html",
        },
        llm_enabled=True,
    )

    assert snapshot["brand"] == "Lululemon"
    assert snapshot["normalized_brand"] == "lululemon"
    assert captured["task_type"] == "product_intelligence_brand_inference"
    assert captured["domain"] == "lululemon.com"
    assert captured["variables"]["product_title"] == "Wundermost Bodysuit"
    assert captured["variables"]["source_domain"] == "lululemon.com"


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_drops_low_confidence_llm_brand(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={"brand": "MaybeBrand", "confidence": 0.2, "rationale": "weak signal"},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,
        raw={"title": "Random Title", "url": "https://retailer.example.com/p/123.html"},
        llm_enabled=True,
    )

    assert snapshot["brand"] == ""
    assert snapshot["normalized_brand"] == ""


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_swallows_llm_error(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload=None,
            error_message="provider unavailable",
            error_category=LLMErrorCategory.PROVIDER_ERROR,
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,
        raw={"title": "Random Title", "url": "https://retailer.example.com/p/123.html"},
        llm_enabled=True,
    )

    assert snapshot["brand"] == ""
    assert snapshot["normalized_brand"] == ""


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_skips_llm_when_no_inputs(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called without title or url")

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,
        raw={},
        llm_enabled=True,
    )

    assert snapshot["brand"] == ""


def _build_candidate_intelligence(*, brand: str = "", title: str = "Wundermost Bodysuit") -> dict[str, object]:
    return {
        "canonical_record": {
            "title": title,
            "brand": brand,
            "normalized_brand": normalize_brand(brand),
            "url": "https://www.lululemon.com/products/p/wundermost-bodysuit/1.html",
            "snippet": "",
            "description": "",
        },
        "confidence_score": 0.30,
        "confidence_label": "uncertain",
        "score_reasons": {"brand_match": False},
        "cleanup_source": "deterministic_google_native",
        "llm_enrichment": {"requested": False, "applied": False},
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_backfill_candidate_brand_skips_when_disabled(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called when llm_enabled is False")

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    result = await backfill_candidate_brand(
        session=None,
        source={"title": "Lululemon Wundermost Bodysuit", "brand": "Lululemon"},
        intelligence=intelligence,
        source_type="brand_dtc",
        llm_enabled=False,
    )

    assert result is intelligence


@pytest.mark.asyncio
@pytest.mark.component
async def test_backfill_candidate_brand_skips_when_brand_present(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called when candidate brand is set")

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence(brand="Lululemon")
    result = await backfill_candidate_brand(
        session=None,
        source={"title": "Lululemon Wundermost Bodysuit", "brand": "Lululemon"},
        intelligence=intelligence,
        source_type="brand_dtc",
        llm_enabled=True,
    )

    assert result is intelligence


@pytest.mark.asyncio
@pytest.mark.component
async def test_backfill_candidate_brand_applies_llm_brand_and_rescores(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={"brand": "Lululemon", "confidence": 0.91, "rationale": "DTC URL match"},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    source = {
        "title": "Lululemon Wundermost Bodysuit",
        "brand": "Lululemon",
        "normalized_brand": "lululemon",
    }
    result = await backfill_candidate_brand(
        session=None,
        source=source,
        intelligence=intelligence,
        source_type="brand_dtc",
        llm_enabled=True,
    )

    canonical = result["canonical_record"]
    assert canonical["brand"] == "Lululemon"
    assert canonical["normalized_brand"] == "lululemon"
    assert result["score_reasons"]["brand_match"] is True
    assert result["confidence_score"] > intelligence["confidence_score"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_backfill_candidate_brand_drops_low_confidence(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={"brand": "Maybe", "confidence": 0.1, "rationale": "weak"},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    result = await backfill_candidate_brand(
        session=None,
        source={"title": "Wundermost Bodysuit", "brand": ""},
        intelligence=intelligence,
        source_type="unknown",
        llm_enabled=True,
    )

    assert result is intelligence


@pytest.mark.asyncio
@pytest.mark.component
async def test_backfill_candidate_brand_handles_llm_error(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload=None,
            error_message="provider down",
            error_category=LLMErrorCategory.PROVIDER_ERROR,
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    result = await backfill_candidate_brand(
        session=None,
        source={"title": "Anything", "brand": ""},
        intelligence=intelligence,
        source_type="retailer",
        llm_enabled=True,
    )

    assert result is intelligence


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_preserves_serpapi_payload(monkeypatch) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        return [
            SearchResult(
                url="https://www.levi.com/p/04511.html",
                payload={
                    "provider": "serpapi",
                    "title": "Levi's 511 Slim Fit Jeans",
                    "snippet": "Official product page",
                },
            )
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "sku": "04511",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
    )

    assert candidates[0].payload["provider"] == "serpapi"
    assert candidates[0].payload["snippet"] == "Official product page"


@pytest.mark.component
def test_product_intelligence_parses_serpapi_shopping_payload() -> None:
    results = parse_serpapi_shopping_results(
        {
            "shopping_results": [
                {
                    "position": 1,
                    "title": "Crown & Ivy Floral Midi Dress",
                    "source": "Belk",
                    "link": "https://www.example.com/p/crown-ivy-floral-midi-dress/123.html",
                    "product_id": "987654321",
                    "product_link": "https://www.google.com/search?ibp=oshop&q=dress",
                    "serpapi_immersive_product_api": "https://serpapi.com/search.json?engine=google_immersive_product&page_token=abc",
                    "price": "$49.99",
                    "extracted_price": 49.99,
                    "thumbnail": "https://example.com/image.jpg",
                    "rating": 4.8,
                    "reviews": 27,
                    "delivery": "Free delivery",
                }
            ]
        }
    )

    assert results[0].url == "https://www.example.com/p/crown-ivy-floral-midi-dress/123.html"
    assert results[0].payload["provider"] == "serpapi_shopping"
    assert results[0].payload["product_id"] == "987654321"
    assert results[0].payload["extracted_price"] == pytest.approx(49.99)
    assert results[0].payload["thumbnail"] == "https://example.com/image.jpg"


@pytest.mark.component
def test_product_intelligence_parses_serpapi_immersive_store_links() -> None:
    results = parse_serpapi_immersive_results(
        {
            "product_results": {
                "title": "Levi's 511 Slim Fit Jeans",
                "product_id": "immersive-product-id",
                "description": "Slim fit jeans.",
                "thumbnails": ["https://example.com/image.jpg"],
                "stores": [
                    {
                        "name": "Levi's",
                        "title": "Levi's 511 Slim Fit Jeans",
                        "link": "https://www.levi.com/p/04511.html",
                        "price": "$69.50",
                        "extracted_price": 69.5,
                        "shipping": "Free shipping",
                    }
                ],
            }
        },
        parent={
            "product_id": "shopping-product-id",
            "product_link": "https://www.google.com/search?ibp=oshop&q=levi",
        },
        limit=5,
    )

    assert results[0].url == "https://www.levi.com/p/04511.html"
    assert results[0].payload["provider"] == "serpapi_immersive"
    assert results[0].payload["product_id"] == "immersive-product-id"
    assert results[0].payload["product_link"] == "https://www.google.com/search?ibp=oshop&q=levi"
    assert results[0].payload["extracted_price"] == pytest.approx(69.5)


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_serpapi_searches_brand_organic_then_shopping(monkeypatch) -> None:
    engines: list[str] = []
    queries: list[str] = []

    async def fake_engine(query: str, *, engine: str, limit: int | None = None) -> dict[str, object]:
        del limit
        engines.append(engine)
        queries.append(query)
        if engine == "google_shopping":
            return {
                "shopping_results": [
                    {
                        "position": 1,
                        "title": "Levi's 511 Slim Fit Jeans",
                        "source": "Levi's",
                        "link": "https://www.levi.com/p/04511.html",
                        "product_id": "shopping-product-id",
                    }
                ]
            }
        return {
            "organic_results": [
                {
                    "position": 1,
                    "title": "Levi's 511 Slim Fit Jeans",
                    "link": "https://www.levi.com/p/04511.html",
                    "snippet": "Official product page",
                }
            ]
        }

    monkeypatch.setattr(discovery_module, "_search_serpapi_engine", fake_engine)

    results = await discovery_module._search_serpapi(
        "levi 511 site:levi.com",
        limit=5,
    )

    assert set(engines) == {"google_shopping", "google"}
    assert sorted(queries) == [
        "levi 511",
        "levi 511 site:levi.com",
    ]
    assert [result.payload["provider"] for result in results] == ["serpapi"]
    assert results[0].url == "https://www.levi.com/p/04511.html"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_serpapi_expands_immersive_store_links(monkeypatch) -> None:
    engines: list[str] = []

    async def fake_engine(query: str, *, engine: str, limit: int | None = None) -> dict[str, object]:
        del query, limit
        engines.append(engine)
        if engine == "google_shopping":
            return {
                "shopping_results": [
                    {
                        "position": 1,
                        "title": "Columbia Men's Tamiami II Short Sleeve Shirt",
                        "source": "Columbia Sportswear",
                        "product_id": "shopping-product-id",
                        "product_link": "https://www.google.com/search?ibp=oshop&q=columbia",
                        "serpapi_immersive_product_api": "https://serpapi.com/search.json?engine=google_immersive_product&page_token=abc",
                    }
                ]
            }
        return {"organic_results": []}

    async def fake_immersive(item: dict[str, object]) -> dict[str, object]:
        assert item["product_id"] == "shopping-product-id"
        return {
            "product_results": {
                "title": "Columbia Men's Tamiami II Short Sleeve Shirt",
                "product_id": "immersive-product-id",
                "stores": [
                    {
                        "name": "Columbia Sportswear",
                        "title": "Men's PFG Tamiami II Short Sleeve Shirt",
                        "link": "https://www.columbia.com/p/mens-pfg-tamiami-ii-short-sleeve-shirt-big-FM7253.html",
                    }
                ],
            }
        }

    monkeypatch.setattr(discovery_module, "_search_serpapi_engine", fake_engine)
    monkeypatch.setattr(discovery_module, "_search_serpapi_immersive_product", fake_immersive)

    results = await discovery_module._search_serpapi(
        "columbia big tall tamiami II SS Shirt",
        limit=5,
    )

    assert engines == ["google_shopping"]
    assert results[0].url == "https://www.columbia.com/p/mens-pfg-tamiami-ii-short-sleeve-shirt-big-FM7253.html"
    assert results[0].payload["provider"] == "serpapi_immersive"
    assert results[0].payload["product_id"] == "immersive-product-id"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_serpapi_runs_identifier_organic_without_immersive(monkeypatch) -> None:
    engines: list[str] = []

    async def fake_engine(query: str, *, engine: str, limit: int | None = None) -> dict[str, object]:
        del limit
        engines.append(engine)
        if engine == "google_shopping":
            return {
                "shopping_results": [
                    {
                        "position": 1,
                        "title": "Wrangler Relaxed Bootcut Jeans",
                        "source": "Wrangler",
                        "product_id": "shopping-product-id",
                        "link": "https://www.macys.com/p/wrangler-jeans/123.html",
                    }
                ]
            }
        return {
            "organic_results": [
                {
                    "position": 1,
                    "title": "Wrangler Relaxed Bootcut Jeans",
                    "link": "https://www.wrangler.com/shop/relaxed-bootcut-jeans.html",
                    "snippet": "Official product page.",
                }
            ]
        }

    monkeypatch.setattr(discovery_module, "_search_serpapi_engine", fake_engine)

    results = await discovery_module._search_serpapi(
        "wrangler relaxed bootcut jeans 1123425700 site:wrangler.com",
        limit=5,
    )

    assert engines.count("google") == 1
    assert engines.count("google_shopping") == 1
    assert [result.payload["provider"] for result in results] == [
        "serpapi",
        "serpapi_shopping",
    ]
    assert results[0].url == "https://www.wrangler.com/shop/relaxed-bootcut-jeans.html"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_serpapi_keeps_brand_site_lookup_when_shopping_has_multiple_results(
    monkeypatch,
) -> None:
    engines: list[tuple[str, str]] = []

    async def fake_engine(query: str, *, engine: str, limit: int | None = None) -> dict[str, object]:
        del limit
        engines.append((engine, query))
        if engine == "google_shopping":
            return {
                "shopping_results": [
                    {
                        "position": 1,
                        "title": "Levi's 511 Slim Fit Jeans",
                        "source": "Macy's",
                        "link": "https://www.macys.com/p/levi-511/1.html",
                    },
                    {
                        "position": 2,
                        "title": "Levi's 511 Slim Fit Jeans",
                        "source": "Amazon",
                        "link": "https://www.amazon.com/levi-511/2.html",
                    },
                ]
            }
        if query == "levi 511 site:levi.com":
            return {
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Levi's 511 Slim Fit Jeans",
                        "link": "https://www.levi.com/p/04511.html",
                        "snippet": "Official product page",
                    }
                ]
            }
        return {"organic_results": []}

    monkeypatch.setattr(discovery_module, "_search_serpapi_engine", fake_engine)

    results = await discovery_module._search_serpapi(
        "levi 511 site:levi.com",
        limit=5,
    )

    assert ("google", "levi 511 site:levi.com") in engines
    assert ("google", "levi 511") not in engines
    assert results[0].url == "https://www.levi.com/p/04511.html"
    assert results[0].payload["provider"] == "serpapi"


@pytest.mark.component
def test_product_intelligence_serpapi_shopping_query_strips_site_filters() -> None:
    assert (
        discovery_module._shopping_query(
            "wrangler relaxed bootcut jeans site:wrangler.com -site:belk.com"
        )
        == "wrangler relaxed bootcut jeans"
    )


@pytest.mark.component
def test_product_intelligence_parses_serpapi_immersive_limit_before_about_link() -> None:
    results = parse_serpapi_immersive_results(
        {
            "product_results": {
                "title": "Levi's 511 Slim Fit Jeans",
                "product_id": "immersive-product-id",
                "stores": [
                    {
                        "name": "Levi's",
                        "title": "Levi's 511 Slim Fit Jeans",
                        "link": "https://www.levi.com/p/04511.html",
                    }
                ],
                "about_the_product": {
                    "title": "About Levi's 511 Slim Fit Jeans",
                    "link": "https://www.levi.com/us/en_us/product/511",
                    "displayed_link": "levi.com",
                },
            }
        },
        parent={"product_link": "https://www.google.com/search?ibp=oshop&q=levi"},
        limit=1,
    )

    assert len(results) == 1
    assert results[0].url == "https://www.levi.com/p/04511.html"


@pytest.mark.component
def test_product_intelligence_parses_serpapi_immersive_when_about_payload_is_not_a_dict() -> None:
    results = parse_serpapi_immersive_results(
        {
            "product_results": {
                "title": "Levi's 511 Slim Fit Jeans",
                "product_id": "immersive-product-id",
                "about_the_product": "unexpected",
                "stores": [
                    {
                        "name": "Levi's",
                        "title": "Levi's 511 Slim Fit Jeans",
                        "link": "https://www.levi.com/p/04511.html",
                    }
                ],
            }
        },
        parent={"product_link": "https://www.google.com/search?ibp=oshop&q=levi"},
        limit=5,
    )

    assert len(results) == 1
    assert results[0].payload["raw"]["product"]["description"] == ""


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_passes_pool_limit_to_search(monkeypatch) -> None:
    limits: list[int | None] = []

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        limits.append(limit)
        return [
            SearchResult(url="https://www.levi.com/p/04511.html", payload={"title": "Levi 511"}),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(product_intelligence_settings, "discovery_pool_multiplier", 4)

    await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511"},
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=5,
    )

    assert limits
    assert set(limits) == {20}


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_keeps_multiple_listings_per_domain(monkeypatch) -> None:
    # A product can be listed by multiple third-party sellers on one marketplace,
    # so discovery must keep more than one distinct listing per domain (bounded only
    # by the user's max_candidates request), not collapse to one per domain.
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        return [
            SearchResult(url="https://www.ebay.com/itm/1", payload={"title": "Levi 511"}),
            SearchResult(url="https://www.ebay.com/itm/2", payload={"title": "Levi 511 sale"}),
            SearchResult(url="https://www.macys.com/p/1.html", payload={"title": "Levi 511"}),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=5,
    )

    domains = sorted(candidate.domain for candidate in candidates)
    # Both eBay third-party listings survive alongside the macys listing.
    assert domains == ["ebay.com", "ebay.com", "macys.com"]
    urls = {candidate.url for candidate in candidates}
    assert "https://www.ebay.com/itm/1" in urls
    assert "https://www.ebay.com/itm/2" in urls


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_prioritizes_brand_site_over_aggregator_pool(monkeypatch) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        if "site:levi.com" in query:
            return [
                SearchResult(url="https://thesummitbirmingham.com/buy/product/511", payload={"title": "Levi 511"}),
                SearchResult(url="https://www.hamiltonplace.com/products/product/511", payload={"title": "Levi 511"}),
                SearchResult(url="https://www.coolspringsgalleria.com/products/product/511", payload={"title": "Levi 511"}),
            ]
        return [
            SearchResult(url="https://www.levi.com/p/04511.html", payload={"title": "Levi 511"}),
            SearchResult(url="https://www.macys.com/p/04511.html", payload={"title": "Levi 511"}),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(product_intelligence_settings, "discovery_pool_multiplier", 4)

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "sku": "04511",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=2,
    )

    assert [candidate.domain for candidate in candidates] == ["levi.com", "macys.com"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_skips_invalid_result_urls(monkeypatch) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        return [
            SearchResult(
                url="javascript:void(0)",
                payload={"provider": provider, "title": "Bad scheme"},
            ),
            SearchResult(
                url="",
                payload={"provider": provider, "title": "Empty"},
            ),
            SearchResult(
                url="https://www.levi.com/p/04511.html",
                payload={"provider": provider, "title": "Levi 511"},
            ),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    candidates = await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511"},
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
    )

    assert len(candidates) == 1
    assert candidates[0].domain == "levi.com"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_rejects_listing_urls_from_serpapi() -> None:
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans/",
                payload={
                    "provider": "serpapi",
                    "title": "Men's Jeans & Denim",
                    "snippet": "Shop fits, washes and denim styles.",
                },
            ),
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans/varick-slim-straight-garment-dyed-jean/123.html",
                payload={
                    "provider": "serpapi",
                    "title": "Polo Ralph Lauren Varick Slim Straight Garment-Dyed Jean",
                    "snippet": "Product page for Varick garment-dyed jeans.",
                },
            ),
        ]

    candidates = await discover_candidates(
        {
            "brand": "Polo Ralph Lauren",
            "title": "Varick Slim Straight Garment-Dyed Jeans",
            "url": "https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.ralphlauren.com/men-clothing-jeans/varick-slim-straight-garment-dyed-jean/123.html"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_rejects_html_listing_urls() -> None:
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans.html",
                payload={
                    "provider": "serpapi",
                    "title": "Men's Jeans & Denim",
                    "snippet": "Shop denim by fit and wash.",
                },
            ),
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans/varick-slim-straight-garment-dyed-jean/123.html",
                payload={
                    "provider": "serpapi",
                    "title": "Polo Ralph Lauren Varick Slim Straight Garment-Dyed Jean",
                    "snippet": "Product page for Varick garment-dyed jeans.",
                },
            ),
        ]

    candidates = await discover_candidates(
        {
            "brand": "Polo Ralph Lauren",
            "title": "Varick Slim Straight Garment-Dyed Jeans",
            "url": "https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.ralphlauren.com/men-clothing-jeans/varick-slim-straight-garment-dyed-jean/123.html"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_keeps_matching_slug_without_detail_marker() -> None:
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://www.levi.com/men/jeans/511-slim-fit-stretch-denim",
                payload={
                    "provider": "serpapi",
                    "title": "Levi's 511 Slim Fit Stretch Denim Jeans",
                    "snippet": "Official Levi's product page.",
                },
            )
        ]

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Stretch Denim Jeans",
            "url": "https://www.belk.com/p/levis-511-slim-fit-jeans/1.html",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.levi.com/men/jeans/511-slim-fit-stretch-denim"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_allows_marketplace_item_ids_when_title_matches() -> None:
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://www.ebay.com/itm/188098451561",
                payload={
                    "provider": "serpapi_immersive",
                    "title": "Izod Men's Comfort Stretch Blue Denim Jeans",
                    "source": "eBay",
                    "product_id": "3501016343738340012",
                },
            )
        ]

    candidates = await discover_candidates(
        {
            "brand": "IZOD",
            "title": "Comfort Stretch Blue Denim Jeans",
            "sku": "3203394I39JN16",
            "url": "https://www.belk.com/p/izod-jeans/1.html",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.ebay.com/itm/188098451561"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_rejects_editorial_brand_pages() -> None:
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://eu.wrangler.com/uk-en/how%20to%20style%20bootcut%20jeans/how-to-wear-bootcut-jeans.html",
                payload={
                    "provider": "serpapi",
                    "title": "How to Wear Bootcut Jeans",
                    "snippet": "A styling guide from Wrangler.",
                },
            ),
            SearchResult(
                url="https://www.wrangler.com/browse/relaxed-fit-bootcut-jeans.html",
                payload={
                    "provider": "serpapi",
                    "title": "Relaxed Fit Bootcut Jeans",
                    "snippet": "Wrangler product page.",
                },
            ),
        ]

    candidates = await discover_candidates(
        {
            "brand": "Wrangler�",
            "title": "Wrangler� Relaxed Bootcut Jeans",
            "url": "https://www.belk.com/p/wrangler--relaxed-bootcut-jeans-/3200040112342570.html",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.wrangler.com/browse/relaxed-fit-bootcut-jeans.html"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_rejects_unrelated_google_native_products() -> None:
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://www.levi.com/p/505-regular-fit-mens-jeans/005050260.html",
                payload={
                    "provider": "google_native",
                    "title": "Levi's 505 Regular Fit Men's Jeans",
                    "snippet": "Classic straight leg jeans.",
                },
            ),
            SearchResult(
                url="https://www.levi.com/p/511-slim-fit-mens-jeans/045112406.html",
                payload={
                    "provider": "google_native",
                    "title": "Levi's 511 Slim Fit Men's Jeans",
                    "snippet": "Slim fit jeans, style 04511-2406.",
                },
            ),
        ]

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "sku": "04511-2406",
            "url": "https://www.belk.com/p/levis-511-slim-fit-jeans/1.html",
        },
        source_domain_value="belk.com",
        provider="google_native",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.levi.com/p/511-slim-fit-mens-jeans/045112406.html"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_rejects_google_native_source_domain_and_url() -> None:
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        assert "belk.com" not in query
        del limit
        return [
            SearchResult(
                url="https://www.belk.com/p/nike-womens-run-defy-sneakers/2900020HM9593.html",
                payload={
                    "provider": "google_native",
                    "title": "Women's Run Defy Sneakers",
                    "snippet": "Nike sneakers at Belk.",
                },
            ),
            SearchResult(
                url="https://www.nike.com/t/run-defy-womens-road-running-shoes/HM9593",
                payload={
                    "provider": "google_native",
                    "title": "Nike Run Defy Women's Road Running Shoes",
                    "snippet": "Style HM9593.",
                },
            ),
        ]

    candidates = await discover_candidates(
        {
            "brand": "Nike",
            "title": "Women's Run Defy Sneakers",
            "sku": "HM9593",
            "url": "https://www.belk.com/p/nike-womens-run-defy-sneakers/2900020HM9593.html",
        },
        source_domain_value="belk.com",
        provider="google_native",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.nike.com/t/run-defy-womens-road-running-shoes/HM9593"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_keeps_search_delay_while_filling_pool(monkeypatch) -> None:
    recorded_delays: list[float] = []

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        if query == "query one":
            return [
                SearchResult(url="https://www.levi.com/p/04511.html", payload={"title": "Levi 511"}),
            ]
        return [
            SearchResult(url="https://www.macys.com/p/04511.html", payload={"title": "Levi 511"}),
        ]

    async def fake_sleep(delay: float) -> None:
        recorded_delays.append(delay)

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.build_search_queries",
        lambda product, *, source_domain_value: ["query one", "query two"],
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.asyncio.sleep",
        fake_sleep,
    )
    monkeypatch.setattr(product_intelligence_settings, "search_delay_ms", 25)
    monkeypatch.setattr(product_intelligence_settings, "discovery_pool_multiplier", 2)

    candidates = await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511"},
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
    )

    assert recorded_delays == [0.025]
    assert len(candidates) == 1
    assert candidates[0].domain == "levi.com"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_fills_requested_count_after_strong_first_query_brand_dtc(monkeypatch) -> None:
    seen_queries: list[str] = []
    recorded_delays: list[float] = []

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        del provider, limit
        seen_queries.append(query)
        if query == "query one":
            return [
                SearchResult(
                    url="https://www.levi.com/p/04511-2406.html",
                    payload={"title": "Levi's Men 511 Slim Fit Jeans"},
                )
            ]
        return [
            SearchResult(url="https://www.macys.com/p/04511.html", payload={"title": "Levi 511"}),
        ]

    async def fake_sleep(delay: float) -> None:
        recorded_delays.append(delay)

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.build_search_queries",
        lambda product, *, source_domain_value: ["query one", "query two"],
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.discovery.asyncio.sleep",
        fake_sleep,
    )
    monkeypatch.setattr(product_intelligence_settings, "search_delay_ms", 25)

    candidates = await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511-2406"},
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=2,
    )

    assert seen_queries == ["query one", "query two"]
    assert recorded_delays == [0.025]
    assert [candidate.domain for candidate in candidates] == ["levi.com", "macys.com"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_job_stores_source_products_and_llm_option(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://www.belk.com/category",
        surface="ecommerce_listing",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://www.belk.com/p/new-directions-shirt/1.html",
        data={
            "brand": "New Directions",
            "title": "Relaxed Shirt",
            "price": "$19.99",
            "url": "https://www.belk.com/p/new-directions-shirt/1.html",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    job = await create_product_intelligence_job(
        db_session,
        user=test_user,
        payload={
            "source_run_id": run.id,
            "source_record_ids": [record.id],
            "options": {
                "llm_enrichment_enabled": True,
                "private_label_mode": "flag",
            },
        },
    )

    assert job.options["llm_enrichment_enabled"] is True
    source = await db_session.scalar(
        select(ProductIntelligenceSourceProduct).where(
            ProductIntelligenceSourceProduct.job_id == job.id
        )
    )
    assert source is not None
    assert source.is_private_label is True
    assert source.price == pytest.approx(19.99)


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_preview_returns_source_and_payload(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://www.belk.com/category",
        surface="ecommerce_listing",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
        data={
            "title": "Varick Slim Straight Garment-Dyed Jeans",
            "price": "$125.00",
            "url": "https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        return [
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans/varick/123.html",
                payload={"provider": provider, "title": "Varick jean"},
            )
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_run_id": run.id,
            "source_record_ids": [record.id],
            "options": {
                "max_source_products": 1,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
                "confidence_threshold": 0.0,
            },
        },
    )

    assert response["source_count"] == 1
    assert response["candidate_count"] == 1
    assert isinstance(response["job_id"], int)
    assert response["candidates"][0]["source_brand"] == "ralph lauren"
    assert response["candidates"][0]["payload"]["provider"] == "serpapi"
    assert response["candidates"][0]["intelligence"]["canonical_record"]["title"] == "Varick jean"
    assert response["candidates"][0]["intelligence"]["canonical_record"]["price"] is None
    assert response["candidates"][0]["intelligence"]["confidence_score"] >= 0
    persisted_match = await db_session.scalar(
        select(ProductIntelligenceMatch).where(
            ProductIntelligenceMatch.job_id == response["job_id"]
        )
    )
    assert persisted_match is not None
    assert persisted_match.candidate_price is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_preview_skips_search_result_llm_enrichment(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://www.belk.com/category",
        surface="ecommerce_listing",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://www.belk.com/p/levis-511-slim-fit-jeans/1.html",
        data={
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "url": "https://www.belk.com/p/levis-511-slim-fit-jeans/1.html",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        del provider, query, limit
        return [
            SearchResult(
                url="https://www.levi.com/p/04511.html",
                payload={"provider": "serpapi", "title": "Levi's Men 511 Slim Fit Jeans"},
            )
        ]

    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        del session, run_id, domain, variables
        if task_type == "product_intelligence_enrichment":
            raise AssertionError("Discovery preview must not call enrichment LLM")
        return LLMTaskResult(
            payload={"brand": "Levis", "confidence": 0.95},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_run_id": run.id,
            "source_record_ids": [record.id],
            "options": {
                "max_source_products": 1,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
                "llm_enrichment_enabled": True,
            },
        },
    )

    assert response["candidate_count"] == 1
    assert response["candidates"][0]["intelligence"]["llm_enrichment"] == {
        "requested": False,
        "applied": False,
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_prefers_row_source_url_for_query_exclusion(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    seen_queries: list[str] = []

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        del provider, limit
        seen_queries.append(query)
        return [
            SearchResult(
                url="https://www.example-brand.com/p/item.html",
                payload={"provider": "google_native", "title": "Example Item"},
            )
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": "https://www.myntra.com/p/shoes/example-item.html",
                    "data": {
                        "title": "Example Item",
                        "brand": "Example Brand",
                        "url": "https://www.belk.com/p/stale-item.html",
                    },
                }
            ],
            "options": {
                "max_source_products": 1,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
                "confidence_threshold": 0.0,
            },
        },
    )

    assert seen_queries
    assert all("myntra.com" not in query for query in seen_queries)
    assert all("belk.com" not in query for query in seen_queries)
    assert response["candidates"][0]["source_url"] == "https://www.myntra.com/p/shoes/example-item.html"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_uses_product_url_from_listing_record(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://www.belk.com/men/mens-clothing/jeans/",
        surface="ecommerce_listing",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://www.belk.com/men/mens-clothing/jeans/",
        data={
            "brand": "Wrangler�",
            "title": "Wrangler� Relaxed Bootcut Jeans",
            "url": "https://www.belk.com/p/wrangler--relaxed-bootcut-jeans-/3200040112342570.html",
            "price": "39.95",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    seen_queries: list[str] = []

    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        del provider, limit
        seen_queries.append(query)
        return [
            SearchResult(
                url="https://www.wrangler.com/shop/relaxed-bootcut-jeans.html",
                payload={"provider": "serpapi", "title": "Wrangler Relaxed Bootcut Jeans"},
            )
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_record_ids": [record.id],
            "options": {
                "max_source_products": 1,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
                "confidence_threshold": 0.0,
            },
        },
    )

    assert response["candidates"][0]["source_url"] == (
        "https://www.belk.com/p/wrangler--relaxed-bootcut-jeans-/3200040112342570.html"
    )
    assert response["candidates"][0]["source_price"] == pytest.approx(39.95)
    assert seen_queries[0] == "site:wrangler.com wrangler Relaxed Bootcut Jeans"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_reuses_one_query_runner_for_multiple_sources(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    enter_count = 0
    seen_queries: list[str] = []

    class _Runner:
        async def __aenter__(self):
            nonlocal enter_count
            enter_count += 1

            async def _run(query: str, limit: int) -> list[SearchResult]:
                del limit
                seen_queries.append(query)
                token = len(seen_queries)
                return [
                    SearchResult(
                        url=f"https://www.levi.com/p/{token}.html",
                        payload={"provider": "google_native", "title": f"Product {token} 511 Jeans", "price": "$55.00"},
                    )
                ]

            return _run

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "app.services.product_intelligence.service.shared_query_runner",
        lambda provider: _Runner(),
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/one.html",
                    "data": {
                        "brand": "Levis",
                        "title": "Product One 511 Jeans",
                        "url": "https://www.belk.com/p/one.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/two.html",
                    "data": {
                        "brand": "Levis",
                        "title": "Product Two 511 Jeans",
                        "url": "https://www.belk.com/p/two.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 1,
                "search_provider": "google_native",
            },
        },
    )

    assert response["candidate_count"] == 2
    assert enter_count == 1
    assert len(seen_queries) >= 2


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_returns_max_urls_per_input_source(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        quoted = query.split('"')
        title_source = quoted[3] if len(quoted) > 3 else quoted[1] if len(quoted) > 1 else quoted[0]
        title_token = title_source.split()[0]
        return [
            SearchResult(url=f"https://www.levi.com/p/{title_token}.html", payload={"provider": provider, "title": title_token}),
            SearchResult(url=f"https://www.macys.com/p/{title_token}.html", payload={"provider": provider, "title": title_token}),
            SearchResult(url=f"https://www.nordstrom.com/p/{title_token}.html", payload={"provider": provider, "title": title_token}),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": f"https://www.belk.com/p/{index}.html",
                    "data": {
                        "brand": "Levis",
                        "title": f"Product {index} 511 Jeans",
                        "url": f"https://www.belk.com/p/{index}.html",
                    },
                }
                for index in range(4)
            ],
            "options": {
                "max_source_products": 4,
                "max_candidates_per_product": 3,
                "search_provider": "serpapi",
                "confidence_threshold": 0.0,
            },
        },
    )

    assert response["source_count"] == 4
    assert response["candidate_count"] == 12
    assert {candidate["source_index"] for candidate in response["candidates"]} == {0, 1, 2, 3}


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_source_count_excludes_private_label(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        del query
        return [
            SearchResult(
                url="https://www.levi.com/p/511.html",
                payload={"provider": provider, "title": "511 Jeans"},
            )
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/private.html",
                    "data": {
                        "brand": "New Directions",
                        "title": "Private label shirt",
                        "url": "https://www.belk.com/p/private.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/branded.html",
                    "data": {
                        "brand": "Levis",
                        "title": "511 Jeans",
                        "url": "https://www.belk.com/p/branded.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 1,
                "private_label_mode": "exclude",
                "search_provider": "serpapi",
            },
        },
    )

    assert response["source_count"] == 1
    assert response["candidate_count"] == 1
    assert response["candidates"][0]["source_index"] == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_defaults_private_label_mode_to_exclude(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        del query
        return [
            SearchResult(
                url="https://www.levi.com/p/511.html",
                payload={"provider": provider, "title": "511 Jeans"},
            )
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/private.html",
                    "data": {
                        "brand": "New Directions",
                        "title": "Private label shirt",
                        "url": "https://www.belk.com/p/private.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/branded.html",
                    "data": {
                        "brand": "Levis",
                        "title": "511 Jeans",
                        "url": "https://www.belk.com/p/branded.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
            },
        },
    )

    assert response["source_count"] == 1
    assert response["candidate_count"] == 1
    assert response["candidates"][0]["source_index"] == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_searches_title_only_sources(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
        title_token = query.split()[0]
        return [
            SearchResult(url=f"https://www.example-retailer.com/p/{title_token}-1.html", payload={"provider": provider, "title": title_token}),
            SearchResult(url=f"https://www.example-brand.com/p/{title_token}-2.html", payload={"provider": provider, "title": title_token}),
            SearchResult(url=f"https://www.example-market.com/p/{title_token}-3.html", payload={"provider": provider, "title": title_token}),
        ]

    monkeypatch.setattr(
        "app.services.product_intelligence.discovery._search_results",
        fake_search_results,
    )


    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/branded.html",
                    "data": {
                        "brand": "Levis",
                        "title": "Branded 511 Jeans",
                        "url": "https://www.belk.com/p/branded.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/unbranded.html",
                    "data": {
                        "title": "Unbranded Slim Jeans",
                        "url": "https://www.belk.com/p/unbranded.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 3,
                "search_provider": "serpapi",
                "confidence_threshold": 0.0,
            },
        },
    )

    assert response["source_count"] == 2
    assert response["candidate_count"] == 6
    assert {candidate["source_index"] for candidate in response["candidates"]} == {0, 1}


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_candidate_poll_marks_timeout(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = ProductIntelligenceJob(user_id=test_user.id, options={}, summary={})
    db_session.add(job)
    await db_session.flush()
    source = ProductIntelligenceSourceProduct(
        job_id=job.id,
        source_url="https://www.belk.com/p/1",
        brand="Levi's",
        normalized_brand="levi's",
        title="511 Jeans",
        payload={},
    )
    db_session.add(source)
    await db_session.flush()
    candidate = ProductIntelligenceCandidate(
        job_id=job.id,
        source_product_id=source.id,
        url="https://www.levi.com/p/1",
        status=PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED,
        payload={},
    )
    db_session.add(candidate)
    await db_session.flush()

    monkeypatch.setattr(product_intelligence_settings, "candidate_poll_seconds", 0.0)
    await poll_candidate_and_score(db_session, job, candidate)

    assert candidate.status == PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT


# ---------------------------------------------------------------------------
# Identity-anchor discovery rework (deterministic style-code + model token)
# ---------------------------------------------------------------------------


@pytest.mark.component
def test_manufacturer_style_code_decomposes_composite_sku() -> None:
    from app.services.product_intelligence.matching import manufacturer_style_code

    # Belk composite SKU = numeric retailer prefix + manufacturer style core.
    assert manufacturer_style_code("3900462FV5285") == "fv5285"
    # External listings expose the code bare or with a colorway suffix.
    assert manufacturer_style_code("Nike Promina FV5285-002 Black/White") == "fv5285"
    # A pure retailer numeric prefix is not a manufacturer code.
    assert manufacturer_style_code("3900462") == ""
    # The GTIN must never be mistaken for a style code.
    assert manufacturer_style_code("0197600670150", gtin_value="0197600670150") == ""


@pytest.mark.component
def test_score_candidate_style_code_match_reaches_auto_accept() -> None:
    source = extract_product_snapshot(
        {
            "title": "Men's Promina Sneakers",
            "brand": "Nike\u00ae",
            "sku": "3900462FV5285",
            "barcode": "0197600670150",
            "price": "$49.00",
            "url": "https://www.belk.com/p/nike-mens-promina-sneakers/3900462FV5285.html",
        }
    )
    candidate = extract_search_result_snapshot(
        {
            "title": "Nike Promina Men's Black White Fv5285-002 Walking Comfort Shoes",
            "source": "eBay",
            "provider": "serpapi_immersive",
            "product_id": "x",
        },
        url="https://www.ebay.com/itm/123",
        domain="ebay.com",
    )
    result = score_candidate(source=source, candidate=candidate, source_type="marketplace")

    assert result["reasons"]["style_code_match"] is True
    assert result["reasons"]["match_basis"] == "style_code"
    assert result["score"] >= 0.90
    assert result["label"] == "high"


@pytest.mark.component
def test_score_candidate_model_token_brand_is_model_level_match() -> None:
    # Terse source vs verbose candidate: raw title overlap is low, but brand-exact plus the
    # distinctive model token ("promina") is a deterministic model-level match.
    source = extract_product_snapshot(
        {"title": "Men's Promina Sneakers", "brand": "Nike\u00ae", "sku": "3900462FV5285"}
    )
    candidate = extract_search_result_snapshot(
        {
            "title": "Nike Promina Men's Walking Shoes (Extra Wide) Black",
            "source": "DSW",
            "provider": "serpapi_immersive",
            "product_id": "y",
        },
        url="https://www.dsw.com/product/nike-promina-walking-shoe-mens/582039",
        domain="dsw.com",
    )
    result = score_candidate(source=source, candidate=candidate, source_type="retailer")

    assert result["reasons"]["model_token_match"] is True
    assert result["reasons"]["match_basis"] == "model+brand"
    assert result["score"] >= 0.82


@pytest.mark.component
def test_score_candidate_same_brand_different_model_not_promoted() -> None:
    # Same brand, different model: the distinctive model token does not overlap, so this
    # must not reach the model-level floor.
    source = extract_product_snapshot(
        {"title": "Men's Promina Sneakers", "brand": "Nike\u00ae", "sku": "3900462FV5285"}
    )
    candidate = extract_search_result_snapshot(
        {"title": "Nike Air Force 1 Low Men's Shoes", "source": "Nike", "provider": "serpapi"},
        url="https://www.nike.com/t/air-force-1-low",
        domain="nike.com",
    )
    result = score_candidate(source=source, candidate=candidate, source_type="brand_dtc")

    assert result["reasons"]["model_token_match"] is False
    assert result["score"] < 0.82


@pytest.mark.component
def test_score_candidate_truncated_candidate_does_not_self_promote() -> None:
    # Directional containment: a truncated generic candidate must not match a more specific
    # source even when they share a family token.
    source = {"title": "Samsung Galaxy S24 Ultra 512GB", "brand": "Samsung"}
    candidate = {"title": "Samsung Galaxy", "brand": "Samsung"}
    result = score_candidate(source=source, candidate=candidate, source_type=SOURCE_TYPE_BRAND_DTC)

    assert result["reasons"]["model_token_match"] is False
    assert result["score"] < 0.82


@pytest.mark.component
def test_score_candidate_brand_resolved_from_candidate_evidence() -> None:
    # Brand not in the registry, but the candidate title states it: matching must still fire
    # via candidate-side evidence (registry only canonicalizes; it does not gate).
    source = {"title": "Northbound Trail Daypack 25L", "brand": "Northbound", "price": 80.0}
    candidate = {
        "title": "Northbound Trail Daypack 25L Olive",
        "brand": "",
        "price": 79.0,
        "description": "Northbound Trail Daypack",
    }
    result = score_candidate(source=source, candidate=candidate, source_type="retailer")

    assert result["reasons"]["brand_match"] is True
    assert result["reasons"].get("brand_from_candidate_evidence") is True


@pytest.mark.component
def test_candidate_dedupe_key_collapses_size_and_color_variants() -> None:
    from app.services.product_intelligence.candidate_urls import candidate_dedupe_key

    key_a = candidate_dedupe_key(
        "https://www.dsw.com/product/x/582039?size=10&width=Medium&cm_mmc=CSE"
    )
    key_b = candidate_dedupe_key(
        "https://www.dsw.com/product/x/582039?size=13&activeColor=002"
    )
    assert key_a == key_b
    # Identity-bearing params are preserved, so genuinely different products stay distinct.
    key_c = candidate_dedupe_key(
        "https://www.lyst.com/shoes/x/?product=SEECFLM&size=10"
    )
    key_d = candidate_dedupe_key(
        "https://www.lyst.com/shoes/x/?product=OTHER&size=11"
    )
    assert key_c != key_d


@pytest.mark.component
def test_build_search_queries_uses_decomposed_style_core_not_composite_sku() -> None:
    # Without a GTIN, the appended identifier must be the bare manufacturer code (FV5285),
    # never the composite Belk SKU (3900462FV5285) which no external retailer indexes.
    queries = build_search_queries(
        {"title": "Men's Promina Sneakers", "brand": "Nike", "sku": "3900462FV5285"},
        source_domain_value="belk.com",
    )
    joined = " | ".join(queries).lower()
    assert "fv5285" in joined
    assert "3900462fv5285" not in joined
