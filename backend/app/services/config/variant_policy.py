"""Public variant axis and transport-field policy."""

from __future__ import annotations

import re

from app.services.config.field_mappings import (
    AVAILABILITY_FIELD,
    BARCODE_FIELD,
    COLOR_FIELD,
    CURRENCY_FIELD,
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
VARIANT_TRANSPORT_FIELDS: tuple[str, ...] = (
    PRICE_FIELD,
    CURRENCY_FIELD,
)
SCENT_DOMINANT_URL_TOKENS = frozenset({"body-mist"})
DETAIL_VARIANT_SIZE_MIN_FOR_NUMERIC_PARENT_DROP = 2
VARIANT_PARENT_SHARED_FIELDS: tuple[str, ...] = (
    PRICE_FIELD,
    CURRENCY_FIELD,
    URL_FIELD,
    IMAGE_URL_FIELD,
)
