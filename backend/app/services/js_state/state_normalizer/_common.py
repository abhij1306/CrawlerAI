from __future__ import annotations
# ruff: noqa: F401,F403,F405

import logging
from typing import Any

from glom import glom  # type: ignore[import-untyped]

from app.services.config.js_state_field_specs import (
    JS_STATE_PRODUCT_PAYLOAD_LIMIT,
    JS_STATE_LIST_ITERATION_LIMIT,
    JS_STATE_OPTION_GROUP_VALUE_KEYS,
    JS_STATE_PRODUCT_FIELD_SPEC,
    JS_STATE_PRODUCT_OPTION_GROUP_KEYS,
    JS_STATE_PRODUCT_VARIANT_LIST_KEYS,
    JS_STATE_VARIANT_FIELD_SPEC,
    VARIANT_AXIS_KEYS,
)
from app.services.config.extraction_rules import (
    DETAIL_ARTIFACT_PRODUCT_TYPE_PATTERNS,
    DETAIL_ARTIFACT_PRODUCT_TYPE_VALUES,
    DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES,
    ECOMMERCE_DESCRIPTION_BLOCK_LIMIT,
)
from app.services.extraction_html_helpers import html_to_text
from app.services.field_policy import normalize_field_key
from app.services.dom.selector_engine import dedupe_image_urls, extract_feature_rows
from app.services.extract.variant_identity_merge import (
    merge_variant_rows,
    resolve_variants,
)
from app.services.extract.variant_axis import normalized_variant_axis_key
from app.services.shared.field_coerce import (
    clean_text,
    extract_urls,
    surface_alias_lookup,
    text_or_none,
)
from app.services.js_state.marketplace_choice_mapper import (
    extract_marketplace_choice_products,
)
from app.services.js_state.variant_options import (
    option_value_labels,
    variant_axis_value,
    variant_option_values,
    variant_selection_values,
)
from app.services.js_state.helpers import (
    availability_value,
    compact_dict,
    normalize_price,
    select_variant,
    stock_quantity,
    variant_attribute,
    variant_axes,
)
from app.services.js_state import job_mapper as _job_mapper
from app.services.platform_policy import JSStateExtractorConfig, platform_js_state_extractors

logger = logging.getLogger(__name__)
PRODUCT_FIELD_SPEC = JS_STATE_PRODUCT_FIELD_SPEC
_VARIANT_FIELD_SPEC = JS_STATE_VARIANT_FIELD_SPEC
map_configured_state_payload = _job_mapper.map_configured_state_payload
map_job_detail_state = _job_mapper.map_job_detail_state
path_value = _job_mapper.path_value
def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
as_list = _as_list

__all__ = [
    "DETAIL_ARTIFACT_PRODUCT_TYPE_PATTERNS",
    "DETAIL_ARTIFACT_PRODUCT_TYPE_VALUES",
    "DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES",
    "ECOMMERCE_DESCRIPTION_BLOCK_LIMIT",
    "JSStateExtractorConfig",
    "JS_STATE_LIST_ITERATION_LIMIT",
    "JS_STATE_OPTION_GROUP_VALUE_KEYS",
    "JS_STATE_PRODUCT_FIELD_SPEC",
    "JS_STATE_PRODUCT_OPTION_GROUP_KEYS",
    "JS_STATE_PRODUCT_PAYLOAD_LIMIT",
    "JS_STATE_PRODUCT_VARIANT_LIST_KEYS",
    "JS_STATE_VARIANT_FIELD_SPEC",
    "PRODUCT_FIELD_SPEC",
    "VARIANT_AXIS_KEYS",
    "availability_value",
    "clean_text",
    "compact_dict",
    "dedupe_image_urls",
    "extract_feature_rows",
    "extract_marketplace_choice_products",
    "extract_urls",
    "html_to_text",
    "map_configured_state_payload",
    "map_job_detail_state",
    "merge_variant_rows",
    "normalize_field_key",
    "normalize_price",
    "normalized_variant_axis_key",
    "option_value_labels",
    "platform_js_state_extractors",
    "path_value",
    "resolve_variants",
    "select_variant",
    "stock_quantity",
    "surface_alias_lookup",
    "text_or_none",
    "as_list",
    "variant_attribute",
    "variant_axes",
    "variant_axis_value",
    "variant_option_values",
    "variant_selection_values",
]
