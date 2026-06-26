from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable
from typing import Any

from app.core.config import variant_policy
from app.core.config.field_mappings import ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS
from app.core.records.url_identity import (
    detail_identity_codes_from_url,
    detail_url_resource_identity,
)


def path_tokens(path: str) -> set[str]:
    normalized = str(path).replace("[", "/").replace("]", "/").replace(".", "/")
    return {token.casefold() for token in normalized.split("/") if token}


def has_product_context(path: str, obj: dict) -> bool:
    keys = set(obj)
    type_name = str(obj.get("@type") or obj.get("type") or "").casefold()
    tokens = path_tokens(path)
    parts = tuple(token for token in str(path).replace(".", "/").split("/") if token)
    direct_product_path = bool(
        parts and parts[-1].casefold() in {"product", "products"}
    )
    product_keys = keys & ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS
    complete_offer = "price" in keys and bool(keys & {"currency", "currencyCode"})
    if (
        "config" in tokens
        and not direct_product_path
        and not complete_offer
        and not bool(keys & {"sku", "url", "productUrl", "product_url"})
    ):
        return False
    return (
        "product" in type_name
        or direct_product_path
        or len(product_keys) >= 2
        or bool(product_keys & {"name", "productName", "title"})
        and complete_offer
    )


def _path_is_descendant(path: str, ancestor: str) -> bool:
    if not ancestor:
        return False
    normalized = ancestor.rstrip("/")
    if not path.startswith(normalized) or len(path) == len(normalized):
        return False
    return path[len(normalized)] in "/.["


def selected_product_root_paths(
    objects: Iterable[tuple[str, Any]], final_url: str
) -> tuple[str, ...]:
    target = detail_url_resource_identity(final_url)
    if not target:
        return ()
    rows = tuple(objects)
    product_roots: set[str] = set()
    for path, obj in rows:
        if not isinstance(obj, dict):
            continue
        matches_target = any(
            value and detail_url_resource_identity(str(value)) == target
            for key in (
                "url",
                "canonicalUrl",
                "canonical_url",
                "productUrl",
                "product_url",
            )
            if (value := obj.get(key))
        )
        if not matches_target:
            continue
        ancestors = [
            candidate_path
            for candidate_path, candidate in rows
            if isinstance(candidate, dict)
            and candidate_path != path
            and _path_is_descendant(path, candidate_path)
            and has_product_context(candidate_path, candidate)
        ]
        if ancestors:
            product_roots.add(max(ancestors, key=len))
        elif has_product_context(path, obj):
            product_roots.add(path)
    return tuple(sorted(product_roots, key=lambda value: (len(value), value)))


def _normalized_cache_item_id(path_part: str) -> str | None:
    prefix, separator, encoded = str(path_part).partition(":")
    if separator != ":" or prefix.casefold() != "item" or not encoded:
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    entity, separator, item_id = decoded.partition(":")
    if separator != ":" or entity.casefold() != "item" or not item_id.isdigit():
        return None
    return item_id


def path_product_identity_conflicts(page_url: str, path: str) -> bool:
    parent_codes = set(detail_identity_codes_from_url(page_url))
    if not parent_codes:
        return False
    parts = tuple(
        part
        for part in str(path).replace("[", "/").replace("]", "/").split("/")
        if part
    )
    normalized_item_ids = {
        item_id
        for part in parts
        if (item_id := _normalized_cache_item_id(part)) is not None
    }
    if any(item_id not in parent_codes for item_id in normalized_item_ids):
        return True
    for index, part in enumerate(parts[:-1]):
        if part.casefold() not in variant_policy.VARIANT_PRODUCT_MAP_PATH_TOKENS:
            continue
        candidate = parts[index + 1]
        normalized = "".join(char for char in candidate if char.isalnum()).upper()
        if (
            len(normalized) < variant_policy.VARIANT_PRODUCT_MAP_KEY_MIN_LENGTH
            or not any(char.isalpha() for char in normalized)
            or not any(char.isdigit() for char in normalized)
        ):
            continue
        if not any(
            left == normalized or left in normalized or normalized in left
            for left in parent_codes
        ):
            return True
    return False
