from __future__ import annotations

# ruff: noqa: F403, F405
from .data_enrichment_test_support import *


@pytest.mark.regression
def test_plausible_size_value_accepts_known_numeric_system_before_strong_gate() -> None:
    assert plausible_size_value(
        "42",
        aliases={},
        systems={"numeric": {"42"}},
        require_strong=False,
    )


@pytest.mark.regression
def test_percentage_material_parse_trims_context_near_percentage() -> None:
    assert percentage_material_parse(
        "Made with cotton 60 percent and polyester 40%."
    ) == [
        "cotton",
        "polyester",
    ]


@pytest.mark.regression
def test_category_url_context_returns_none_for_malformed_input() -> None:
    assert category_url_context("http://[bad") is None


@pytest.mark.regression
def test_normalize_taxonomy_token_keeps_size_tokens_and_singularizes() -> None:
    assert normalize_taxonomy_token("s") == "s"
    assert normalize_taxonomy_token("m") == "m"
    assert normalize_taxonomy_token("l") == "l"
    assert normalize_taxonomy_token("handbags") == "bag"
    assert normalize_taxonomy_token("dresses") == "dress"


@pytest.mark.regression
def test_taxonomy_conflict_helpers_keep_accessory_and_sport_rules_explicit() -> None:
    assert accessory_path_conflict(
        "electronics > audio > audio accessories",
        {"headphone"},
    )
    assert not accessory_path_conflict(
        "electronics > audio > audio accessories",
        {"case"},
    )
    assert toys_vs_sports_conflict("toys & games > games", {"fitness"})
    assert not toys_vs_sports_conflict("toys & games > building toys", {"toy"})
    assert sport_specific_conflict({"soccer"}, {"basketball"})
    assert special_token_conflict({"ball"}, {"basketball"})
    assert taxonomy_candidate_conflicts(
        {"fitness"},
        "Toys & Games > Games",
    )


@pytest.mark.regression
def test_normalize_price_range_rejects_trailing_noise() -> None:
    assert normalize_price(
        {"price": "$10 - $20 each"},
        source_url="https://example.com/products/widget",
    ) == {"price_min": 10.0, "price_max": 20.0, "currency": "USD"}
    noisy = normalize_price(
        {"price": "$10 - $20 random words"},
        source_url="https://example.com/products/widget",
    )
    assert noisy == {"amount": 10.0, "currency": "USD"}


@pytest.mark.regression
def test_data_enrichment_variant_fit_does_not_become_size() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Cotton Trouser",
            "category": "Pants",
            "variants": [
                {
                    "size": "medium",
                    "fit": "regular fit",
                    "width": "wide",
                }
            ],
        },
        source_url="https://example.com/products/trouser",
    )

    assert enrichment["size_normalized"] == ["M"]


@pytest.mark.regression
def test_data_enrichment_category_uses_primary_category_before_title_noise() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "KitchenAid 13-cup food processor",
            "brand": "KitchenAid",
            "category": "Kitchen Appliances",
        },
        source_url="https://example.com/products/food-processor",
    )

    assert (
        enrichment["category_path"]
        == "Home & Garden > Kitchen & Dining > Kitchen Appliances"
    )
    assert "Cup Sleeves" not in str(enrichment["category_path"])


@pytest.mark.regression
def test_data_enrichment_exact_shopify_path_match_wins() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Navy Linen Midi Dress",
            "category": "Apparel & Accessories > Clothing > Dresses",
        },
        source_url="https://example.com/products/dress",
    )

    assert enrichment["category_path"] == "Apparel & Accessories > Clothing > Dresses"
    assert enrichment["_taxonomy_match"]["source"] == "exact_path"


@pytest.mark.regression
def test_data_enrichment_phrase_match_inputs_exclude_bulky_evidence_fields() -> None:
    values = category_match_values(
        {
            "title": "leather disco biker jacket",
            "category": "Men > Clothing > Leather Jackets",
            "description": "Short description says apparel accessory token.",
            "materials": "Lamb Skin/glass/Polyester/Spandex/Elastane/Polyester",
            "specifications": {"fit": "regular", "care": "professional clean only"},
        }
    )

    flattened = " ".join(str(value) for value in values)

    assert "leather disco biker jacket" in flattened
    assert "Men > Clothing > Leather Jackets" in flattened
    assert "Short description says apparel accessory token" not in flattened
    assert "Lamb Skin" not in flattened
    assert "professional clean only" not in flattened


@pytest.mark.regression
def test_data_enrichment_taxonomy_path_phrase_uses_index_lookup() -> None:
    row = {
        "category_id": "gid://shopify/TaxonomyCategory/aa-1-10-2",
        "category_path": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "attribute_handles": [],
    }
    taxonomy_index = TaxonomyIndex(
        version=DATA_ENRICHMENT_TAXONOMY_VERSION,
        categories=(),
        exact_lookup={},
        leaf_lookup={},
        path_phrase_lookup={"coats jackets": (row,)},
        id_lookup={},
    )

    match = shopify_catalog.phrase_path_category_match(
        "coats jackets",
        taxonomy_index,
        source_tokens={"leather", "coats", "jackets"},
    )

    assert match is not None
    assert match["category_path"] == row["category_path"]


@pytest.mark.regression
def test_data_enrichment_taxonomy_path_phrase_allows_token_subset_match() -> None:
    row = {
        "category_id": "gid://shopify/TaxonomyCategory/aa-1-10-2",
        "category_path": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "leaf": "Coats & Jackets",
        "path_match_tokens": {
            "apparel",
            "accessory",
            "clothing",
            "outerwear",
            "coat",
            "jacket",
        },
        "attribute_handles": [],
    }
    taxonomy_index = TaxonomyIndex(
        version=DATA_ENRICHMENT_TAXONOMY_VERSION,
        categories=(row,),
        exact_lookup={},
        leaf_lookup={},
        path_phrase_lookup={},
        id_lookup={},
    )

    match = shopify_catalog.phrase_path_category_match(
        "outerwear jacket",
        taxonomy_index,
        source_tokens={"leather", "outerwear", "jacket"},
    )

    assert match is not None
    assert match["category_path"] == row["category_path"]


@pytest.mark.regression
def test_data_enrichment_taxonomy_path_phrase_rejects_generic_subset_match() -> None:
    row = {
        "category_id": "gid://shopify/TaxonomyCategory/aa-1-10-2",
        "category_path": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "leaf": "Coats & Jackets",
        "path_match_tokens": {
            "apparel",
            "accessory",
            "clothing",
            "outerwear",
            "coat",
            "jacket",
        },
        "attribute_handles": [],
    }
    taxonomy_index = TaxonomyIndex(
        version=DATA_ENRICHMENT_TAXONOMY_VERSION,
        categories=(row,),
        exact_lookup={},
        leaf_lookup={},
        path_phrase_lookup={},
        id_lookup={},
    )

    match = shopify_catalog.phrase_path_category_match(
        "apparel clothing",
        taxonomy_index,
        source_tokens={"apparel", "clothing"},
    )

    assert match is None


@pytest.mark.regression
def test_data_enrichment_taxonomy_path_phrase_does_not_reject_valid_accessory_term() -> (
    None
):
    row = {
        "category_id": "gid://shopify/TaxonomyCategory/aa-1-10",
        "category_path": "Apparel & Accessories > Clothing Accessories",
        "path_match_tokens": {"apparel", "accessory", "clothing"},
        "attribute_handles": [],
    }
    taxonomy_index = TaxonomyIndex(
        version=DATA_ENRICHMENT_TAXONOMY_VERSION,
        categories=(row,),
        exact_lookup={},
        leaf_lookup={},
        path_phrase_lookup={"clothing accessory": (row,)},
        id_lookup={},
    )

    match = shopify_catalog.phrase_path_category_match(
        "clothing accessory",
        taxonomy_index,
        source_tokens={"clothing", "accessory"},
    )

    assert match is not None
    assert match["category_path"] == row["category_path"]


@pytest.mark.regression
def test_data_enrichment_color_aliases_cover_common_retail_names() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Wrap Dress",
            "category": "Dresses",
            "color": "Blush",
        },
        source_url="https://example.com/products/wrap-dress",
    )

    assert enrichment["color_family"] == "pink"


@pytest.mark.regression
def test_data_enrichment_context_only_tokens_exclude_product_terms() -> None:
    assert not {"s", "single", "star"} & set(
        DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS
    )


@pytest.mark.regression
def test_data_enrichment_color_aliases_do_not_mix_blue_green_intermediates() -> None:
    assert "teal" not in DATA_ENRICHMENT_COLOR_FAMILY_ALIASES["blue"]
    assert "turquoise" not in DATA_ENRICHMENT_COLOR_FAMILY_ALIASES["blue"]
    assert "teal" not in DATA_ENRICHMENT_COLOR_FAMILY_ALIASES["green"]


@pytest.mark.regression
def test_data_enrichment_size_split_handles_semicolon_and_middle_dot() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Running Shoe",
            "product_type": "Shoes",
            "size": "38; 40 · 42",
        },
        source_url="https://example.com/products/running-shoe",
    )

    assert enrichment["size_normalized"] == ["38", "40", "42"]
    assert enrichment["size_system"] == "numeric"


@pytest.mark.regression
def test_data_enrichment_price_infers_firstcry_currency() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Black Seascape Stretch Bracelet",
            "price": "868.21",
            "category": "Bracelets",
        },
        source_url="https://www.firstcry.com/example/product-detail",
    )

    assert enrichment["price_normalized"] == {"amount": 868.21, "currency": "INR"}


@pytest.mark.regression
def test_data_enrichment_seo_keywords_include_title_bigrams() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Black Seascape Stretch Bracelet",
            "price": "868.21",
            "category": "Bracelets",
        },
        source_url="https://www.firstcry.com/example/product-detail",
    )

    assert "black seascape" in set(enrichment["seo_keywords"] or [])


@pytest.mark.regression
def test_data_enrichment_seo_keywords_preserve_brand_phrase_and_dedupe_stems() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Running Run Jacket",
            "brand": "Calvin Klein",
            "category": "Jackets",
        },
        source_url="https://example.com/products/run-jacket",
    )

    keywords = set(enrichment["seo_keywords"] or [])
    assert "calvin klein" in keywords
    assert not {"running", "run"} <= keywords
