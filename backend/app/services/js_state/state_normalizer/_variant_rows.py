from __future__ import annotations
# ruff: noqa: F401,F403,F405

from typing import Any

from app.services.config.variant_policy import PUBLIC_VARIANT_AXIS_FIELDS

from ._common import *
from ._variant_mapping import _option_names, _variant_axis_raw_value

_MATRIX_AXIS_FIELDS = frozenset(PUBLIC_VARIANT_AXIS_FIELDS)


def _product_variant_rows(product: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in JS_STATE_PRODUCT_VARIANT_LIST_KEYS:
        raw_rows = as_list(product.get(key))
        if not raw_rows:
            continue
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            # `variants` rows are authoritative single-axis data, so use
            # _backfill_single_axis_variant_context to avoid inflating transport
            # fields. Richer sources use _backfill_nested_variant_context.
            if key != "variants":
                _backfill_nested_variant_context(row, product)
            else:
                _backfill_single_axis_variant_context(
                    row,
                    product,
                    variant_count=len(raw_rows),
                )
            rows.append(row)
    rows.extend(_nested_choice_item_variant_rows(product))
    if not rows:
        rows.extend(_variant_matrix_rows(product))
    if not rows:
        rows.extend(_mapped_size_variant_rows(product))
    if not rows:
        rows.extend(_option_group_variant_rows(product))
    return rows

def _mapped_size_variant_rows(product: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sizes = product.get("sizes")
    if not isinstance(raw_sizes, dict):
        return []
    rows: list[dict[str, Any]] = []
    for size_key, item in raw_sizes.items():
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if row.get("size") in (None, "", [], {}):
            row["size"] = (
                text_or_none(item.get("title"))
                or text_or_none(item.get("displayName"))
                or text_or_none(item.get("name"))
                or text_or_none(size_key)
            )
        _backfill_single_axis_variant_context(row, product)
        rows.append(row)
    return rows

def _option_group_variant_rows(product: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_key in JS_STATE_PRODUCT_OPTION_GROUP_KEYS:
        for group in as_list(product.get(group_key)):
            if not isinstance(group, dict):
                continue
            axis_name = text_or_none(
                group.get("name")
                or group.get("title")
                or group.get("label")
                or group.get("attribute_code")
                or group.get("id")
            )
            if not axis_name:
                continue
            for value_key in JS_STATE_OPTION_GROUP_VALUE_KEYS:
                values = as_list(group.get(value_key))
                if values:
                    break
            else:
                values = []
            for item in values:
                if not isinstance(item, dict):
                    continue
                axis_value = (
                    text_or_none(item.get("label"))
                    or text_or_none(item.get("name"))
                    or text_or_none(item.get("displayValue"))
                    or text_or_none(item.get("value"))
                    or text_or_none(item.get("index"))
                )
                if not axis_value:
                    continue
                row = dict(item)
                row["name"] = axis_name
                row["value"] = axis_value
                simple_id = text_or_none(
                    item.get("simple_id") or item.get("simpleId") or item.get("variantId")
                )
                if simple_id and row.get("id") in (None, "", [], {}):
                    row["id"] = simple_id
                rows.append(row)
    return rows

def _nested_choice_item_variant_rows(product: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for core_product in as_list(product.get("coreProducts")):
        if not isinstance(core_product, dict):
            continue
        for choice in as_list(core_product.get("coreChoices")):
            if not isinstance(choice, dict):
                continue
            color_family = choice.get("colorFamily")
            color = (
                text_or_none(choice.get("displayColorDescription"))
                or (
                    text_or_none(color_family.get("label"))
                    if isinstance(color_family, dict)
                    else None
                )
            )
            image_url = _choice_primary_image(choice)
            for item in as_list(choice.get("items")):
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                if color and row.get("color") in (None, "", [], {}):
                    row["color"] = color
                size = _variant_axis_raw_value(row, "size")
                if size and row.get("size") in (None, "", [], {}):
                    row["size"] = size
                if image_url and row.get("image") in (None, "", [], {}):
                    row["image"] = image_url
                rows.append(row)
    return rows

def _choice_primary_image(choice: dict[str, Any]) -> str | None:
    for shot in as_list(choice.get("orderedShots")):
        if not isinstance(shot, dict):
            continue
        image_url = text_or_none(shot.get("imageUrl"))
        if image_url:
            return image_url
    return None

def _backfill_nested_variant_context(
    variant: dict[str, Any],
    product: dict[str, Any],
) -> None:
    for target_key, product_keys in {
        "color": ("color", "colour"),
        "currencyCode": ("currencyCode", "currency", "priceCurrency"),
        "compareAtPrice": ("compareAtPrice", "compare_at_price"),
        "featuredImage": ("featuredMedia", "featured_image", "image"),
        "url": (
            "url",
            "href",
            "onlineStoreUrl",
            "online_store_url",
            "productUrl",
            "product_url",
            "canonicalUrl",
            "canonical_url",
        ),
    }.items():
        if variant.get(target_key) not in (None, "", [], {}):
            continue
        for product_key in product_keys:
            value = product.get(product_key)
            if value not in (None, "", [], {}):
                variant[target_key] = value
                break

def _backfill_single_axis_variant_context(
    variant: dict[str, Any],
    product: dict[str, Any],
    *,
    variant_count: int | None = None,
) -> None:
    if variant.get("color") not in (None, "", [], {}):
        return
    option_names = {
        normalized_variant_axis_key(name)
        for name in _option_names(product.get("options"))
    }
    if "color" in option_names:
        return
    if (
        "size" not in option_names
        and _variant_axis_raw_value(variant, "size") in (None, "", [], {})
        and (variant_count or 1) <= 1
    ):
        return
    color = text_or_none(product.get("color") or product.get("colour"))
    if color:
        variant["color"] = color


def _variant_matrix_rows(product: dict[str, Any]) -> list[dict[str, Any]]:
    matrix = as_list(product.get("variantMatrix"))
    if not matrix:
        return []
    axis_hints = _classification_axis_hints(product)
    rows: list[dict[str, Any]] = []
    for node in matrix:
        if not isinstance(node, dict):
            continue
        _collect_variant_matrix_rows(
            node,
            rows=rows,
            axis_hints=axis_hints,
            option_values={},
        )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        row_key = (
            text_or_none(row.get("id")) or "",
            text_or_none(row.get("url")) or "",
        )
        if row_key in seen:
            continue
        seen.add(row_key)
        deduped.append(row)
    return deduped


def _collect_variant_matrix_rows(
    node: dict[str, Any],
    *,
    rows: list[dict[str, Any]],
    axis_hints: list[tuple[str, frozenset[str]]],
    option_values: dict[str, str],
) -> None:
    current_option_values = dict(option_values)
    axis_key, axis_value = _variant_matrix_axis_value(
        node,
        axis_hints=axis_hints,
        option_values=current_option_values,
    )
    if axis_key and axis_value:
        current_option_values.setdefault(axis_key, axis_value)
    children = [child for child in as_list(node.get("elements")) if isinstance(child, dict)]
    variant_option = node.get("variantOption")
    if (node.get("isLeaf") or not children) and isinstance(variant_option, dict):
        row = _variant_matrix_row(
            variant_option,
            option_values=current_option_values,
        )
        if row:
            rows.append(row)
        return
    for child in children:
        _collect_variant_matrix_rows(
            child,
            rows=rows,
            axis_hints=axis_hints,
            option_values=current_option_values,
        )


def _variant_matrix_row(
    variant_option: dict[str, Any],
    *,
    option_values: dict[str, str],
) -> dict[str, Any] | None:
    row: dict[str, Any] = dict(option_values)
    code = text_or_none(variant_option.get("code"))
    if code:
        row["id"] = code
        row["sku"] = code
    url = text_or_none(variant_option.get("url"))
    if url:
        row["url"] = url
    price_data = variant_option.get("priceData")
    if isinstance(price_data, dict):
        value = price_data.get("value")
        if value not in (None, "", [], {}):
            row["price"] = value
        currency = text_or_none(price_data.get("currencyIso"))
        if currency:
            row["currency"] = currency
    stock = variant_option.get("stock")
    if isinstance(stock, dict):
        stock_level = stock.get("stockLevel")
        if stock_level not in (None, "", [], {}):
            try:
                row["stock_quantity"] = int(str(stock_level).strip())
            except (TypeError, ValueError):
                # Non-numeric stock level; leave stock_quantity unset.
                pass
        status = text_or_none(stock.get("stockLevelStatus"))
        if status:
            lowered = status.casefold()
            if lowered == "instock":
                row["availability"] = "in_stock"
            elif lowered == "outofstock":
                row["availability"] = "out_of_stock"
    # Variant-matrix rows without any public axis value are transport-only blobs.
    # They are ambiguous in public output even when they carry sku/url/price.
    return (
        row
        if any(value for key, value in row.items() if key in _MATRIX_AXIS_FIELDS)
        else None
    )


def _variant_matrix_axis_value(
    node: dict[str, Any],
    *,
    axis_hints: list[tuple[str, frozenset[str]]],
    option_values: dict[str, str],
) -> tuple[str | None, str | None]:
    value_category = node.get("variantValueCategory")
    if not isinstance(value_category, dict):
        return None, None
    raw_value = text_or_none(value_category.get("name")) or text_or_none(
        value_category.get("label")
    )
    if not raw_value:
        return None, None
    parent_category = node.get("parentVariantCategory")
    axis_candidates = [
        text_or_none(parent_category.get("name")) if isinstance(parent_category, dict) else None,
        text_or_none(value_category.get("label")),
        text_or_none(value_category.get("description")),
    ]
    for candidate in axis_candidates:
        axis_key = normalized_variant_axis_key(candidate)
        if axis_key in PUBLIC_VARIANT_AXIS_FIELDS and axis_key not in option_values:
            return axis_key, raw_value
    normalized_value = clean_text(raw_value).casefold()
    for axis_key, values in axis_hints:
        if axis_key in option_values:
            continue
        if normalized_value in values:
            return axis_key, raw_value
    return None, None


def _classification_axis_hints(product: dict[str, Any]) -> list[tuple[str, frozenset[str]]]:
    hints: list[tuple[str, frozenset[str]]] = []
    for classification in as_list(product.get("classifications")):
        if not isinstance(classification, dict):
            continue
        for feature in as_list(classification.get("features")):
            if not isinstance(feature, dict):
                continue
            axis_key = _classification_feature_axis_key(feature)
            if not axis_key:
                continue
            values = frozenset(
                clean_text(feature_value.get("value")).casefold()
                for feature_value in as_list(feature.get("featureValues"))
                if isinstance(feature_value, dict)
                if clean_text(feature_value.get("value"))
            )
            if values:
                hints.append((axis_key, values))
    return hints


def _classification_feature_axis_key(feature: dict[str, Any]) -> str | None:
    for raw_name in (
        feature.get("name"),
        feature.get("code"),
    ):
        cleaned = clean_text(raw_name).casefold()
        if not cleaned:
            continue
        for axis_key in ("color", "size", "length", "fit"):
            if axis_key in cleaned:
                return axis_key
    return None
