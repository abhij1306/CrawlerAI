"""Public persisted/exported record policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from app.core.config.field_mappings import (
    APPLY_URL_FIELD,
    CANONICAL_URL_FIELD,
    URL_FIELD,
)

PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS: Mapping[str, Sequence[str]] = {
    "ecommerce_detail": (
        "canonical_url",
        "created_at",
        "image_count",
        "published_at",
        "updated_at",
    )
}
PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS: tuple[str, ...] = (
    "color",
    "colour",
    "productId",
    "product_id",
    "productid",
    "sku",
    "size",
    "variant",
)
PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES: tuple[str, ...] = ("dwvar_",)
PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PATTERNS: tuple[str, ...] = (r"^v\d+$",)
PUBLIC_RECORD_URL_BLOCKED_PATH_MARKERS: tuple[str, ...] = (
    "/api/",
    "/event/",
    "/events/",
    "/tracking/",
    "/analytics/",
    "/beacon/",
    "/click",
)
PUBLIC_RECORD_URL_MAX_LENGTH = 2048

PUBLIC_RECORD_CANONICAL_SURFACE = "ecommerce_detail"
PUBLIC_RECORD_CANONICAL_URL_FIELDS = frozenset(
    {APPLY_URL_FIELD, CANONICAL_URL_FIELD, URL_FIELD}
)
PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS = frozenset({"record_type"})
PUBLIC_RECORD_ECOMMERCE_DROPPED_FIELDS = frozenset({"tags"})
PUBLIC_RECORD_LEGACY_VARIANT_FIELDS = frozenset(
    {
        "selected_variant",
        "variant_axes",
        "available_sizes",
        "option1_name",
        "option1_values",
        "option2_name",
        "option2_values",
        "option_1_name",
        "option_1_value",
        "option_1_values",
        "option_2_name",
        "option_2_value",
        "option_2_values",
    }
)
PUBLIC_RECORD_LEGACY_OPTION_FIELD_PATTERN = r"option\d+_(?:name|values?)"
PUBLIC_RECORD_BARCODE_LENGTHS = frozenset({8, 12, 13, 14})
PUBLIC_RECORD_NUMERIC_BRAND_PATTERN = r"['’]?(?P<brand>\d{2,3})"
PUBLIC_RECORD_BRAND_REGION_SUFFIX_TOKENS = frozenset(
    {
        "USA",
        "US",
        "UK",
        "EU",
        "EN",
        "CA",
        "AU",
        "IN",
        "UAE",
        "GCC",
        "GLOBAL",
        "INTL",
        "INTERNATIONAL",
        "OFFICIAL",
        "ONLINE",
        "STORE",
        "SHOP",
        "HOME",
        "WEBSITE",
    }
)
PUBLIC_RECORD_BRAND_IGNORED_HOST_LABELS = frozenset(
    {"", "www", "shop", "store", "us", "usa", "uk", "in", "com", "co", "net", "org"}
)
PUBLIC_RECORD_BRAND_HOST_SUFFIXES = (
    "beauty",
    "cosmetics",
    "official",
    "online",
    "shop",
    "store",
)
PUBLIC_RECORD_GENERIC_HOST_BRANDS = frozenset(
    {"example", "invalid", "localhost", "test"}
)
PUBLIC_RECORD_GENDER_TAXONOMY = MappingProxyType(
    {
        "men": "Men",
        "m": "Men",
        "man": "Men",
        "male": "Men",
        "mens": "Men",
        "men's": "Men",
        "women": "Women",
        "f": "Women",
        "woman": "Women",
        "female": "Women",
        "womens": "Women",
        "women's": "Women",
        "unisex": "Unisex",
        "uni": "Unisex",
        "kids": "Kids",
        "kid": "Kids",
        "children": "Kids",
        "child": "Kids",
        "boys": "Boys",
        "boy": "Boys",
        "girls": "Girls",
        "girl": "Girls",
    }
)
PUBLIC_RECORD_GENDER_REJECT_TOKENS = frozenset(
    {"default", "null", "na", "n/a", "none", "all", "other", ""}
)
PUBLIC_RECORD_IDENTITY_INTERNAL_TOKENS = frozenset(
    {
        "plp",
        "pdp",
        "specifications",
        "specification",
        "description",
        "details",
        "detail",
        "overview",
        "reviews",
        "review",
        "summary",
        "untitled",
    }
)
PUBLIC_RECORD_PRODUCT_TYPE_NOISE_TOKENS = frozenset(
    {"brightcove", "video", "player", "iframe", "embed", "widget"}
)
PUBLIC_RECORD_SKU_DRAFT_PREFIX_PATTERN = r"^(?:copy|draft|tmp|temp|test)[-_]+"
