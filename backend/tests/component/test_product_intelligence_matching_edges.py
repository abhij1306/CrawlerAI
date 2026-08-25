from __future__ import annotations

# ruff: noqa: F403, F405
from .product_intelligence_test_support import *


@pytest.mark.component
def test_manufacturer_style_code_decomposes_composite_sku() -> None:
    from app.intelligence.matching import manufacturer_style_code

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
    result = score_candidate(
        source=source, candidate=candidate, source_type="marketplace"
    )

    assert result["reasons"]["style_code_match"] is True
    assert result["reasons"]["match_basis"] == "style_code"
    assert result["score"] >= 0.90
    assert result["label"] == "high"


@pytest.mark.component
def test_score_candidate_model_token_brand_is_model_level_match() -> None:
    # Terse source vs verbose candidate: raw title overlap is low, but brand-exact plus the
    # distinctive model token ("promina") is a deterministic model-level match.
    source = extract_product_snapshot(
        {
            "title": "Men's Promina Sneakers",
            "brand": "Nike\u00ae",
            "sku": "3900462FV5285",
        }
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
        {
            "title": "Men's Promina Sneakers",
            "brand": "Nike\u00ae",
            "sku": "3900462FV5285",
        }
    )
    candidate = extract_search_result_snapshot(
        {
            "title": "Nike Air Force 1 Low Men's Shoes",
            "source": "Nike",
            "provider": "serpapi",
        },
        url="https://www.nike.com/t/air-force-1-low",
        domain="nike.com",
    )
    result = score_candidate(
        source=source, candidate=candidate, source_type="brand_dtc"
    )

    assert result["reasons"]["model_token_match"] is False
    assert result["score"] < 0.82


@pytest.mark.component
def test_score_candidate_truncated_candidate_does_not_self_promote() -> None:
    # Directional containment: a truncated generic candidate must not match a more specific
    # source even when they share a family token.
    source = {"title": "Samsung Galaxy S24 Ultra 512GB", "brand": "Samsung"}
    candidate = {"title": "Samsung Galaxy", "brand": "Samsung"}
    result = score_candidate(
        source=source, candidate=candidate, source_type=SOURCE_TYPE_BRAND_DTC
    )

    assert result["reasons"]["model_token_match"] is False
    assert result["score"] < 0.82


@pytest.mark.component
def test_score_candidate_brand_resolved_from_candidate_evidence() -> None:
    # Brand not in the registry, but the candidate title states it: matching must still fire
    # via candidate-side evidence (registry only canonicalizes; it does not gate).
    source = {
        "title": "Northbound Trail Daypack 25L",
        "brand": "Northbound",
        "price": 80.0,
    }
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
    from app.intelligence.candidate_urls import candidate_dedupe_key

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
    key_d = candidate_dedupe_key("https://www.lyst.com/shoes/x/?product=OTHER&size=11")
    assert key_c != key_d


@pytest.mark.component
def test_build_search_queries_uses_decomposed_style_core_not_composite_sku() -> None:
    # Without a GTIN, the appended identifier must be the bare manufacturer code (FV5285),
    # never the composite Belk SKU (3900462FV5285) which no external retailer indexes.
    queries = build_search_queries(
        {"title": "Men's Promina Sneakers", "brand": "Nike", "sku": "3900462FV5285"},
    )
    joined = " | ".join(queries).lower()
    assert "fv5285" in joined
    assert "3900462fv5285" not in joined
