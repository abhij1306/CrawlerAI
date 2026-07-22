"""Semantic authority for ecommerce-detail resolution (INVARIANTS §3/§17).

The package is split by concern into sibling submodules (``resolver``,
``decisions``, ``offers``, ``variants``, ``variant_rollup``, ``derived``,
``lineage``) alongside the existing ``ranking``/``price_units``/``assets``
modules. This facade re-exports the full pre-split public surface so every
existing ``from app.extraction.resolution import ...`` importer keeps working
unchanged.
"""

from __future__ import annotations

import re as re
from collections.abc import Mapping as Mapping
from decimal import Decimal as Decimal, InvalidOperation as InvalidOperation
from urllib.parse import parse_qsl as parse_qsl, urlsplit as urlsplit

from app.core.config import field_mappings as field_mappings
from app.core.config.extraction_price_rules import (
    DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY as DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY,
)
from app.core.config.extraction_rules import (
    AVAILABILITY_PARENT_ROLLUP_PRECEDENCE as AVAILABILITY_PARENT_ROLLUP_PRECEDENCE,
    DETAIL_TITLE_MEASUREMENT_FLAG as DETAIL_TITLE_MEASUREMENT_FLAG,
    DETAIL_TITLE_REJECTION_FLAGS as DETAIL_TITLE_REJECTION_FLAGS,
    INVALID_AVAILABILITY_EVIDENCE_FLAG as INVALID_AVAILABILITY_EVIDENCE_FLAG,
    PRODUCT_ASSET_IDENTITY_FACT_TYPES as PRODUCT_ASSET_IDENTITY_FACT_TYPES,
    VARIANT_COLOR_BRAND_CONFLICT_FLAG as VARIANT_COLOR_BRAND_CONFLICT_FLAG,
    VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO as VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO,
    VARIANT_DOM_URL_AXIS_PARAM_PATTERN as VARIANT_DOM_URL_AXIS_PARAM_PATTERN,
    VARIANT_URL_AXIS_PARAMS as VARIANT_URL_AXIS_PARAMS,
    VARIANT_URL_OPTION_ENDPOINT_PATH_TOKENS as VARIANT_URL_OPTION_ENDPOINT_PATH_TOKENS,
)
from app.core.config.locale_format_rules import (
    CURRENCY_SYMBOL_TO_ISO as CURRENCY_SYMBOL_TO_ISO,
    currency_hint_from_page_url as currency_hint_from_page_url,
)
from app.core.config.field_mappings import (
    INVALID_SCALAR_TYPE_EVIDENCE_FLAG as INVALID_SCALAR_TYPE_EVIDENCE_FLAG,
)
from app.core.config.variant_policy import (
    DEFAULT_VARIANT_DIAGNOSTIC_REASON as DEFAULT_VARIANT_DIAGNOSTIC_REASON,
    DEFAULT_VARIANT_PLACEHOLDER_FLAG as DEFAULT_VARIANT_PLACEHOLDER_FLAG,
    DETAIL_PARENT_INHERITED_OFFER_FIELDS as DETAIL_PARENT_INHERITED_OFFER_FIELDS,
    DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID as DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID,
    DETAIL_PARENT_VARIANT_PRICE_DRIFT_MAX_RATIO as DETAIL_PARENT_VARIANT_PRICE_DRIFT_MAX_RATIO,
    PUBLIC_VARIANT_AXIS_FIELDS as PUBLIC_VARIANT_AXIS_FIELDS,
    public_variant_row_is_sellable as public_variant_row_is_sellable,
)
from app.core.records.url_identity import (
    conflicting_product_asset_urls as conflicting_product_asset_urls,
    detail_style_code_from_url as detail_style_code_from_url,
    detail_title_from_url as detail_title_from_url,
    detail_url_resource_identity as detail_url_resource_identity,
    semantic_identity_tokens as semantic_identity_tokens,
)
from app.core.shared.field_coerce import (
    sanitize_option_scalar as sanitize_option_scalar,
)
from app.core.shared.field_coerce_text import (
    infer_brand_from_marked_title_path as infer_brand_from_marked_title_path,
    infer_brand_from_page_identity as infer_brand_from_page_identity,
    infer_brand_from_product_url as infer_brand_from_product_url,
    infer_brand_from_title_marker as infer_brand_from_title_marker,
)
from app.core.shared.ids import stable_id as stable_id
from app.core.shared.text_coerce import slug_tokens as slug_tokens
from app.core.shared.url_utils import (
    low_resolution_asset_urls as low_resolution_asset_urls,
    public_asset_delivery_url as public_asset_delivery_url,
)
from app.extraction.contracts import (
    AssetDecision as AssetDecision,
    Decision as Decision,
    DerivedFact as DerivedFact,
    Evidence as Evidence,
    Finding as Finding,
    RejectedEvidence as RejectedEvidence,
    ResolutionResult as ResolutionResult,
    VariantDecision as VariantDecision,
)
from app.extraction.entities import (
    AssetEntity as AssetEntity,
    EntitySet as EntitySet,
    OfferEntity as OfferEntity,
    VariantEntity as VariantEntity,
)
from app.extraction.resolution import (
    decisions as decisions,
    derived as derived,
    lineage as lineage,
    offers as offers,
    resolver as resolver,
    variant_rollup as variant_rollup,
    variants as variants,
)
from app.extraction.resolution.assets import (
    accepted_asset_evidence as accepted_asset_evidence,
    asset_rank as asset_rank,
    invalid_primary_asset_evidence as invalid_primary_asset_evidence,
    normalize_asset_url as normalize_asset_url,
    resolve_product_assets as resolve_product_assets,
)
from app.extraction.resolution.decisions import (
    _GENERIC_INVALIDITY_FLAGS as _GENERIC_INVALIDITY_FLAGS,
    _asset_publication_facts as _asset_publication_facts,
    _invalidity_reason as _invalidity_reason,
    _resolve_asset as _resolve_asset,
    _resolve_scalar as _resolve_scalar,
    _url_mismatched_product_subjects as _url_mismatched_product_subjects,
)
from app.extraction.resolution.derived import (
    _availability_from_stock_quantity as _availability_from_stock_quantity,
    _brand_from_title as _brand_from_title,
    _currency_for_price as _currency_for_price,
    _derived as _derived,
    _derived_fact as _derived_fact,
    _semantic_derived_facts as _semantic_derived_facts,
)
from app.extraction.resolution.lineage import (
    _aggregate_fact as _aggregate_fact,
    _decision_lineage as _decision_lineage,
    _derived_lineage as _derived_lineage,
    _has_parent_inherited_lineage as _has_parent_inherited_lineage,
    _lineage_evidence_ids as _lineage_evidence_ids,
    _lineage_reference_ids as _lineage_reference_ids,
    _put_decision_value as _put_decision_value,
    _resolved_product_url as _resolved_product_url,
    _resolved_value_and_lineage as _resolved_value_and_lineage,
)
from app.extraction.resolution.offers import (
    _offer_atomic_price_currency_preferences as _offer_atomic_price_currency_preferences,
    _offer_atomic_unresolved_decision as _offer_atomic_unresolved_decision,
    _offer_evidence_compatible as _offer_evidence_compatible,
    _offer_rank as _offer_rank,
    _preferred_parent_offer_id as _preferred_parent_offer_id,
    _resolve_offer as _resolve_offer,
)
from app.extraction.resolution.price_units import (
    _price_unit_derived_facts as _price_unit_derived_facts,
    _price_unit_repairs as _price_unit_repairs,
)
from app.extraction.resolution.ranking import (
    non_positive_money as non_positive_money,
    rank as rank,
)
from app.extraction.resolution.resolver import resolve as resolve
from app.extraction.resolution.variant_rollup import (
    _aggregate_partial_variant_price as _aggregate_partial_variant_price,
    _aggregate_variant_availability as _aggregate_variant_availability,
    _aggregate_variant_field as _aggregate_variant_field,
    _drop_leaf_variant_prices_conflicting_parent as _drop_leaf_variant_prices_conflicting_parent,
    _inherit_variant_offer_facts as _inherit_variant_offer_facts,
    _leaf_variant_decisions as _leaf_variant_decisions,
    _parent_derived_from_variants as _parent_derived_from_variants,
    _price_scale_conflicts as _price_scale_conflicts,
    _reconcile_variant_prices as _reconcile_variant_prices,
    _same_currency_variant_amount as _same_currency_variant_amount,
    _single_variant_sku as _single_variant_sku,
)
from app.extraction.resolution.variants import (
    _explicit_partial_child_is_publishable as _explicit_partial_child_is_publishable,
    _has_variant_option as _has_variant_option,
    _put_variant_offer as _put_variant_offer,
    _put_variant_options as _put_variant_options,
    _resolve_variant as _resolve_variant,
    _resolve_variants as _resolve_variants,
    _resolved_variant_row as _resolved_variant_row,
    _variant_decision as _variant_decision,
    _variant_rejection_reason as _variant_rejection_reason,
    _variant_url_conflicts as _variant_url_conflicts,
    _variant_url_is_option_endpoint as _variant_url_is_option_endpoint,
    inherit_variant_id_from_sku as inherit_variant_id_from_sku,
)

_rank = rank

# The split submodules are import-machinery details, not public surface:
# drop their auto-bound attributes so dir() stays identical to the pre-split
# package (``assets``/``price_units``/``ranking`` were already public).
del decisions, derived, lineage, offers, resolver, variant_rollup, variants
