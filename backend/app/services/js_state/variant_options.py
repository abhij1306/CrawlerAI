from __future__ import annotations

from typing import Any

from app.services.config.js_state_field_specs import VARIANT_AXIS_KEYS
from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_key,
    variant_axis_name_is_semantic,
)
from app.services.shared.field_coerce import (
    coerce_field_value,
    text_or_none,
)


def variant_axis_value(
    axis_name: str,
    value: object,
    *,
    page_url: str,
) -> str | None:
    axis_key = normalized_variant_axis_key(axis_name) or str(axis_name or "")
    coerced = coerce_field_value(axis_key, value, page_url)
    return text_or_none(coerced)


def variant_selection_values(
    variant: dict[str, Any],
    *,
    option_names: list[str],
) -> dict[str, str]:
    selection_values: dict[str, str] = {}
    named_axis = _name_value_axis(variant)
    if named_axis:
        return named_axis
    selected_options = (
        variant.get("selectedOptions")
        if isinstance(variant.get("selectedOptions"), list)
        else variant.get("selected_options")
    )
    if isinstance(selected_options, list):
        for item in selected_options:
            if not isinstance(item, dict):
                continue
            axis_name = text_or_none(item.get("name") or item.get("label"))
            axis_key = normalized_variant_axis_key(axis_name)
            axis_value = variant_axis_value(
                axis_key,
                item.get("value") or item.get("title") or item.get("label"),
                page_url="",
            )
            if axis_key and axis_value and variant_axis_name_is_semantic(axis_name):
                selection_values[axis_key] = axis_value
    if selection_values:
        return selection_values
    variation_values = variant.get("variationValues")
    if not isinstance(variation_values, dict):
        variation_values = variant.get("variation_values")
    if isinstance(variation_values, dict):
        for axis_name, raw_value in variation_values.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned = variant_axis_value(axis_key, raw_value, page_url="")
            if axis_key and cleaned and variant_axis_name_is_semantic(axis_name):
                selection_values[axis_key] = cleaned
    if selection_values:
        return selection_values
    raw_options = _as_list(variant.get("options"))
    for index in range(1, 4):
        axis_name = (
            option_names[index - 1]
            if index - 1 < len(option_names)
            else f"option_{index}"
        )
        axis_key = normalized_variant_axis_key(axis_name)
        if not axis_key or not variant_axis_name_is_semantic(axis_name):
            continue
        value = variant.get(f"option{index}")
        if value in (None, "", [], {}) and index - 1 < len(raw_options):
            value = raw_options[index - 1]
        cleaned = variant_axis_value(axis_key, value, page_url="")
        if cleaned:
            selection_values[axis_key] = cleaned
    return selection_values


def variant_option_values(
    variant: dict[str, Any],
    *,
    option_names: list[str],
    option_value_labels: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    option_values: dict[str, str] = {}
    named_axis = _name_value_axis(variant, option_value_labels=option_value_labels)
    if named_axis:
        return named_axis
    selected_options = (
        variant.get("selectedOptions")
        if isinstance(variant.get("selectedOptions"), list)
        else variant.get("selected_options")
    )
    if isinstance(selected_options, list):
        for item in selected_options:
            if not isinstance(item, dict):
                continue
            axis_name = text_or_none(item.get("name") or item.get("label"))
            axis_value = variant_axis_value(
                normalized_variant_axis_key(axis_name or ""),
                item.get("value") or item.get("title") or item.get("label"),
                page_url="",
            )
            if (
                not axis_name
                or not axis_value
                or not variant_axis_name_is_semantic(axis_name)
            ):
                continue
            axis_key = normalized_variant_axis_key(axis_name)
            if axis_key:
                option_values[axis_key] = _display_option_value(
                    axis_key,
                    axis_value,
                    option_value_labels=option_value_labels,
                )
    if option_values:
        return option_values
    variation_values = variant.get("variationValues")
    if not isinstance(variation_values, dict):
        variation_values = variant.get("variation_values")
    if isinstance(variation_values, dict):
        direct_axis_keys = {
            normalized_variant_axis_key(axis_name)
            for axis_name in variation_values
            if normalized_variant_axis_key(axis_name)
            == str(axis_name or "").strip().lower().replace("-", "_")
        }
        for axis_name, raw_value in variation_values.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned = variant_axis_value(axis_key, raw_value, page_url="")
            if (
                not axis_key
                or not cleaned
                or not variant_axis_name_is_semantic(axis_name)
            ):
                continue
            if axis_key in direct_axis_keys and axis_key != str(axis_name).strip().lower():
                continue
            if axis_key in option_values:
                continue
            option_values[axis_key] = _display_option_value(
                axis_key,
                cleaned,
                option_value_labels=option_value_labels,
            )
    if option_values:
        return option_values
    attributes = variant.get("attributes")
    if isinstance(attributes, dict):
        for axis_name, raw_value in attributes.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned = variant_axis_value(axis_key, raw_value, page_url="")
            if (
                not axis_key
                or not cleaned
                or not variant_axis_name_is_semantic(axis_name)
            ):
                continue
            option_values[axis_key] = _display_option_value(
                axis_key,
                cleaned,
                option_value_labels=option_value_labels,
            )
    if option_values:
        return option_values
    traits = variant.get("traits")
    if isinstance(traits, dict):
        for axis_name, raw_value in traits.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned = variant_axis_value(axis_key, raw_value, page_url="")
            if (
                not axis_key
                or not cleaned
                or not variant_axis_name_is_semantic(axis_name)
            ):
                continue
            option_values[axis_key] = _display_option_value(
                axis_key,
                cleaned,
                option_value_labels=option_value_labels,
            )
    if option_values:
        return option_values
    size_chart = variant.get("sizeChart")
    if isinstance(size_chart, dict):
        cleaned = variant_axis_value("size", size_chart.get("baseSize"), page_url="")
        if cleaned:
            option_values["size"] = _display_option_value(
                "size",
                cleaned,
                option_value_labels=option_value_labels,
            )
    if option_values:
        return option_values
    raw_options = _as_list(variant.get("options"))
    for index in range(1, 4):
        axis_name = (
            option_names[index - 1]
            if index - 1 < len(option_names)
            else f"option_{index}"
        )
        axis_key = normalized_variant_axis_key(axis_name) or f"option_{index}"
        if not variant_axis_name_is_semantic(axis_name):
            continue
        value = variant.get(f"option{index}")
        if value in (None, "", [], {}) and index - 1 < len(raw_options):
            value = raw_options[index - 1]
        cleaned = variant_axis_value(axis_key, value, page_url="")
        if cleaned:
            option_values[axis_key] = _display_option_value(
                axis_key,
                cleaned,
                option_value_labels=option_value_labels,
            )
    if not option_values:
        for possible_axis in VARIANT_AXIS_KEYS:
            val = variant.get(possible_axis)
            cleaned = variant_axis_value(possible_axis, val, page_url="")
            if cleaned:
                option_values[possible_axis] = _display_option_value(
                    possible_axis,
                    cleaned,
                    option_value_labels=option_value_labels,
                )
    return option_values


def option_value_labels(product: dict[str, Any]) -> dict[str, dict[str, str]]:
    labels: dict[str, dict[str, str]] = {}
    raw_attributes = product.get("variationAttributes")
    if not isinstance(raw_attributes, list):
        raw_attributes = product.get("variation_attributes")
    if not isinstance(raw_attributes, list):
        raw_attributes = product.get("attributes")
    if not isinstance(raw_attributes, list):
        return labels
    direct_axis_keys = {
        normalized_variant_axis_key(
            text_or_none(
                attribute.get("id") or attribute.get("name") or attribute.get("label")
            )
            or ""
        )
        for attribute in raw_attributes
        if isinstance(attribute, dict)
        if normalized_variant_axis_key(
            text_or_none(
                attribute.get("id") or attribute.get("name") or attribute.get("label")
            )
            or ""
        )
        == str(text_or_none(attribute.get("id") or "") or "")
        .strip()
        .lower()
        .replace("-", "_")
    }
    for attribute in raw_attributes:
        if not isinstance(attribute, dict):
            continue
        axis_name = text_or_none(
            attribute.get("id")
            or attribute.get("name")
            or attribute.get("label")
            or attribute.get("type")
        )
        axis_key = normalized_variant_axis_key(axis_name or "")
        if not axis_key:
            continue
        if axis_key in direct_axis_keys and axis_key != str(axis_name or "").strip().lower():
            continue
        values = attribute.get("values")
        if not isinstance(values, list):
            values = attribute.get("options")
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            raw_value = text_or_none(item.get("value") or item.get("id") or item.get("slug"))
            display = text_or_none(
                item.get("name")
                or item.get("displayValue")
                or item.get("display_value")
                or item.get("label")
            )
            if not raw_value or not display:
                continue
            labels.setdefault(axis_key, {})[raw_value] = display
            item_id = text_or_none(item.get("id") or item.get("slug"))
            if item_id:
                labels.setdefault(axis_key, {})[item_id] = display
    return labels


def _name_value_axis(
    variant: dict[str, Any],
    *,
    option_value_labels: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    axis_name = text_or_none(variant.get("name") or variant.get("label"))
    axis_key = normalized_variant_axis_key(axis_name or "")
    cleaned = variant_axis_value(axis_key, variant.get("value"), page_url="")
    if not axis_key or not cleaned or not variant_axis_name_is_semantic(axis_name):
        return {}
    return {
        axis_key: _display_option_value(
            axis_key,
            cleaned,
            option_value_labels=option_value_labels,
        )
    }


def _display_option_value(
    axis_key: str,
    value: str,
    *,
    option_value_labels: dict[str, dict[str, str]] | None,
) -> str:
    cleaned = text_or_none(value)
    if not cleaned:
        return ""
    return (option_value_labels or {}).get(axis_key, {}).get(cleaned, cleaned)


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
