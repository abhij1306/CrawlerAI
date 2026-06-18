from __future__ import annotations
# ruff: noqa: F401,F403,F405

import re
from typing import Any
from urllib.parse import urlsplit

from app.services.extract.record_overlay import overlay_record

from ._common import *  # skipcq: PYL-W0614 - normalizer modules re-export shared mapper helpers.

def _merge_same_product_record(
    base_record: dict[str, Any],
    incoming: dict[str, Any],
    *,
    page_url: str,
) -> dict[str, Any]:
    merged = overlay_record(
        base_record,
        incoming,
        skip_fields={"variants", "variant_count"},
        overwrite_fields={"availability", "stock_quantity", "original_price"},
    )

    merged_variants = merge_variant_rows(
        base_record.get("variants"),
        incoming.get("variants"),
        [] if base_record.get("variants") else [_scalar_variant_row(base_record)],
        [] if incoming.get("variants") else [_scalar_variant_row(incoming)],
    )
    if merged_variants:
        merged["variants"] = merged_variants
        merged["variant_count"] = len(merged_variants)
    return compact_dict(merged)

def _merge_variant_fields(
    base_record: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(base_record)
    merged_variants = merge_variant_rows(
        base_record.get("variants"), incoming.get("variants")
    )
    if merged_variants:
        merged["variants"] = merged_variants
        merged["variant_count"] = len(merged_variants)
    return compact_dict(merged)

def _scalar_variant_row(record: dict[str, Any]) -> dict[str, Any]:
    axes = {
        field_name: record.get(field_name)
        for field_name in VARIANT_AXIS_KEYS
        if record.get(field_name) not in (None, "", [], {})
    }
    if not axes:
        return {}
    row: dict[str, Any] = dict(axes)
    for field_name in (
        "sku",
        "barcode",
        "url",
        "image_url",
        "availability",
        "stock_quantity",
        "price",
        "original_price",
        "currency",
        "product_id",
    ):
        if record.get(field_name) not in (None, "", [], {}):
            row[field_name] = record[field_name]
    return row

def _mapped_product_identity_matches(
    base_record: dict[str, Any],
    mapped: dict[str, Any],
    *,
    page_url: str,
) -> bool:
    for field_name in ("product_id", "sku", "handle"):
        base_value = text_or_none(base_record.get(field_name))
        mapped_value = text_or_none(mapped.get(field_name))
        if base_value and mapped_value:
            if base_value == mapped_value:
                return True
    base_url = text_or_none(base_record.get("url"))
    mapped_url = text_or_none(mapped.get("url"))
    if base_url and mapped_url and base_url == mapped_url:
        return True
    if _mapped_record_matches_page_url(
        mapped, page_url
    ) and _mapped_product_family_matches(base_record, mapped):
        return True
    base_title = text_or_none(base_record.get("title"))
    mapped_title = text_or_none(mapped.get("title"))
    if base_title and mapped_title and base_title == mapped_title:
        return True
    return _mapped_product_family_matches(base_record, mapped)

def _mapped_record_matches_page_url(record: dict[str, Any], page_url: str) -> bool:
    page_path = urlsplit(page_url).path.rstrip("/").lower()
    product_id = text_or_none(record.get("product_id"))
    if product_id and product_id.lower() in str(page_url or "").lower():
        return True
    for field_name in ("url", "handle"):
        value = text_or_none(record.get(field_name))
        if value and urlsplit(value).path.rstrip("/").lower() == page_path:
            return True
        if value and f"/{value.strip('/').lower()}" in page_path:
            return True
    return False

def _mapped_product_family_matches(
    base_record: dict[str, Any],
    mapped: dict[str, Any],
) -> bool:
    base_family_tokens = _family_title_tokens(base_record)
    mapped_family_tokens = _family_title_tokens(mapped)
    if not _family_title_tokens_match(base_family_tokens, mapped_family_tokens):
        return False
    base_brand = _normalized_party_name(base_record.get("brand") or base_record.get("vendor"))
    mapped_brand = _normalized_party_name(mapped.get("brand") or mapped.get("vendor"))
    if base_brand and mapped_brand and base_brand != mapped_brand:
        return False
    return _record_has_variant_family_signal(base_record) or _record_has_variant_family_signal(
        mapped
    )

def _family_title_tokens(record: dict[str, Any]) -> list[str]:
    title = clean_text(record.get("title"))
    if not title:
        return []
    drop_tokens = set()
    for raw_value in (
        record.get("brand"),
        record.get("vendor"),
        record.get("color"),
        record.get("size"),
        record.get("style"),
        record.get("material"),
        record.get("finish"),
        record.get("pattern"),
        record.get("scent"),
        record.get("flavor"),
        record.get("capacity"),
        record.get("length"),
        record.get("width"),
    ):
        drop_tokens.update(_title_tokens(raw_value))
    return [token for token in _title_tokens(title) if token not in drop_tokens]

def _normalized_party_name(value: object) -> str:
    tokens = _title_tokens(value)
    return " ".join(tokens)

def _title_tokens(value: object) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", clean_text(value).lower())
        if token and (len(token) >= 2 or token.isdigit())
    ]

def _family_title_tokens_match(
    base_tokens: list[str],
    mapped_tokens: list[str],
) -> bool:
    if len(base_tokens) < 2 or len(mapped_tokens) < 2:
        return False
    if base_tokens == mapped_tokens:
        return True
    shorter, longer = (
        (base_tokens, mapped_tokens)
        if len(base_tokens) <= len(mapped_tokens)
        else (mapped_tokens, base_tokens)
    )
    if len(longer) - len(shorter) > 1:
        return False
    return longer[: len(shorter)] == shorter or longer[-len(shorter) :] == shorter

def _record_has_variant_family_signal(record: dict[str, Any]) -> bool:
    variants = record.get("variants")
    if isinstance(variants, list) and variants:
        return True
    return any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in ("color", "size", "style", "material", "variant_count")
    )


__all__: list[str] = []
