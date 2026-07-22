"""Guard tests for audit 4.4: matching thresholds live in config, not code.

``intelligence/matching.py`` previously hardcoded the GTIN title-similarity
gate (0.45), the ``score_label`` cutoffs (0.85/0.60/0.40), and the
title-similarity expansion thresholds while sibling thresholds came from
``core/config/product_intelligence.py``. The constants now live in config;
these tests pin both the exact legacy values (behavior-identical) and the
wiring from ``matching.py`` to config.
"""

from __future__ import annotations

import pytest

from app.core.config import product_intelligence as config
from app.intelligence import matching

pytestmark = pytest.mark.unit


def test_config_constants_preserve_exact_legacy_values() -> None:
    assert config.MATCH_GTIN_MIN_TITLE_SIM == 0.45
    assert config.SCORE_LABEL_HIGH_CUTOFF == 0.85
    assert config.SCORE_LABEL_MEDIUM_CUTOFF == 0.60
    assert config.SCORE_LABEL_LOW_CUTOFF == 0.40
    assert config.TITLE_SIM_EXPANSION_MIN_CONTAINMENT == 0.85
    assert config.TITLE_SIM_EXPANSION_MIN_COVERAGE == 0.60
    assert config.TITLE_SIM_EXPANSION_MIN_OVERLAP_TOKENS == 3
    assert config.TITLE_SIM_EXPANSION_CONTAINMENT_WEIGHT == 0.80
    assert config.TITLE_SIM_EXPANSION_COVERAGE_WEIGHT == 0.20


def test_gtin_title_sim_gate_is_not_the_title_similarity_weight() -> None:
    # config/product_intelligence.py already carried 0.45 as the additive
    # title-similarity weight; the GTIN gate is a separate named constant with
    # the same numeric value but a different meaning (audit 4.4 warning).
    assert config.MATCH_SCORE_WEIGHTS["title_similarity"] == 0.45
    assert config.MATCH_GTIN_MIN_TITLE_SIM == 0.45


def test_matching_uses_config_constants() -> None:
    assert matching.MATCH_GTIN_MIN_TITLE_SIM == config.MATCH_GTIN_MIN_TITLE_SIM
    assert matching.SCORE_LABEL_HIGH_CUTOFF == config.SCORE_LABEL_HIGH_CUTOFF
    assert matching.SCORE_LABEL_MEDIUM_CUTOFF == config.SCORE_LABEL_MEDIUM_CUTOFF
    assert matching.SCORE_LABEL_LOW_CUTOFF == config.SCORE_LABEL_LOW_CUTOFF
    assert (
        matching.TITLE_SIM_EXPANSION_MIN_CONTAINMENT
        == config.TITLE_SIM_EXPANSION_MIN_CONTAINMENT
    )
    assert (
        matching.TITLE_SIM_EXPANSION_MIN_COVERAGE
        == config.TITLE_SIM_EXPANSION_MIN_COVERAGE
    )
    assert (
        matching.TITLE_SIM_EXPANSION_MIN_OVERLAP_TOKENS
        == config.TITLE_SIM_EXPANSION_MIN_OVERLAP_TOKENS
    )
    assert (
        matching.TITLE_SIM_EXPANSION_CONTAINMENT_WEIGHT
        == config.TITLE_SIM_EXPANSION_CONTAINMENT_WEIGHT
    )
    assert (
        matching.TITLE_SIM_EXPANSION_COVERAGE_WEIGHT
        == config.TITLE_SIM_EXPANSION_COVERAGE_WEIGHT
    )


def test_score_label_boundaries_follow_config_cutoffs() -> None:
    epsilon = 1e-9
    assert matching.score_label(config.SCORE_LABEL_HIGH_CUTOFF) == "high"
    assert matching.score_label(config.SCORE_LABEL_HIGH_CUTOFF - epsilon) == "medium"
    assert matching.score_label(config.SCORE_LABEL_MEDIUM_CUTOFF) == "medium"
    assert matching.score_label(config.SCORE_LABEL_MEDIUM_CUTOFF - epsilon) == "low"
    assert matching.score_label(config.SCORE_LABEL_LOW_CUTOFF) == "low"
    assert matching.score_label(config.SCORE_LABEL_LOW_CUTOFF - epsilon) == "uncertain"


def _snapshot(title: str, brand: str, gtin: str) -> dict[str, object]:
    return {
        "title": title,
        "brand": brand,
        "normalized_brand": matching.normalize_brand(brand),
        "gtin": gtin,
    }


def test_gtin_floor_requires_title_similarity_above_config_gate() -> None:
    source = _snapshot(
        "Nike Promina Men's Walking Shoes", "Nike", "0123456789012"
    )
    same_title = matching.score_candidate(
        source=source,
        candidate=_snapshot(
            "Nike Promina Men's Walking Shoes", "Nike", "0123456789012"
        ),
        source_type="retailer",
    )
    assert same_title["reasons"]["gtin_match"] is True
    assert same_title["reasons"]["brand_match"] is True
    assert same_title["reasons"]["title_similarity"] >= config.MATCH_GTIN_MIN_TITLE_SIM
    assert same_title["reasons"]["match_basis"] == config.MATCH_BASIS_GTIN
    assert same_title["score"] >= config.MATCH_SCORE_FLOOR_GTIN

    disjoint_title = matching.score_candidate(
        source=source,
        candidate=_snapshot("qzwx kv jytrx bnmp fdgs", "Nike", "0123456789012"),
        source_type="retailer",
    )
    assert disjoint_title["reasons"]["gtin_match"] is True
    assert disjoint_title["reasons"]["brand_match"] is True
    assert disjoint_title["reasons"]["title_similarity"] < config.MATCH_GTIN_MIN_TITLE_SIM
    assert disjoint_title["reasons"]["match_basis"] != config.MATCH_BASIS_GTIN
    assert disjoint_title["score"] < config.MATCH_SCORE_FLOOR_GTIN


def test_title_similarity_expansion_blend_uses_config_thresholds() -> None:
    # containment 4/4 = 1.0, larger_coverage 4/6 >= 0.60, 4 shared tokens >= 3:
    # the expansion blend fires.
    blended = matching._title_similarity(
        "men promina sneakers walking",
        "men promina sneakers walking shoes nike",
    )
    containment = 1.0
    larger_coverage = 4 / 6
    blend = (
        config.TITLE_SIM_EXPANSION_CONTAINMENT_WEIGHT * containment
        + config.TITLE_SIM_EXPANSION_COVERAGE_WEIGHT * larger_coverage
    )
    assert blended == pytest.approx(blend, abs=1e-9)

    # Below the minimum shared-token count the blend must not fire even with
    # full containment: falls back to plain overlap/sequence similarity.
    plain = matching._title_similarity(
        "men promina",
        "men promina sneakers walking shoes nike",
    )
    assert plain < blend
