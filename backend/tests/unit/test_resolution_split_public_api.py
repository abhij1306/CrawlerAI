"""Guard tests for the extraction/resolution package split (audit 4.1).

``extraction/resolution/__init__.py`` was a 2,044-LOC god-package. It is now
split by concern into sibling submodules, with ``__init__.py`` as a pure
re-export facade. These tests pin the pre-split public surface so every
existing ``from app.extraction.resolution import ...`` importer keeps working
unchanged.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

# Recorded from ``dir(app.extraction.resolution)`` immediately before the
# split (names starting with ``__`` excluded). Must stay identical.
_PRE_SPLIT_PUBLIC_NAMES = frozenset(
    {
        "AVAILABILITY_PARENT_ROLLUP_PRECEDENCE",
        "AssetDecision",
        "AssetEntity",
        "CURRENCY_SYMBOL_TO_ISO",
        "DEFAULT_VARIANT_DIAGNOSTIC_REASON",
        "DEFAULT_VARIANT_PLACEHOLDER_FLAG",
        "DETAIL_PARENT_INHERITED_OFFER_FIELDS",
        "DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID",
        "DETAIL_PARENT_VARIANT_PRICE_DRIFT_MAX_RATIO",
        "DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY",
        "DETAIL_TITLE_MEASUREMENT_FLAG",
        "DETAIL_TITLE_REJECTION_FLAGS",
        "Decimal",
        "Decision",
        "DerivedFact",
        "EntitySet",
        "Evidence",
        "Finding",
        "INVALID_AVAILABILITY_EVIDENCE_FLAG",
        "INVALID_SCALAR_TYPE_EVIDENCE_FLAG",
        "InvalidOperation",
        "Mapping",
        "OfferEntity",
        "PRODUCT_ASSET_IDENTITY_FACT_TYPES",
        "PUBLIC_VARIANT_AXIS_FIELDS",
        "RejectedEvidence",
        "ResolutionResult",
        "VARIANT_COLOR_BRAND_CONFLICT_FLAG",
        "VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO",
        "VARIANT_DOM_URL_AXIS_PARAM_PATTERN",
        "VARIANT_URL_AXIS_PARAMS",
        "VARIANT_URL_OPTION_ENDPOINT_PATH_TOKENS",
        "VariantDecision",
        "VariantEntity",
        "_GENERIC_INVALIDITY_FLAGS",
        "_aggregate_fact",
        "_aggregate_partial_variant_price",
        "_aggregate_variant_availability",
        "_aggregate_variant_field",
        "_asset_publication_facts",
        "_availability_from_stock_quantity",
        "_brand_from_title",
        "_currency_for_price",
        "_decision_lineage",
        "_derived",
        "_derived_fact",
        "_derived_lineage",
        "_drop_leaf_variant_prices_conflicting_parent",
        "_explicit_partial_child_is_publishable",
        "_has_parent_inherited_lineage",
        "_has_variant_option",
        "_inherit_variant_offer_facts",
        "_invalidity_reason",
        "_leaf_variant_decisions",
        "_lineage_evidence_ids",
        "_lineage_reference_ids",
        "_offer_atomic_price_currency_preferences",
        "_offer_atomic_unresolved_decision",
        "_offer_evidence_compatible",
        "_offer_rank",
        "_parent_derived_from_variants",
        "_preferred_parent_offer_id",
        "_price_scale_conflicts",
        "_price_unit_derived_facts",
        "_price_unit_repairs",
        "_put_decision_value",
        "_put_variant_offer",
        "_put_variant_options",
        "_rank",
        "_reconcile_variant_prices",
        "_resolve_asset",
        "_resolve_offer",
        "_resolve_scalar",
        "_resolve_variant",
        "_resolve_variants",
        "_resolved_product_url",
        "_resolved_value_and_lineage",
        "_resolved_variant_row",
        "_same_currency_variant_amount",
        "_semantic_derived_facts",
        "_single_variant_sku",
        "_url_mismatched_product_subjects",
        "_variant_decision",
        "_variant_rejection_reason",
        "_variant_url_conflicts",
        "_variant_url_is_option_endpoint",
        "accepted_asset_evidence",
        "annotations",
        "asset_rank",
        "assets",
        "conflicting_product_asset_urls",
        "currency_hint_from_page_url",
        "detail_style_code_from_url",
        "detail_title_from_url",
        "detail_url_resource_identity",
        "field_mappings",
        "infer_brand_from_marked_title_path",
        "infer_brand_from_page_identity",
        "infer_brand_from_product_url",
        "infer_brand_from_title_marker",
        "inherit_variant_id_from_sku",
        "invalid_primary_asset_evidence",
        "low_resolution_asset_urls",
        "non_positive_money",
        "normalize_asset_url",
        "parse_qsl",
        "price_units",
        "public_asset_delivery_url",
        "public_variant_row_is_sellable",
        "rank",
        "ranking",
        "re",
        "resolve",
        "resolve_product_assets",
        "sanitize_option_scalar",
        "semantic_identity_tokens",
        "slug_tokens",
        "stable_id",
        "urlsplit",
    }
)


def test_public_surface_is_identical_to_pre_split() -> None:
    import app.extraction.resolution as resolution

    names = {name for name in dir(resolution) if not name.startswith("__")}
    assert names == _PRE_SPLIT_PUBLIC_NAMES


def test_legacy_import_styles_still_work() -> None:
    # app/extraction/adapters.py and tests/unit/test_resolution_ranking.py
    # import exactly these names from the package root.
    from app.extraction.resolution import (  # noqa: F401
        _rank,
        _resolve_offer,
        _resolve_scalar,
        resolve,
    )


def test_facade_reexports_are_the_same_objects() -> None:
    import app.extraction.resolution as resolution
    from app.extraction.resolution import (
        decisions,
        derived,
        lineage,
        offers,
        resolver,
        variant_rollup,
        variants,
    )

    assert resolution.resolve is resolver.resolve
    assert resolution._resolve_scalar is decisions._resolve_scalar
    assert resolution._resolve_offer is offers._resolve_offer
    assert resolution._resolve_variants is variants._resolve_variants
    assert (
        resolution._reconcile_variant_prices is variant_rollup._reconcile_variant_prices
    )
    assert resolution._derived is derived._derived
    assert resolution._aggregate_fact is lineage._aggregate_fact
    assert resolution._rank is resolution.rank


def test_fresh_interpreter_import_works() -> None:
    subprocess.run(
        [sys.executable, "-c", "import app.extraction.resolution"],
        check=True,
        capture_output=True,
        text=True,
    )
