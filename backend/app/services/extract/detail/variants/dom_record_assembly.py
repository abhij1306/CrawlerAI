from __future__ import annotations

from itertools import product
from typing import Any

from app.services.config.extraction_rules import DOM_VARIANT_CARTESIAN_COMBO_LIMIT
from app.services.extract.detail.variants import dom_coercion as _variant_coercion
from app.services.extract.detail.variants.state_targets import state_variant_targets
from app.services.extract.variant_axis import normalized_variant_axis_key
from app.services.extract.variant_identity_merge import (
    resolve_variants,
    split_variant_axes,
)
from app.services.extract.variant_normalization.contract import (
    flatten_variants_for_public_output,
)
from app.services.js_state.helpers import select_variant
from app.services.shared.field_coerce import (
    clean_text,
    object_list as _object_list,
    text_or_none,
)

_DOM_OPTION_AVAILABILITY_PRIORITY = (
    "out_of_stock",
    "limited_stock",
    "in_stock",
)
_dom_variant_axis_allowed = _variant_coercion._dom_variant_axis_allowed


def assemble_dom_variant_record(
    *,
    deduped_groups: list[dict[str, object]],
    js_state_objects: dict[str, Any] | None,
    page_url: str,
    safe_int_config,
    cartesian_combo_limit: object = DOM_VARIANT_CARTESIAN_COMBO_LIMIT,
) -> dict[str, object]:
    state_axis_targets, state_combo_targets = state_variant_targets(
        js_state_objects,
        page_url=page_url,
    )
    record: dict[str, object] = {}
    axis_values_by_name: dict[str, list[str]] = {}
    axis_option_metadata: dict[str, dict[str, dict[str, object]]] = {}
    axis_order: list[tuple[str, str, list[str]]] = []
    for group in deduped_groups:
        name = clean_text(group.get("name"))
        values = [str(value) for value in _object_list(group.get("values"))]
        axis_key = normalized_variant_axis_key(name)
        if not _dom_variant_axis_allowed(axis_key):
            continue
        axis_values_by_name[axis_key] = values
        axis_option_metadata[axis_key] = _option_metadata(group)
        _merge_state_axis_targets(
            axis_option_metadata[axis_key],
            dict(state_axis_targets.get(axis_key) or {}),
        )
        axis_order.append((axis_key, name, values))
    if not axis_values_by_name:
        return {}

    variants = _dom_variants_from_axes(
        axis_order=axis_order,
        axis_option_metadata=axis_option_metadata,
        state_combo_targets=state_combo_targets,
        combo_limit=safe_int_config(
            cartesian_combo_limit,
            1000,
            "DOM_VARIANT_CARTESIAN_COMBO_LIMIT",
        ),
    )
    selectable_axes, single_value_attributes = split_variant_axes(
        axis_values_by_name,
        always_selectable_axes=frozenset({"size"}),
    )
    resolved_variants = (
        resolve_variants(selectable_axes or axis_values_by_name, variants)
        if variants
        else []
    )
    active_variant = _selected_or_active_variant(
        resolved_variants,
        axis_order=axis_order,
        axis_option_metadata=axis_option_metadata,
        page_url=page_url,
    )
    for axis_name, value in single_value_attributes.items():
        record.setdefault(axis_name, value)
    if resolved_variants:
        _apply_resolved_variants(
            record,
            resolved_variants=resolved_variants,
            active_variant=active_variant,
            page_url=page_url,
        )
    return record


def _option_metadata(group: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        clean_text(entry.get("value")): {
            key: entry.get(key)
            for key in (
                "availability",
                "selected",
                "style",
                "stock_quantity",
                "url",
                "variant_id",
                "image_url",
            )
            if entry.get(key) not in (None, "", [], {})
        }
        for entry in _object_list(group.get("entries"))
        if isinstance(entry, dict)
        if clean_text(entry.get("value"))
    }


def _merge_state_axis_targets(
    option_metadata: dict[str, dict[str, object]],
    state_targets: dict[object, object],
) -> None:
    for option_value, state_metadata in state_targets.items():
        merged_metadata = option_metadata.setdefault(str(option_value), {})
        if not isinstance(state_metadata, dict):
            continue
        for key in ("url", "variant_id", "image_url"):
            if state_metadata.get(key) not in (None, "", [], {}) and merged_metadata.get(
                key
            ) in (None, "", [], {}):
                merged_metadata[key] = state_metadata[key]


def _dom_variants_from_axes(
    *,
    axis_order: list[tuple[str, str, list[str]]],
    axis_option_metadata: dict[str, dict[str, dict[str, object]]],
    state_combo_targets: dict[tuple[tuple[str, str], ...], dict[str, object]],
    combo_limit: int,
) -> list[dict[str, object]]:
    axis_names = [axis_key for axis_key, _label, _values in axis_order]
    axis_value_lists = [values for _axis_key, _label, values in axis_order]
    if _dom_variant_combo_count(axis_value_lists) > combo_limit:
        return _axis_only_dom_variants(axis_order, axis_option_metadata)
    variants: list[dict[str, object]] = []
    for combo in product(*axis_value_lists):
        variant = _combo_variant(
            combo,
            axis_names=axis_names,
            axis_option_metadata=axis_option_metadata,
            state_combo_targets=state_combo_targets,
        )
        if variant:
            variants.append(variant)
    return variants


def _combo_variant(
    combo: tuple[str, ...],
    *,
    axis_names: list[str],
    axis_option_metadata: dict[str, dict[str, dict[str, object]]],
    state_combo_targets: dict[tuple[tuple[str, str], ...], dict[str, object]],
) -> dict[str, object]:
    option_values = {
        axis_name: value
        for axis_name, value in zip(axis_names, combo, strict=False)
        if clean_text(value)
    }
    if not option_values:
        return {}
    variant: dict[str, object] = {"option_values": option_values, **option_values}
    selected_metadata = _selected_option_metadata(axis_option_metadata, option_values)
    availability = _availability_from_selected_options(selected_metadata)
    if availability:
        variant["availability"] = availability
    stock_quantity = _stock_quantity_from_selected_options(selected_metadata)
    if stock_quantity is not None:
        variant["stock_quantity"] = stock_quantity
    combo_metadata = state_combo_targets.get(tuple(sorted(option_values.items())), {})
    for key in ("url", "variant_id", "image_url"):
        if combo_metadata.get(key) not in (None, "", [], {}):
            variant[key] = combo_metadata[key]
    if len(axis_names) == 1:
        option_metadata = axis_option_metadata.get(axis_names[0], {}).get(
            str(combo[0]), {}
        )
        if option_metadata.get("style") not in (None, "", [], {}):
            variant["style"] = option_metadata.get("style")
        for key in ("url", "variant_id", "image_url"):
            if option_metadata.get(key) not in (None, "", [], {}):
                variant[key] = option_metadata.get(key)
    return variant


def _selected_or_active_variant(
    resolved_variants: list[dict[str, object]],
    *,
    axis_order: list[tuple[str, str, list[str]]],
    axis_option_metadata: dict[str, dict[str, dict[str, object]]],
    page_url: str,
) -> dict[str, object] | None:
    active_variant = select_variant(resolved_variants, page_url=page_url)
    selected_option_values = {
        axis_name: option_value
        for axis_name, option_value in (
            (
                axis_name,
                next(
                    (
                        value
                        for value, metadata in axis_option_metadata.get(
                            axis_name, {}
                        ).items()
                        if metadata.get("selected")
                    ),
                    None,
                ),
            )
            for axis_name, _label, _values in axis_order
        )
        if option_value
    }
    if not selected_option_values:
        return active_variant
    return next(
        (
            variant
            for variant in resolved_variants
            if variant.get("option_values") == selected_option_values
        ),
        active_variant,
    )


def _apply_resolved_variants(
    record: dict[str, object],
    *,
    resolved_variants: list[dict[str, object]],
    active_variant: dict[str, object] | None,
    page_url: str,
) -> None:
    flat_variants = flatten_variants_for_public_output(
        resolved_variants,
        page_url=page_url,
    ) or []
    if flat_variants:
        for variant in flat_variants:
            variant["_validated"] = True
        record["variants"] = flat_variants
        record["variant_count"] = len(flat_variants)
    if active_variant and record.get("availability") in (None, "", [], {}):
        selected_availability = text_or_none(active_variant.get("availability"))
        if selected_availability:
            record["availability"] = selected_availability


def _selected_option_metadata(
    axis_option_metadata: dict[str, dict[str, dict[str, object]]],
    option_values: dict[str, str],
) -> list[dict[str, object]]:
    selected_metadata: list[dict[str, object]] = []
    for axis_name, value in option_values.items():
        metadata = axis_option_metadata.get(axis_name, {}).get(clean_text(value), {})
        if isinstance(metadata, dict) and metadata:
            selected_metadata.append(metadata)
    return selected_metadata


def _availability_from_selected_options(
    selected_metadata: list[dict[str, object]],
) -> str:
    values = {
        text_or_none(metadata.get("availability"))
        for metadata in selected_metadata
        if isinstance(metadata, dict)
    }
    values.discard(None)
    for candidate in _DOM_OPTION_AVAILABILITY_PRIORITY:
        if candidate in values:
            return candidate
    return ""


def _stock_quantity_from_selected_options(
    selected_metadata: list[dict[str, object]],
) -> int | None:
    quantities: list[int] = []
    for metadata in selected_metadata:
        if not isinstance(metadata, dict):
            continue
        raw_quantity = metadata.get("stock_quantity")
        if raw_quantity in (None, "", [], {}):
            continue
        try:
            quantities.append(int(str(raw_quantity).strip()))
        except (TypeError, ValueError):
            continue
    if not quantities:
        return None
    if any(quantity <= 0 for quantity in quantities):
        return 0
    if len(set(quantities)) == 1:
        return quantities[0]
    return None


def _dom_variant_combo_count(axis_value_lists: list[list[str]]) -> int:
    count = 1
    for values in axis_value_lists:
        count *= max(1, len(values))
    return count


def _axis_only_dom_variants(
    axis_order: list[tuple[str, str, list[str]]],
    axis_option_metadata: dict[str, dict[str, dict[str, object]]],
) -> list[dict[str, object]]:
    variants: list[dict[str, object]] = []
    for axis_key, _name, values in axis_order:
        for value in values:
            cleaned_value = clean_text(value)
            if not cleaned_value:
                continue
            option_values = {axis_key: cleaned_value}
            variant: dict[str, object] = {
                "option_values": option_values,
                axis_key: cleaned_value,
            }
            metadata = axis_option_metadata.get(axis_key, {}).get(cleaned_value, {})
            for key in (
                "availability",
                "selected",
                "style",
                "stock_quantity",
                "url",
                "variant_id",
                "image_url",
            ):
                if metadata.get(key) not in (None, "", [], {}):
                    variant[key] = metadata[key]
            variants.append(variant)
    return variants
