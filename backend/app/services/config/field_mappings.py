"""Static field mappings.

Alias consumers prefer exact canonical field keys before alias fallbacks.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.config._export_data import load_export_data

_EXPORTS_PATH = Path(__file__).with_name("field_mappings.exports.json")
_STATIC_EXPORTS = {
    name: value
    for name, value in load_export_data(str(_EXPORTS_PATH)).items()
    if not name.startswith("_")
}
locals().update(
    {
        name: value if value is not None else ()
        for name, value in _STATIC_EXPORTS.items()
    }
)
FIELD_ALIASES: dict[str, list[str]] = {
    str(name): list(values)
    for name, values in dict(_STATIC_EXPORTS.get("FIELD_ALIASES") or {}).items()
}
CANONICAL_SCHEMAS = {
    **dict(_STATIC_EXPORTS.get("CANONICAL_SCHEMAS") or {}),
    "design_system": [
        "title",
        "design_tokens",
        "source_urls",
        "generation_metadata",
        "url",
    ],
}
PROMPT_REGISTRY = {
    **dict(_STATIC_EXPORTS.get("PROMPT_REGISTRY") or {}),
    "design_system_markdown": {
        "response_type": "object",
        "system_file": "design_system_markdown.system.txt",
        "user_file": "design_system_markdown.user.txt",
    },
    "run_diagnosis": {
        "response_type": "object",
        "system_file": "run_diagnosis.system.txt",
        "user_file": "run_diagnosis.user.txt",
    },
}

COLOR_FIELD = "color"
TITLE_FIELD = "title"
SIZE_FIELD = "size"
WIDTH_FIELD = "width"
WEIGHT_FIELD = "weight"
PRICE_FIELD = "price"
CURRENCY_FIELD = "currency"
URL_FIELD = "url"
APPLY_URL_FIELD = "apply_url"
CANONICAL_URL_FIELD = "canonical_url"
IMAGE_URL_FIELD = "image_url"
ADDITIONAL_IMAGES_FIELD = "additional_images"
PRODUCT_ID_FIELD = "product_id"
AVAILABILITY_FIELD = "availability"
STOCK_QUANTITY_FIELD = "stock_quantity"
VARIANTS_FIELD = "variants"
AVAILABLE_SIZES_FIELD = "available_sizes"
VARIANT_AXES_FIELD = "variant_axes"
SELECTED_VARIANT_FIELD = "selected_variant"
BARCODE_FIELD = "barcode"
SKU_FIELD = "sku"
ROUTE_BARCODE_TO_SKU = True
NAVIGATION_URL_FIELDS = frozenset({URL_FIELD, APPLY_URL_FIELD, CANONICAL_URL_FIELD})
BRAND_LIKE_FIELDS = frozenset({"brand", "company", "dealer_name", "vendor"})
TITLE_STRUCTURED_VALUE_KEYS = (
    "values",
    "title",
    "name",
    "label",
    "text",
    "value",
)
PRICE_DICT_PREFERRED_KEYS = (
    "formattedPrice",
    "displayPrice",
    "price",
    "amount",
    "currentValue",
    "lowPrice",
    "minPrice",
    "minValue",
    "highPrice",
    "maxPrice",
    "maxValue",
    "value",
)
UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
NORMALIZER_LIST_TEXT_FIELDS = frozenset(
    {*_STATIC_EXPORTS.get("NORMALIZER_LIST_TEXT_FIELDS", ()), "features"}
)
ECOMMERCE_DETAIL_JS_STATE_PRIORITY_FIELDS = frozenset(
    field_name
    for field_name in _STATIC_EXPORTS.get("ECOMMERCE_DETAIL_JS_STATE_FIELDS", ())
    if field_name not in {PRODUCT_ID_FIELD, IMAGE_URL_FIELD, ADDITIONAL_IMAGES_FIELD}
)
VARIANT_AXIS_FIELD_NAMES = (
    COLOR_FIELD,
    SIZE_FIELD,
    "type",
    "switches",
    "fit",
    "style",
    "material",
    "finish",
    "pattern",
    "scent",
    "flavor",
    "capacity",
    "length",
    WIDTH_FIELD,
)
REQUESTED_FIELD_PREFIXES = ("product_", "item_", "job_")
HTML_SECTION_FIELDS = frozenset(
    {"responsibilities", "qualifications", "benefits", "skills"}
)
REQUESTED_FIELD_ALIAS_BASES = {
    "responsibilities": FIELD_ALIASES.get("responsibilities", []),
    "qualifications": FIELD_ALIASES.get("qualifications", []),
    "benefits": FIELD_ALIASES.get("benefits", []),
    "skills": FIELD_ALIASES.get("skills", []),
    "summary": FIELD_ALIASES.get("summary", []),
    "specifications": FIELD_ALIASES.get("specifications", []),
    "product_details": FIELD_ALIASES.get("product_details", []),
    "features": FIELD_ALIASES.get("features", []),
    "materials": FIELD_ALIASES.get("materials", []),
    "material": FIELD_ALIASES.get("materials", []),
    "care": FIELD_ALIASES.get("care", []),
    "dimensions": FIELD_ALIASES.get("dimensions", []),
    "remote": FIELD_ALIASES.get("remote", []),
    "requirements": FIELD_ALIASES.get("requirements", []),
    "country_of_origin": [
        "country of origin",
        "country_of_origin",
        "origin",
        "made in",
        "manufactured in",
        "importer",
        "importer_info",
        "importer name and address",
    ],
    "color_variants": FIELD_ALIASES.get("color_variants", []),
    "gender": FIELD_ALIASES.get("gender", []),
}
REQUESTED_FIELD_ALIAS_EXTRAS = {
    "responsibilities": (
        "job responsibilities",
        "key responsibilities",
        "job duties",
        "what you'll do",
        "what_you_ll_do",
        "what_you_will_do",
        "role responsibilities",
    ),
    "qualifications": (
        "job qualifications",
        "job_qualification",
        "should have",
        "you should have",
        "minimum requirements",
        "minimum_requirements",
        "preferred qualifications",
        "preferred_qualifications",
        "who you are",
        "what we're looking for",
    ),
    "benefits": (
        "job benefits",
        "perks",
        "why you'll love this job",
        "life at stripe",
        "what we offer",
    ),
    "skills": ("job skills", "job_skills", "experience", "what you'll bring"),
    "summary": ("description", "our opportunity", "about the role", "about the team"),
    "specifications": (
        "specs",
        "spec",
        "technical details",
        "tech specs",
        "the details",
    ),
    "product_details": ("product detail",),
    "features": ("key features",),
    "materials": ("fabrics", "material composition"),
    "material": ("fabrics", "material composition"),
    "care": ("care instructions", "washing instructions"),
}
_EXTRA_EXPORTS = [
    "AVAILABLE_SIZES_FIELD",
    "APPLY_URL_FIELD",
    "AVAILABILITY_FIELD",
    "BARCODE_FIELD",
    "BRAND_LIKE_FIELDS",
    "CANONICAL_URL_FIELD",
    "COLOR_FIELD",
    "CURRENCY_FIELD",
    "ECOMMERCE_DETAIL_JS_STATE_PRIORITY_FIELDS",
    "IMAGE_URL_FIELD",
    "NORMALIZER_LIST_TEXT_FIELDS",
    "PRICE_FIELD",
    "PRICE_DICT_PREFERRED_KEYS",
    "PRODUCT_ID_FIELD",
    "HTML_SECTION_FIELDS",
    "REQUESTED_FIELD_ALIAS_BASES",
    "REQUESTED_FIELD_ALIAS_EXTRAS",
    "REQUESTED_FIELD_PREFIXES",
    "ROUTE_BARCODE_TO_SKU",
    "SELECTED_VARIANT_FIELD",
    "SIZE_FIELD",
    "SKU_FIELD",
    "STOCK_QUANTITY_FIELD",
    "TITLE_FIELD",
    "TITLE_STRUCTURED_VALUE_KEYS",
    "UNICODE_ESCAPE_RE",
    "URL_FIELD",
    "VARIANTS_FIELD",
    "VARIANT_AXES_FIELD",
    "VARIANT_AXIS_FIELD_NAMES",
    "WEIGHT_FIELD",
    "WIDTH_FIELD",
]


def __getattr__(name: str) -> Any:
    try:
        value = _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    return value if value is not None else ()


__all__ = sorted(list(_STATIC_EXPORTS.keys()) + _EXTRA_EXPORTS)
