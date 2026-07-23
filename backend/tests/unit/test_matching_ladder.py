"""Focused behavioral tests for the intelligence matching ladder (audit 4.11).

Pure-function coverage of ``app/intelligence/matching.py`` — no database:

- ``score_candidate`` identity-ladder order and short-circuits
  (GTIN > style-code > brand-DTC > brand+strong-title > brand+model-token
  > brand+medium-title), including the wrong-variant cap that fires last.
- The GTIN gate: ``_gtin_match`` key families plus the config-backed
  title-similarity gate (``MATCH_GTIN_MIN_TITLE_SIM``).
- ``_apply_identity_floor`` as a decision table (each rung + fall-through).
- ``score_label`` cutoffs (config constants), ``is_private_label`` exclusion,
  ``_style_code_match``, and brand inference (``_infer_brand`` /
  ``_infer_known_brand``).
"""

from __future__ import annotations

import pytest

from app.core.config import product_intelligence as config
from app.intelligence import matching

pytestmark = pytest.mark.unit


def _snapshot(
    title: str,
    brand: str = "",
    *,
    gtin: str = "",
    style_code: str = "",
    price: object = None,
    url: str = "",
) -> dict[str, object]:
    return {
        "title": title,
        "brand": brand,
        "normalized_brand": matching.normalize_brand(brand),
        "gtin": gtin,
        "style_code": style_code,
        "price": price,
        "url": url,
    }


def _floor_reasons(
    *,
    brand: bool = False,
    gtin: bool = False,
    style: bool = False,
    model: bool = False,
    price: bool = False,
    variant: bool = False,
) -> dict[str, object]:
    return {
        "brand_match": brand,
        "gtin_match": gtin,
        "style_code_match": style,
        "model_token_match": model,
        "price_band_match": price,
        "variant_mismatch": variant,
    }


def _apply(
    score: float,
    reasons: dict[str, object],
    *,
    source_type: str = "retailer",
    title_similarity: float = 0.0,
) -> tuple[float, dict[str, object]]:
    return matching._apply_identity_floor(
        score=score,
        reasons=reasons,
        source_type=source_type,
        title_similarity=title_similarity,
    )


# ---------------------------------------------------------------------------
# score_candidate: ladder order + short-circuits
# ---------------------------------------------------------------------------


def test_ladder_gtin_rung_wins_and_short_circuits_style_code() -> None:
    # Both GTIN and style-code signals present: the higher GTIN rung must win.
    source = _snapshot(
        "Nike Promina Men's Walking Shoes",
        "Nike",
        gtin="0123456789012",
        style_code="fv5285",
    )
    candidate = _snapshot(
        "Nike Promina Men's Walking Shoes",
        "Nike",
        gtin="0123456789012",
        style_code="fv5285",
    )
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type="retailer"
    )
    assert result["reasons"]["gtin_match"] is True
    assert result["reasons"]["style_code_match"] is True
    assert result["reasons"]["match_basis"] == config.MATCH_BASIS_GTIN
    # Additive signals saturate: title 0.45 + brand 0.25 + gtin 0.25 + style
    # 0.25 + retailer authority 0.10 > 1.0, clamped at 1.0.
    assert result["score"] == 1.0
    assert result["label"] == config.DEFAULT_SCORE_LABEL_HIGH


def test_ladder_gtin_rung_blocked_below_config_title_sim_gate() -> None:
    source = _snapshot(
        "Nike Promina Men's Walking Shoes", "Nike", gtin="0123456789012"
    )
    candidate = _snapshot(
        "qzwx kv jytrx bnmp fdgs", "Nike", gtin="0123456789012"
    )
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type="retailer"
    )
    assert result["reasons"]["gtin_match"] is True
    assert result["reasons"]["brand_match"] is True
    assert result["reasons"]["title_similarity"] < config.MATCH_GTIN_MIN_TITLE_SIM
    # The GTIN floor must NOT apply: falls through every rung to title-only.
    assert result["reasons"]["match_basis"] == config.MATCH_BASIS_TITLE
    assert result["score"] < config.MATCH_SCORE_FLOOR_GTIN


def test_ladder_style_code_rung_with_brand() -> None:
    source = _snapshot("Nike Promina Sneakers", "Nike", style_code="fv5285")
    candidate = _snapshot(
        "Nike Promina Shoes FV5285-002", "Nike", style_code="fv5285"
    )
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type="retailer"
    )
    assert result["reasons"]["gtin_match"] is False
    assert result["reasons"]["match_basis"] == config.MATCH_BASIS_STYLE_CODE
    assert result["score"] >= config.MATCH_SCORE_FLOOR_STYLE_CODE


def test_ladder_style_code_rung_without_brand_uses_lower_floor() -> None:
    source = _snapshot("Promina sneaker listing", style_code="fv5285")
    candidate = _snapshot("xyzz qkv wndrng", style_code="fv5285")
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type="retailer"
    )
    assert result["reasons"]["brand_match"] is False
    assert result["reasons"]["match_basis"] == config.MATCH_BASIS_STYLE_CODE
    assert config.MATCH_SCORE_FLOOR_STYLE_CODE_NO_BRAND <= result["score"] < (
        config.MATCH_SCORE_FLOOR_STYLE_CODE
    )


def test_ladder_brand_dtc_rung_beats_brand_title() -> None:
    # Identical brand+titles would also satisfy the brand+title rung; the DTC
    # rung sits higher on the ladder and must win for the brand's own listing.
    source = _snapshot("Nike Promina Men's Walking Shoes", "Nike")
    candidate = _snapshot("Nike Promina Men's Walking Shoes", "Nike")
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type=config.SOURCE_TYPE_BRAND_DTC
    )
    assert result["reasons"]["match_basis"] == config.MATCH_BASIS_BRAND_DTC
    # Additive: title 0.45 + brand 0.25 + DTC authority 0.18 = 0.88 -> floored.
    assert result["score"] == pytest.approx(config.MATCH_SCORE_FLOOR_BRAND_DTC)


def test_ladder_brand_dtc_rung_blocked_below_dtc_title_sim_gate() -> None:
    source = _snapshot("Nike Promina Men's Walking Shoes", "Nike")
    candidate = _snapshot("Nike qzwx kv jytrx bnmp", "Nike")
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type=config.SOURCE_TYPE_BRAND_DTC
    )
    assert result["reasons"]["title_similarity"] < config.MATCH_DTC_MIN_TITLE_SIM
    assert result["reasons"]["match_basis"] != config.MATCH_BASIS_BRAND_DTC


def test_ladder_brand_title_high_rung_with_price_band() -> None:
    source = _snapshot("Nike Promina Men's Walking Shoes", "Nike", price=100.0)
    candidate = _snapshot("Nike Promina Men's Walking Shoes", "Nike", price=102.0)
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type="retailer"
    )
    assert result["reasons"]["price_band_match"] is True
    assert result["reasons"]["match_basis"] == config.MATCH_BASIS_BRAND_TITLE
    # Additive 0.45 + 0.25 + 0.05 + 0.10 = 0.85 -> raised to the price floor.
    assert result["score"] == pytest.approx(
        config.MATCH_SCORE_FLOOR_BRAND_TITLE_PRICE_HIGH
    )


def test_ladder_brand_title_high_rung_without_price_band() -> None:
    source = _snapshot("Nike Promina Men's Walking Shoes", "Nike")
    candidate = _snapshot("Nike Promina Men's Walking Shoes", "Nike")
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type="retailer"
    )
    assert result["reasons"]["price_band_match"] is False
    assert result["reasons"]["match_basis"] == config.MATCH_BASIS_BRAND_TITLE
    # Additive 0.45 + 0.25 + 0.10 = 0.80 -> raised to the no-price floor.
    assert result["score"] == pytest.approx(config.MATCH_SCORE_FLOOR_BRAND_TITLE_HIGH)


def test_ladder_model_brand_rung_for_terse_source_title() -> None:
    # Terse source vs verbose retailer title: low raw title similarity, but the
    # shared distinctive model token ("promina") carries the match.
    source = _snapshot("Men's Promina Sneakers", "Nike")
    candidate = _snapshot("Nike Promina Men's Walking Shoes Extra Wide", "Nike")
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type="retailer"
    )
    assert result["reasons"]["model_token_match"] is True
    assert result["reasons"]["title_similarity"] < config.MATCH_TITLE_SIM_MEDIUM
    assert result["reasons"]["match_basis"] == config.MATCH_BASIS_MODEL_BRAND
    assert result["score"] == pytest.approx(config.MATCH_SCORE_FLOOR_MODEL_BRAND)


def test_ladder_falls_through_to_title_basis_without_identity_signals() -> None:
    source = _snapshot("Nike Promina Men's Walking Shoes", "Nike")
    candidate = _snapshot("Adidas Ultraboost Light Running", "Adidas")
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type="retailer"
    )
    assert result["reasons"]["brand_match"] is False
    assert result["reasons"]["identifier_match"] is False
    assert result["reasons"]["match_basis"] == config.MATCH_BASIS_TITLE
    assert result["score"] < config.MATCH_SCORE_FLOOR_BRAND_TITLE_MEDIUM


def test_ladder_variant_mismatch_cap_fires_after_floors() -> None:
    # GTIN+brand+strong title would floor at 0.92, but the explicit variant
    # spec mismatch (8 oz vs 16 oz) caps the final score below auto-accept.
    source = _snapshot("Nike Water Bottle 8 oz", "Nike", gtin="0123456789012")
    candidate = _snapshot("Nike Water Bottle 16 oz", "Nike", gtin="0123456789012")
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type="retailer"
    )
    assert result["reasons"]["variant_mismatch"] is True
    assert result["reasons"]["match_basis"] == config.MATCH_BASIS_GTIN
    assert result["score"] == pytest.approx(config.MATCH_VARIANT_MISMATCH_SCORE_CAP)


def test_score_candidate_infers_candidate_brand_from_evidence() -> None:
    source = _snapshot("Nike Promina Shoes", "Nike")
    candidate = _snapshot("Nike Promina Shoes", "")
    result = matching.score_candidate(
        source=source, candidate=candidate, source_type="retailer"
    )
    assert result["reasons"]["brand_from_candidate_evidence"] is True
    assert result["reasons"]["brand_match"] is True


# ---------------------------------------------------------------------------
# _apply_identity_floor as a decision table
# ---------------------------------------------------------------------------


def test_identity_floor_gtin_rung_requires_brand_and_title_sim() -> None:
    score, reasons = _apply(
        0.10,
        _floor_reasons(gtin=True, brand=True),
        title_similarity=config.MATCH_GTIN_MIN_TITLE_SIM,
    )
    assert score == pytest.approx(config.MATCH_SCORE_FLOOR_GTIN)
    assert reasons["match_basis"] == config.MATCH_BASIS_GTIN

    score, reasons = _apply(
        0.10,
        _floor_reasons(gtin=True, brand=True),
        title_similarity=config.MATCH_GTIN_MIN_TITLE_SIM - 1e-9,
    )
    assert score == pytest.approx(0.10)
    assert reasons["match_basis"] == config.MATCH_BASIS_TITLE

    # GTIN without a brand match cannot floor either.
    score, reasons = _apply(
        0.10,
        _floor_reasons(gtin=True),
        title_similarity=1.0,
    )
    assert score == pytest.approx(0.10)
    assert reasons["match_basis"] == config.MATCH_BASIS_TITLE


def test_identity_floor_gtin_rung_short_circuits_lower_rungs() -> None:
    score, reasons = _apply(
        0.10,
        _floor_reasons(gtin=True, brand=True, style=True, model=True, price=True),
        source_type=config.SOURCE_TYPE_BRAND_DTC,
        title_similarity=1.0,
    )
    assert reasons["match_basis"] == config.MATCH_BASIS_GTIN
    assert score == pytest.approx(config.MATCH_SCORE_FLOOR_GTIN)


def test_identity_floor_style_rung_brand_selects_floor() -> None:
    score, reasons = _apply(
        0.10, _floor_reasons(style=True, brand=True), title_similarity=0.10
    )
    assert score == pytest.approx(config.MATCH_SCORE_FLOOR_STYLE_CODE)
    assert reasons["match_basis"] == config.MATCH_BASIS_STYLE_CODE

    score, reasons = _apply(
        0.10, _floor_reasons(style=True), title_similarity=0.10
    )
    assert score == pytest.approx(config.MATCH_SCORE_FLOOR_STYLE_CODE_NO_BRAND)
    assert reasons["match_basis"] == config.MATCH_BASIS_STYLE_CODE


def test_identity_floor_style_rung_skipped_on_variant_mismatch() -> None:
    score, reasons = _apply(
        0.10,
        _floor_reasons(style=True, brand=True, variant=True),
        title_similarity=0.95,
    )
    # Style/high/model/medium rungs are all variant-gated: no floor applies,
    # and the cap leaves an already-low score untouched (never lifts).
    assert score == pytest.approx(0.10)
    assert reasons["match_basis"] == config.MATCH_BASIS_TITLE


def test_identity_floor_dtc_rung() -> None:
    score, reasons = _apply(
        0.10,
        _floor_reasons(brand=True),
        source_type=config.SOURCE_TYPE_BRAND_DTC,
        title_similarity=config.MATCH_DTC_MIN_TITLE_SIM,
    )
    assert score == pytest.approx(config.MATCH_SCORE_FLOOR_BRAND_DTC)
    assert reasons["match_basis"] == config.MATCH_BASIS_BRAND_DTC

    # A retailer (non-DTC) candidate with the same signals must not take it.
    score, reasons = _apply(
        0.10,
        _floor_reasons(brand=True),
        source_type="retailer",
        title_similarity=config.MATCH_DTC_MIN_TITLE_SIM,
    )
    assert reasons["match_basis"] != config.MATCH_BASIS_BRAND_DTC
    assert score < config.MATCH_SCORE_FLOOR_BRAND_DTC


def test_identity_floor_brand_title_high_rung_price_selects_floor() -> None:
    score, reasons = _apply(
        0.10,
        _floor_reasons(brand=True, price=True),
        title_similarity=config.MATCH_TITLE_SIM_HIGH,
    )
    assert score == pytest.approx(config.MATCH_SCORE_FLOOR_BRAND_TITLE_PRICE_HIGH)
    assert reasons["match_basis"] == config.MATCH_BASIS_BRAND_TITLE

    score, reasons = _apply(
        0.10,
        _floor_reasons(brand=True),
        title_similarity=config.MATCH_TITLE_SIM_HIGH,
    )
    assert score == pytest.approx(config.MATCH_SCORE_FLOOR_BRAND_TITLE_HIGH)
    assert reasons["match_basis"] == config.MATCH_BASIS_BRAND_TITLE


def test_identity_floor_model_brand_rung() -> None:
    score, reasons = _apply(
        0.10,
        _floor_reasons(brand=True, model=True),
        title_similarity=0.30,
    )
    assert score == pytest.approx(config.MATCH_SCORE_FLOOR_MODEL_BRAND)
    assert reasons["match_basis"] == config.MATCH_BASIS_MODEL_BRAND


def test_identity_floor_medium_rung_is_last() -> None:
    score, reasons = _apply(
        0.10,
        _floor_reasons(brand=True),
        title_similarity=config.MATCH_TITLE_SIM_MEDIUM,
    )
    assert score == pytest.approx(config.MATCH_SCORE_FLOOR_BRAND_TITLE_MEDIUM)
    assert reasons["match_basis"] == config.MATCH_BASIS_BRAND_TITLE


def test_identity_floor_no_rung_leaves_score_and_basis_title() -> None:
    score, reasons = _apply(0.33, _floor_reasons(), title_similarity=0.50)
    assert score == pytest.approx(0.33)
    assert reasons["match_basis"] == config.MATCH_BASIS_TITLE


def test_identity_floor_never_lowers_an_already_high_score() -> None:
    score, reasons = _apply(
        0.99,
        _floor_reasons(brand=True),
        title_similarity=config.MATCH_TITLE_SIM_MEDIUM,
    )
    assert score == pytest.approx(0.99)
    assert reasons["match_basis"] == config.MATCH_BASIS_BRAND_TITLE


def test_identity_floor_variant_cap_fires_last_and_never_lifts() -> None:
    # Cap clamps a floored score...
    score, reasons = _apply(
        0.10,
        _floor_reasons(gtin=True, brand=True, variant=True),
        title_similarity=1.0,
    )
    assert score == pytest.approx(config.MATCH_VARIANT_MISMATCH_SCORE_CAP)
    assert reasons["match_basis"] == config.MATCH_BASIS_GTIN

    # ...but a score already below the cap stays put.
    score, _ = _apply(
        0.50,
        _floor_reasons(brand=True, variant=True),
        title_similarity=0.10,
    )
    assert score == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# GTIN gate
# ---------------------------------------------------------------------------


def test_gtin_match_across_key_families_and_formats() -> None:
    assert matching._gtin_match({"gtin": "00123"}, {"upc": "00123"}) is True
    assert matching._gtin_match({"barcode": "123"}, {"ean": "123"}) is True
    assert matching._gtin_match({"gtin": "0123-456"}, {"gtin": "0123 456"}) is True
    assert matching._gtin_match({"gtin": "ABC123"}, {"sku_upc": "abc123"}) is True


def test_gtin_match_rejects_missing_or_disjoint_values() -> None:
    assert matching._gtin_match({"gtin": "00123"}, {}) is False
    assert matching._gtin_match({}, {"gtin": "00123"}) is False
    assert matching._gtin_match({}, {}) is False
    assert matching._gtin_match({"gtin": "00123"}, {"gtin": "00456"}) is False


# ---------------------------------------------------------------------------
# score_label cutoffs (config constants)
# ---------------------------------------------------------------------------


def test_score_label_cutoffs_follow_config_constants() -> None:
    epsilon = 1e-9
    assert matching.score_label(config.SCORE_LABEL_HIGH_CUTOFF) == (
        config.DEFAULT_SCORE_LABEL_HIGH
    )
    assert matching.score_label(config.SCORE_LABEL_HIGH_CUTOFF - epsilon) == (
        config.DEFAULT_SCORE_LABEL_MEDIUM
    )
    assert matching.score_label(config.SCORE_LABEL_MEDIUM_CUTOFF) == (
        config.DEFAULT_SCORE_LABEL_MEDIUM
    )
    assert matching.score_label(config.SCORE_LABEL_MEDIUM_CUTOFF - epsilon) == (
        config.DEFAULT_SCORE_LABEL_LOW
    )
    assert matching.score_label(config.SCORE_LABEL_LOW_CUTOFF) == (
        config.DEFAULT_SCORE_LABEL_LOW
    )
    assert matching.score_label(config.SCORE_LABEL_LOW_CUTOFF - epsilon) == (
        config.DEFAULT_SCORE_LABEL_UNCERTAIN
    )
    assert matching.score_label(0.0) == config.DEFAULT_SCORE_LABEL_UNCERTAIN
    assert matching.score_label(1.0) == config.DEFAULT_SCORE_LABEL_HIGH


# ---------------------------------------------------------------------------
# is_private_label exclusion
# ---------------------------------------------------------------------------


def test_is_private_label_recognizes_private_labels_through_normalization() -> None:
    assert matching.is_private_label("Belk") is True
    assert matching.is_private_label(" belk ") is True
    assert matching.is_private_label("KAARI BLUE") is True
    assert matching.is_private_label("New-Directions") is True


def test_is_private_label_recognizes_belk_exclusive_registry_brands() -> None:
    assert matching.is_private_label("Crown & Ivy") is True
    assert matching.is_private_label("Belk & Co") is True


def test_is_private_label_excludes_national_and_empty_brands() -> None:
    assert matching.is_private_label("Nike") is False
    assert matching.is_private_label("Levi's") is False
    assert matching.is_private_label("") is False
    assert matching.is_private_label(None) is False


# ---------------------------------------------------------------------------
# Style codes
# ---------------------------------------------------------------------------


def test_style_code_match_intersects_code_sets() -> None:
    assert (
        matching._style_code_match({"style_code": "fv5285"}, {"style_code": "fv5285"})
        is True
    )
    assert (
        matching._style_code_match(
            {"style_code": "aa12345 bb67890"}, {"style_code": "bb67890"}
        )
        is True
    )


def test_style_code_match_rejects_disjoint_or_missing_codes() -> None:
    assert (
        matching._style_code_match({"style_code": "fv5285"}, {"style_code": "dm8968"})
        is False
    )
    assert matching._style_code_match({"style_code": "fv5285"}, {}) is False
    assert matching._style_code_match({}, {"style_code": "fv5285"}) is False
    assert matching._style_code_match({"style_code": ""}, {"style_code": ""}) is False


def test_manufacturer_style_code_strips_retailer_prefix_and_colorway() -> None:
    assert matching.manufacturer_style_code("3900462FV5285") == "fv5285"
    assert matching.manufacturer_style_code("FV5285-002") == "fv5285"
    # Codes shorter than the config minimum never match.
    assert matching.manufacturer_style_code("ab12") == ""
    # Multiple codes reduce to a sorted, space-joined set.
    assert matching.manufacturer_style_code("FV5285 and DM8968") == "dm8968 fv5285"


# ---------------------------------------------------------------------------
# Brand inference
# ---------------------------------------------------------------------------


def test_normalize_brand_applies_alias_map() -> None:
    assert matching.normalize_brand("LEVI'S") == "levi's"
    assert matching.normalize_brand("levis") == "levi's"
    assert matching.normalize_brand("Nike") == "nike"
    assert matching.normalize_brand(None) == ""


def test_infer_known_brand_matches_aliases_in_free_text() -> None:
    assert matching._infer_known_brand("nike running shoes promo") == "nike"
    assert matching._infer_known_brand("Levi's 511 Slim Fit Jeans") == "levi's"
    assert matching._infer_known_brand("qzwx kv jytrx bnmp") == ""
    assert matching._infer_known_brand() == ""


def test_infer_brand_prefers_known_brands_in_url_or_title() -> None:
    # The brand token comes from the URL slug, not the title.
    brand = matching._infer_brand(
        source_url="https://www.levi.com/p/levis-511", title="511 Slim Fit Jeans"
    )
    assert matching.normalize_brand(brand) == "levi's"


def test_infer_brand_falls_back_to_title_marker() -> None:
    brand = matching._infer_brand(source_url="", title="™Novesta Star Runner")
    assert brand.endswith("Novesta")


def test_infer_brand_returns_empty_without_any_signal() -> None:
    assert matching._infer_brand(source_url="", title="") == ""
    assert (
        matching._infer_brand(source_url="https://example.com/", title="qzwx kv")
        == ""
    )


def test_host_is_belk_scopes_to_belk_domains_only() -> None:
    assert matching._host_is_belk("belk.com") is True
    assert matching._host_is_belk("www.belk.com") is True
    assert matching._host_is_belk("https://www.belk.com/p/x") is True
    assert matching._host_is_belk("sub.belk.com") is True
    assert matching._host_is_belk("belk.com.evil.example") is False
    assert matching._host_is_belk("notbelk.com") is False
    assert matching._host_is_belk("") is False


def test_canonical_source_brand_upgrades_inferable_brand() -> None:
    # A weak merchant label is replaced by a domain-mapped brand inferred from
    # the listing evidence.
    upgraded = matching._canonical_source_brand(
        "unknown merchant",
        source_url="https://www.nike.com/t/promina-shoe",
        title="Nike Promina Shoes",
    )
    assert matching.normalize_brand(upgraded) == "nike"

    # Already domain-mapped brands pass through untouched.
    assert (
        matching._canonical_source_brand(
            "Nike", source_url="https://example.com/x", title="Some Shoes"
        )
        == "Nike"
    )

    # Nothing inferable: keep the original label.
    assert (
        matching._canonical_source_brand(
            "qzwx merchant", source_url="https://example.com/x", title="kv jytrx"
        )
        == "qzwx merchant"
    )


def test_extract_product_snapshot_derives_canonical_fields() -> None:
    snapshot = matching.extract_product_snapshot(
        {
            "title": "Nike Promina Shoes",
            "brand": "Nike",
            "url": "https://www.nike.com/t/promina",
            "price": "$120.00",
            "gtin": "0123456789012",
            "sku": "FV5285-002",
        }
    )
    assert snapshot["title"] == "Nike Promina Shoes"
    assert snapshot["normalized_brand"] == "nike"
    assert snapshot["price"] == pytest.approx(120.0)
    assert snapshot["currency"] == "USD"
    assert snapshot["gtin"] == "0123456789012"
    assert snapshot["style_code"] == "fv5285"
    assert matching.extract_product_snapshot(None)["title"] == ""
