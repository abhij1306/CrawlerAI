"""Public variant axis and transport-field policy."""

from __future__ import annotations

import re

from app.core.config.extraction_price_rules import (
    DETAIL_EXPLICIT_MINOR_UNIT_PRICE_FIELDS,
)
from app.core.config.field_mappings import (
    AVAILABILITY_FIELD,
    BARCODE_FIELD,
    COLOR_FIELD,
    CURRENCY_FIELD,
    ECOMMERCE_DISPLAY_PRICE_SOURCE_KEYS,
    IMAGE_URL_FIELD,
    PRICE_FIELD,
    SIZE_FIELD,
    SKU_FIELD,
    STOCK_QUANTITY_FIELD,
    URL_FIELD,
    WEIGHT_FIELD,
)


def _normalized_variant_axis_alias_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower().replace("&", " ")).strip(
        "_"
    )


VARIANT_AXIS_CANONICAL_MAPPING: dict[frozenset[str], str] = {
    frozenset(
        {
            COLOR_FIELD,
            "colors",
            "colour",
            "colours",
            "hue",
            "shade",
            "color way",
            "color_way",
            "colorway",
            "frame color",
            "frame_color",
            "frame colour",
            "frame_colour",
        }
    ): COLOR_FIELD,
    frozenset({SIZE_FIELD, "sizes", "frame size", "frame_size"}): SIZE_FIELD,
    frozenset(
        {"resolution", "resolutions", "display resolution", "display_resolution"}
    ): "resolution",
    frozenset(
        {"screen size", "screen_size", "display size", "display_size"}
    ): "screen_size",
    frozenset(
        {"upholstery color", "upholstery colour", "upholstery_color"}
    ): "upholstery_color",
    frozenset({"type", "types"}): "type",
    frozenset({"switch", "switches", "switch type", "switch_type"}): "switches",
    frozenset({"fit", "fits"}): "fit",
    frozenset({"length", "lengths"}): "length",
    frozenset({"width", "widths", "shoe width", "shoe_width"}): "width",
    frozenset(
        {
            "dimensions",
            "dimension",
            "measurements",
            "measurement",
            "proportions",
            "proportion",
        }
    ): "dimensions",
    frozenset({"flavor", "flavors", "flavour", "flavours", "taste"}): "flavor",
    frozenset({"material", "materials"}): "material",
    frozenset({"pattern", "patterns"}): "pattern",
    frozenset({"finish", "finishes"}): "finish",
    frozenset(
        {
            "count",
            "counts",
            "pack count",
            "pack_count",
            "package count",
            "package_count",
        }
    ): "count",
    frozenset(
        {
            "bundle type",
            "bundle_type",
            "bundle",
            "bundles",
            "part or kit",
            "part_or_kit",
        }
    ): "bundle_type",
    frozenset({WEIGHT_FIELD, "weights"}): WEIGHT_FIELD,
    frozenset({"firmness", "firm"}): "firmness",
    frozenset({"thickness", "thick"}): "thickness",
    frozenset({"storage capacity", "storage_capacity"}): "storage_capacity",
    frozenset({"material composition", "material_composition", "composition"}): (
        "material_composition"
    ),
}
PUBLIC_VARIANT_AXIS_FIELDS: tuple[str, ...] = (
    COLOR_FIELD,
    SIZE_FIELD,
    "resolution",
    "screen_size",
    "upholstery_color",
    "type",
    "switches",
    "fit",
    "length",
    "width",
    "flavor",
    "material",
    "pattern",
    "finish",
    "firmness",
    "count",
    "bundle_type",
    WEIGHT_FIELD,
    "dimensions",
    "style",
    "condition",
    "state",
    "storage",
    "storage_capacity",
    "connectivity",
    "voltage",
    "plug_type",
    "volume",
    "scent",
    "spf_rating",
    "skin_type",
    "configuration",
    "fabric_grade",
    "leg_finish",
    "tolerance_level",
    "thread_size",
    "thickness",
    "material_composition",
    "load_rating",
    "frequency",
    "commitment_period",
    "seat_count",
    "usage_limit",
    "tier",
)
DETAIL_PARENT_VARIANT_PRICE_DRIFT_MAX_RATIO = 0.01
GEOGRAPHIC_STATE_VARIANT_MIN_MATCHES = 3
GEOGRAPHIC_STATE_VARIANT_VALUES: tuple[str, ...] = (
    "alabama",
    "alaska",
    "american samoa",
    "arizona",
    "arkansas",
    "armed forces africa",
    "armed forces americas",
    "armed forces canada",
    "armed forces europe",
    "armed forces middle east",
    "armed forces pacific",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "district of columbia",
    "federated states of micronesia",
    "florida",
    "georgia",
    "guam",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "marshall islands",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "northern mariana islands",
    "ohio",
    "oklahoma",
    "oregon",
    "palau",
    "pennsylvania",
    "puerto rico",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virgin islands",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
)
GEOGRAPHIC_STATE_VARIANT_VALUE_SET = frozenset(GEOGRAPHIC_STATE_VARIANT_VALUES)
AXIS_NAME_ALIASES = {
    normalized_alias: normalized_canonical
    for group, canonical in VARIANT_AXIS_CANONICAL_MAPPING.items()
    for normalized_canonical in [_normalized_variant_axis_alias_key(canonical)]
    for normalized_alias in (
        _normalized_variant_axis_alias_key(str(raw_alias)) for raw_alias in group
    )
    if normalized_alias and normalized_canonical
}
OPTION_SCALAR_FIELDS = frozenset(PUBLIC_VARIANT_AXIS_FIELDS)
VARIANT_SKU_VALUE_KEYS = (
    "sku",
    "skuCode",
    "sku_code",
    "skuId",
    "sku_id",
    "merchSkuId",
    "merch_sku_id",
    "stockKeepingUnit",
)
VARIANT_URL_VALUE_KEYS = ("url", "productUrl", "product_url", "pdpUrl", "pdp_url")
VARIANT_IMAGE_DIMENSION_MIN_PX = 100
EMBEDDED_STATE_SCRIPT_SELECTOR = (
    'script[type="application/json"], '
    "script#__NEXT_DATA__, script#__NUXT_DATA__, script#__NG_STATE__, "
    'script[id^="ProductJson"]'
)
EMBEDDED_STATE_GLOBAL_KEYS = (
    "__INITIAL_STATE__",
    "INITIAL_STATE",
    "__PRELOADED_STATE__",
    "__NUXT__",
    "__NG_STATE__",
    "SDG.Data.productJson",
    "_RestockRocketConfig.product",
    "meta",
)
EMBEDDED_STATE_PRODUCT_META_KEY = "meta"
EMBEDDED_STATE_PRODUCT_META_CONTAINER_KEY = "product"
EMBEDDED_STATE_PRODUCT_META_VARIANTS_KEY = "variants"
EMBEDDED_STATE_MAX_SCRIPTS = 120
EMBEDDED_STATE_MAX_SCRIPT_CHARS = 10_000_000
EMBEDDED_STATE_MAX_DEPTH = 24
EMBEDDED_STATE_MAX_NODES = 100_000
EMBEDDED_STATE_MAX_LIST_ITEMS = 5_000
VARIANT_MERCH_SKU_ID_KEYS = ("merchSkuId", "merch_sku_id")
VARIANT_MERCH_SKU_SIZE_KEYS = ("label", "localizedLabel")
VARIANT_CHILD_COLLECTION_KEYS = (
    "variants",
    "variations",
    "sizes",
    "skus",
    "skuData",
    "sku_data",
)
VARIANT_PARENT_OPTION_CHILD_KEYS = ("variants", "variations")
VARIANT_PRODUCT_MAP_PATH_TOKENS = frozenset({"products"})
VARIANT_PRODUCT_MAP_KEY_MIN_LENGTH = 4
VARIANT_NESTED_URL_VALUE_KEYS = ("url", "canonicalUrl", "canonical_url", "path")
VARIANT_SHOPIFY_SIZE_KEYS = ("public_title", "untranslatedTitle")
VARIANT_SIZE_LIKE_PATTERN = (
    r"^(?:"
    r"(?:\d+(?:\.\d+)?)(?:\s*[-/]\s*\d+(?:\.\d+)?)?"
    r"|(?:X{0,4}[SML]|[2-9]X[SL])"
    r"|(?:ONE\s*SIZE|O/S|OS|ONE)"
    r")$"
)
VARIANT_POSITIONAL_OPTION_KEYS = ("option1", "option2", "option3")
VARIANT_POSITIONAL_NUMERIC_SIZE_MIN = 1.0
VARIANT_POSITIONAL_NUMERIC_SIZE_MAX = 99.0
VARIANT_STRUCTURED_PATH_TOKENS = frozenset(
    {"variant", "variants", "variation", "variations", "sku", "skus", "skudata"}
)
VARIANT_DIRECT_OPTION_FIELD_AXES = {
    "size": "size",
    "sizeDescription": "size",
    "displaySize": "size",
    "localizedSize": "size",
    "nikeSize": "size",
    "sizeLabel": "size",
    "sizeName": "size",
    "color": "color",
    "colour": "color",
    "colorName": "color",
    "displayColor": "color",
    "colorDisplayName": "color",
    "colorDescription": "color",
    "colorway": "color",
    "shade": "color",
    "shadeName": "color",
    "width": "width",
    "length": "length",
    "material": "material",
    "style": "style",
    "capacity": "capacity",
    "quantity": "quantity",
}
VARIANT_OPTION_CONTAINER_KEYS = (
    "attributes",
    "variationValues",
    "variationAttributes",
    "selectedOptions",
    "options",
    "productOptions",
    "dimensions",
)
VARIANT_OPTION_AXIS_KEYS = (
    "name",
    "label",
    "displayName",
    "attributeName",
    "optionName",
    "variationType",
    "type",
)
VARIANT_OPTION_VALUE_KEYS = (
    "value",
    "displayValue",
    "optionValue",
    "selectedValue",
    "variationValue",
    "shadeName",
    "name",
    "label",
)
VARIANT_SCALAR_VALUE_KEYS = (
    "value",
    "text",
    "name",
    "label",
    "displayValue",
    "optionValue",
    "selectedValue",
    "variationValue",
    *ECOMMERCE_DISPLAY_PRICE_SOURCE_KEYS,
    *DETAIL_EXPLICIT_MINOR_UNIT_PRICE_FIELDS,
    "amount",
    "current",
    "currentPrice",
    "salePrice",
    "listPrice",
    "price",
)
VARIANT_OFFER_DISPLAY_PRICE_KEYS = ECOMMERCE_DISPLAY_PRICE_SOURCE_KEYS
VARIANT_OFFER_PRICE_KEYS = (
    "price",
    "currentPrice",
    "current_price",
    "salePrice",
    "sale_price",
    *DETAIL_EXPLICIT_MINOR_UNIT_PRICE_FIELDS,
    "priceInfo",
    "pricing",
)
VARIANT_OFFER_ORIGINAL_PRICE_KEYS = (
    "originalPrice",
    "regularPrice",
    "listPrice",
    "compareAtPrice",
)
VARIANT_OFFER_CURRENCY_KEYS = (
    "currency",
    "currencyCode",
    "currency_code",
    "priceCurrency",
)
VARIANT_OFFER_AVAILABILITY_KEYS = (
    "availability",
    "available",
    "inStock",
    "isAvailable",
    "isInStock",
    "inventoryStatus",
    "purchasable",
    "isPurchasable",
    "availableForSale",
    "sellable",
    "isSellable",
)
VARIANT_OFFER_STOCK_KEYS = (
    "stock_quantity",
    "stockQuantity",
    "inventory",
    "inventoryQuantity",
)
VARIANT_GTIN_VALUE_KEYS = (
    "gtin",
    "gtin8",
    "gtin12",
    "gtin13",
    "gtin14",
    "barcode",
    "upc",
    "ean",
)

STRUCTURED_EVIDENCE_PRIORITY_RANKS = {
    "identity": 1,
    "requested": 2,
    "options": 3,
    "offer": 4,
    "identifiers": 5,
    "variant_assets": 6,
    "descriptive": 7,
}
STRUCTURED_EVIDENCE_IDENTITY_FACTS = frozenset(
    {"product.id", "product.url", "variant.id"}
)
STRUCTURED_EVIDENCE_ATOMIC_OFFER_FACTS = frozenset(
    {
        "offer.price",
        "offer.currency",
        "offer.availability",
        "offer.original_price",
        "offer.stock_quantity",
    }
)
STRUCTURED_EVIDENCE_IDENTIFIER_FACTS = frozenset(
    {
        "product.sku",
        "product.mpn",
        "product.gtin",
        "variant.sku",
        "variant.gtin",
    }
)
STRUCTURED_EVIDENCE_DESCRIPTIVE_FACTS = frozenset(
    {"product.description", "asset.image_url"}
)
STRUCTURED_SOURCE_OBJECT_BUDGET_REASON = "source_object_budget_exhausted"
STRUCTURED_EVIDENCE_BUDGET_REASON = "evidence_per_source_object_budget_exhausted"
CHILD_JOIN_FAILED_RULE_ID = "CHILD_JOIN_FAILED"
DEFAULT_VARIANT_DIAGNOSTIC_REASON = "default_variant_diagnostic_only"
DEFAULT_VARIANT_PLACEHOLDER_FLAG = "default_variant_placeholder"
STRUCTURED_EVIDENCE_FACT_PREFIXES = {
    "variant_options": "variant.option.",
    "variant_identity": "variant.",
    "offer": "offer.",
    "assets": "asset.",
}
STRUCTURED_EVIDENCE_FACT_FAMILIES = {
    "variant_options": "variant_options",
    "variant_identity": "variant_identity",
    "offer": "offer",
    "variant_assets": "variant_assets",
    "assets": "assets",
}


def variant_state_values_are_geographic(values: object) -> bool:
    if not isinstance(values, list):
        return False
    matched = {
        str(value or "").strip().casefold()
        for value in values
        if str(value or "").strip().casefold() in GEOGRAPHIC_STATE_VARIANT_VALUE_SET
    }
    return len(matched) >= int(GEOGRAPHIC_STATE_VARIANT_MIN_MATCHES)


FLAT_VARIANT_KEYS: tuple[str, ...] = (
    "variant_id",
    COLOR_FIELD,
    SIZE_FIELD,
    "style",
    SKU_FIELD,
    BARCODE_FIELD,
    PRICE_FIELD,
    CURRENCY_FIELD,
    URL_FIELD,
    IMAGE_URL_FIELD,
    AVAILABILITY_FIELD,
    STOCK_QUANTITY_FIELD,
)
PUBLIC_FLAT_VARIANT_FIELDS = frozenset(
    (*PUBLIC_VARIANT_AXIS_FIELDS, *FLAT_VARIANT_KEYS)
)
NON_PUBLIC_VARIANT_IDENTITY_FIELDS = frozenset({"gtin"})
VARIANT_TRANSPORT_FIELDS = frozenset(
    {
        "variant_id",
        SKU_FIELD,
        BARCODE_FIELD,
        URL_FIELD,
        PRICE_FIELD,
        CURRENCY_FIELD,
        IMAGE_URL_FIELD,
        AVAILABILITY_FIELD,
        STOCK_QUANTITY_FIELD,
    }
)
_VARIANT_ROW_EMPTY_VALUES: tuple[object, ...] = (None, "", [], {}, ())


def variant_row_is_image_dimension_artifact(row: dict[str, object]) -> bool:
    """A row that is only ``variant_id`` + a large ``width`` is an image
    dimension echo, not a sellable variant."""
    if set(row) - {"variant_id", "width"}:
        return False
    width = str(row.get("width") or "").strip()
    return width.isdigit() and int(width) >= VARIANT_IMAGE_DIMENSION_MIN_PX


def public_variant_row_is_sellable(row: dict[str, object]) -> bool:
    """The single publish gate for a flattened variant row.

    Sellable iff the row carries any transport field (identifier / commercial
    fact / image), OR exposes >=2 option axes, OR a single axis that is one of
    the canonical retail axes (size / color — the dominant Shopify/PDP shape).
    Resolve and publication both defer here so a size-only / pre-order /
    color-only variant cannot be admitted by one stage and silently dropped by
    another.
    """
    if not row or variant_row_is_image_dimension_artifact(row):
        return False
    if any(
        row.get(field) not in _VARIANT_ROW_EMPTY_VALUES
        for field in VARIANT_TRANSPORT_FIELDS
    ):
        return True
    axes = {
        str(key)
        for key, value in row.items()
        if str(key) in PUBLIC_VARIANT_AXIS_FIELDS
        and value not in _VARIANT_ROW_EMPTY_VALUES
    }
    if len(axes) >= 2:
        return True
    return bool(axes & {SIZE_FIELD, COLOR_FIELD})


SCENT_DOMINANT_URL_TOKENS = frozenset({"body-mist"})
DETAIL_VARIANT_SIZE_MIN_FOR_NUMERIC_PARENT_DROP = 2
VARIANT_PARENT_SHARED_FIELDS: tuple[str, ...] = (
    URL_FIELD,
    IMAGE_URL_FIELD,
)
DETAIL_PRODUCT_VARIANT_CONSENSUS_FIELDS: tuple[str, ...] = (
    COLOR_FIELD,
    PRICE_FIELD,
    CURRENCY_FIELD,
    IMAGE_URL_FIELD,
)
DETAIL_PRODUCT_VARIANT_OVERRIDE_FIELDS: tuple[str, ...] = (
    COLOR_FIELD,
    CURRENCY_FIELD,
)
DETAIL_PARENT_INHERITED_OFFER_FIELDS: tuple[str, ...] = (
    PRICE_FIELD,
    CURRENCY_FIELD,
    AVAILABILITY_FIELD,
)
DETAIL_VARIANT_CONSENSUS_RULE_ID = "VARIANT_CONSENSUS_TO_PRODUCT"
DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID = "PARENT_OFFER_TO_VARIANT"
DETAIL_NEGATIVE_STOCK_RULE_ID = "NEGATIVE_STOCK_TO_OUT_OF_STOCK"
DETAIL_REQUIRED_OFFER_FIELDS: tuple[str, ...] = (PRICE_FIELD, CURRENCY_FIELD)
DETAIL_MINIMUM_KNOWLEDGE_FIELDS: tuple[str, ...] = (
    PRICE_FIELD,
    IMAGE_URL_FIELD,
    "description",
    "brand",
    "variants",
)
VARIANT_COLOR_METADATA_PREFIX_PATTERN = r"^(?:[a-z]+)?colou?rname[\s:_-]+"
RELATED_VOLUME_VARIANT_PATTERN = r"^\s*\d+(?:\.\d+)?\s*(?:fl\s*)?oz\b"
RELATED_VOLUME_VARIANT_RULE_ID = "RELATED_VOLUME_ROWS_REMOVED"
