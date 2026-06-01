from __future__ import annotations
# ruff: noqa: F401,F403,F405

import re
from typing import Any

from ._common import *
from ._variant_rows import _product_variant_rows

def _normalized_state_payload(state_key: str, payload: Any) -> Any:
    if state_key == "__NUXT_DATA__":
        revived = _revive_nuxt_data_array(payload)
        if revived is not None:
            return revived
    return payload

def _revive_nuxt_data_array(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, list):
        return payload if isinstance(payload, dict) else None
    data_rows: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("state"), dict):
            state.update(item.get("state") or {})
        if isinstance(item.get("data"), dict):
            data_rows.append(item["data"])
        elif "product" in item and isinstance(item.get("product"), dict):
            data_rows.append({"product": item["product"]})
    revived: dict[str, Any] = {}
    if data_rows:
        revived["data"] = data_rows
    if state:
        revived["state"] = state
    return revived or None

def _looks_like_product_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if _payload_type_is_non_product(value):
        return False
    if _looks_like_stock_price_product_payload(value):
        return True
    has_title = any(
        key in value
        for key in (
            "title",
            "name",
            "productTitle",
            "productName",
            "nameByLanguage",
            "pn",
            "copyProductTitle",
        )
    ) or bool(
        text_or_none(
            ((value.get("item") or {}).get("product_description") or {}).get("title")
        )
        if isinstance(value.get("item"), dict)
        else None
    )
    if not has_title:
        return False
    return any(
        key in value
        for key in (
            "variants",
            "availableSizes",
            "variation_hierarchy",
            "coreProducts",
            "options",
            "colors",
            "sizes",
            "prices",
            "representative",
            "product_type",
            "productType",
            "vendor",
            "brand",
            "handle",
            "price",
            "sku",
            "availability",
            "category",
            "type",
            "mrp",
            "Img",
            "offers",
            "images",
            "image",
            "media",
            "featuredImage",
            "featuredMedia",
            "description",
            "body_html",
            "onlineStoreUrl",
            "webPathAlias",
        )
    )

def _payload_type_is_non_product(value: dict[str, Any]) -> bool:
    raw_type = (
        clean_text(
            value.get("type")
            or value.get("product_type")
            or value.get("productType")
            or value.get("@type")
        )
        or ""
    ).casefold()
    if not raw_type:
        return False
    if raw_type in DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES:
        return True
    if raw_type in DETAIL_ARTIFACT_PRODUCT_TYPE_VALUES:
        return True
    return any(
        re.search(str(pattern), raw_type, re.I)
        for pattern in tuple(DETAIL_ARTIFACT_PRODUCT_TYPE_PATTERNS or ())
        if str(pattern).strip()
    )

def _looks_like_stock_price_product_payload(value: dict[str, Any]) -> bool:
    return (
        value.get("productId") not in (None, "", [], {})
        and isinstance(value.get("productPrice"), dict)
        and isinstance(value.get("variants"), list)
    )

def _find_product_payloads(
    value: Any,
    *,
    depth: int = 0,
    limit: int = int(JS_STATE_PRODUCT_PAYLOAD_LIMIT),
) -> list[dict[str, Any]]:
    if depth > limit:
        return []
    payloads: list[dict[str, Any]] = []
    if _looks_like_product_payload(value):
        payloads.append(dict(value))
    if isinstance(value, dict):
        for item in value.values():
            payloads.extend(_find_product_payloads(item, depth=depth + 1, limit=limit))
    elif isinstance(value, list):
        for item in value[: int(JS_STATE_LIST_ITERATION_LIMIT)]:
            payloads.extend(_find_product_payloads(item, depth=depth + 1, limit=limit))
    payloads.sort(key=_product_payload_score, reverse=True)
    return payloads[: int(JS_STATE_PRODUCT_PAYLOAD_LIMIT)]

def _product_payload_score(product: dict[str, Any]) -> tuple[int, ...]:
    raw_variants = _product_variant_rows(product)
    raw_options = as_list(product.get("options"))
    raw_colors = as_list(product.get("colors"))
    raw_sizes = as_list(product.get("sizes"))
    product_keys = set(product)
    strong_product_keys = {
        "variants",
        "options",
        "variation_hierarchy",
        "coreProducts",
        "colors",
        "sizes",
        "prices",
        "representative",
        "product_type",
        "productType",
        "vendor",
        "brand",
        "handle",
        "price",
        "sku",
        "availability",
        "category",
        "type",
        "productId",
        "product_id",
        "id",
        "pid",
        "legacyStyleGroupId",
        "mrp",
        "Img",
        "offers",
        "images",
        "image",
    }
    axis_signal_count = sum(
        1
        for variant in raw_variants
        if isinstance(variant, dict)
        and any(key in variant for key in VARIANT_AXIS_KEYS)
    )
    product_identifier_count = sum(
        1
        for key in ("productId", "product_id", "id", "sku", "handle")
        if product.get(key) not in (None, "", [], {})
    )
    price_signal_count = sum(
        1
        for key in ("price", "prices", "offers")
        if product.get(key) not in (None, "", [], {})
    )
    return (
        len(raw_variants),
        len(raw_options),
        len(raw_colors) + len(raw_sizes),
        axis_signal_count,
        product_identifier_count,
        price_signal_count,
        1 if product.get("images") not in (None, "", [], {}) or product.get("image") not in (None, "", [], {}) else 0,
        len(product_keys & strong_product_keys),
        len(product_keys),
    )


__all__: list[str] = []
