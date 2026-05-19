from __future__ import annotations

__all__ = (
    "sanitize_detail_placeholder_scalars",
    "sanitize_detail_identity_scalars",
    "detail_title_looks_like_placeholder",
)

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any


from app.services.config.extraction_rules import (
    CANDIDATE_PLACEHOLDER_VALUES,
    CATEGORY_PLACEHOLDER_VALUES,
    DETAIL_CATEGORY_BRANCH_STOP_TOKENS,
    DETAIL_CATEGORY_LABEL_PREFIXES,
    DETAIL_CATEGORY_UI_TOKENS,
    DETAIL_BREADCRUMB_SEPARATOR_LABELS,
    DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO,
)
from app.services.shared.field_coerce import (
    clean_text,
    text_or_none,
)
from app.services.extract.detail.identity.core import (
    detail_identity_codes_from_url as _detail_identity_codes_from_url,
    detail_title_from_url as _detail_title_from_url,
    semantic_detail_identity_tokens as _semantic_detail_identity_tokens,
)
from app.services.extract.detail.assembly.raw_signals import (
    detail_breadcrumb_is_root_label,
)
from app.services.extract.detail.text.sanitizer import (
    detail_product_type_is_low_signal,
    detail_title_value_is_low_signal,
)
from app.services.config.detail_extraction_constants import (
    DETAIL_PLACEHOLDER_TITLE_PATTERNS as _DETAIL_PLACEHOLDER_TITLE_PATTERNS,
    MATERIAL_KEYWORD_TOKENS as _material_keyword_tokens,
    MERCH_CODE_PATTERN as _MERCH_CODE_PATTERN,
    ORG_SUFFIX_PATTERN as _ORG_SUFFIX_PATTERN,
    UUID_LIKE_PATTERN as _UUID_LIKE_PATTERN,
)

logger = logging.getLogger(__name__)


def sanitize_detail_placeholder_scalars(
    record: dict[str, Any], *, identity_url: str = ""
) -> None:
    title = clean_text(record.get("title"))
    if detail_title_looks_like_placeholder(title) or detail_title_value_is_low_signal(
        title
    ):
        record.pop("title", None)
        record["_placeholder_title_removed"] = True
    category = clean_text(record.get("category"))
    if category.lower() in CATEGORY_PLACEHOLDER_VALUES:
        record.pop("category", None)
    elif category:
        cleaned_category = _clean_detail_category_path(
            category,
            title=record.get("title"),
            sku=record.get("sku"),
            page_url=identity_url,
        )
        if cleaned_category:
            record["category"] = cleaned_category
        else:
            record.pop("category", None)
    features = record.get("features")
    if isinstance(features, list):
        if not any(text_or_none(item) for item in features):
            record.pop("features", None)
    else:
        feature_text = text_or_none(features)
        if feature_text and _feature_text_is_json_object(feature_text):
            record.pop("features", None)
    product_type = text_or_none(record.get("product_type"))
    if detail_product_type_is_low_signal(product_type):
        record.pop("product_type", None)
    materials = text_or_none(record.get("materials"))
    if materials and _materials_value_looks_like_org_name(materials):
        record.pop("materials", None)
    product_attributes = record.get("product_attributes")
    if isinstance(product_attributes, dict):
        cleaned_attributes = {
            str(key): value
            for key, value in product_attributes.items()
            if not _detail_scalar_value_is_placeholder(value)
        }
        if cleaned_attributes:
            record["product_attributes"] = cleaned_attributes
        else:
            record.pop("product_attributes", None)

def _feature_text_is_json_object(value: str) -> bool:
    text = clean_text(value)
    if not (text.startswith("{") and text.endswith("}")):
        return False
    try:
        return isinstance(json.loads(text), dict)
    except (TypeError, ValueError):
        return False


def sanitize_detail_identity_scalars(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> None:
    brand = text_or_none(record.get("brand"))
    vendor = text_or_none(record.get("vendor"))
    if brand and vendor and brand.casefold() == vendor.casefold():
        record.pop("vendor", None)
    sku = text_or_none(record.get("sku"))
    preferred_code = _preferred_detail_merch_code(record, identity_url=identity_url)
    if preferred_code and (not sku or _looks_like_uuid(sku)):
        record["sku"] = preferred_code
        if text_or_none(record.get("part_number")) in (None, ""):
            record["part_number"] = preferred_code
    _repair_detail_title_from_requested_identity(record, identity_url=identity_url)
    placeholder_title_removed = bool(record.pop("_placeholder_title_removed", False))
    if not text_or_none(record.get("title")):
        fallback_is_safe = _detail_title_fallback_is_safe(record)
        description_backed = bool(text_or_none(record.get("description")))
        if (
            placeholder_title_removed
            and not fallback_is_safe
            and not description_backed
        ):
            return
        fallback_title = _detail_title_from_url(identity_url)
        if fallback_title:
            record["title"] = (
                fallback_title.title() if fallback_is_safe else fallback_title
            )
            field_sources = record.setdefault("_field_sources", {})
            field_sources["title"] = ["url_slug"]

def _repair_detail_title_from_requested_identity(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> None:
    title = clean_text(record.get("title"))
    fallback_title = _detail_title_from_url(identity_url)
    if not title or not fallback_title:
        return
    requested_tokens = _semantic_detail_identity_tokens(fallback_title)
    title_tokens = _semantic_detail_identity_tokens(title)
    if len(requested_tokens) < 3 or requested_tokens & title_tokens:
        return
    supporting_text = " ".join(
        clean_text(value)
        for value in (
            record.get("description"),
            record.get("image_url"),
            record.get("sku"),
            record.get("part_number"),
        )
        if clean_text(value)
    )
    for variant in record.get("variants") or []:
        if isinstance(variant, dict):
            supporting_text = " ".join(
                (
                    supporting_text,
                    clean_text(variant.get("url")),
                    clean_text(variant.get("image_url")),
                    clean_text(variant.get("sku")),
                )
            )
    supporting_tokens = _semantic_detail_identity_tokens(supporting_text)
    if len(requested_tokens & supporting_tokens) < min(2, len(requested_tokens)):
        return
    record["title"] = fallback_title.title()
    field_sources = record.setdefault("_field_sources", {})
    if isinstance(field_sources, dict):
        field_sources["title"] = ["url_slug_identity_repair"]


def _detail_title_fallback_is_safe(record: dict[str, Any]) -> bool:
    return any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in (
            "price",
            "original_price",
            "sku",
            "part_number",
            "barcode",
            "brand",
            "image_url",
            "availability",
            "product_attributes",
            "variants",
        )
    )


def _preferred_detail_merch_code(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> str | None:
    expected_codes = _detail_identity_codes_from_url(identity_url)
    raw_values = (
        record.get("sku"),
        record.get("part_number"),
        record.get("product_details"),
        record.get("description"),
        record.get("url"),
        identity_url,
    )
    fallback: str | None = None
    for raw_value in raw_values:
        text = text_or_none(raw_value)
        if not text:
            continue
        for match in _MERCH_CODE_PATTERN.findall(text):
            candidate = match.upper()
            if candidate.count("-") > 2:
                continue
            normalized = re.sub(r"[^A-Z0-9]+", "", candidate)
            if (
                len(normalized) < 8
                or not re.search(r"[A-Z]", normalized)
                or not re.search(r"\d", normalized)
            ):
                continue
            if fallback is None:
                fallback = candidate
            if not expected_codes or normalized in expected_codes:
                return candidate
    return fallback


def _looks_like_uuid(value: str) -> bool:
    return bool(_UUID_LIKE_PATTERN.fullmatch(str(value or "").strip()))


def _detail_scalar_value_is_placeholder(value: object) -> bool:
    cleaned = clean_text(value).lower()
    if not cleaned:
        return True
    if cleaned in {str(item).strip().lower() for item in CANDIDATE_PLACEHOLDER_VALUES}:
        return True
    return cleaned in {"category", "default title", "uncategorized"}


def _clean_detail_category_path(
    value: object,
    *,
    title: object,
    sku: object,
    page_url: str = "",
) -> str:
    parts = [
        clean_text(part)
        for part in re.split(r"\s*(?:>|/|›|»|→|\|)\s*", clean_text(value))
        if clean_text(part)
    ]
    if not parts:
        return ""
    ui_tokens = {
        clean_text(token).casefold()
        for token in tuple(DETAIL_CATEGORY_UI_TOKENS or ())
        if clean_text(token)
    }
    prefixes = tuple(
        str(prefix).casefold() for prefix in tuple(DETAIL_CATEGORY_LABEL_PREFIXES or ())
    )
    branch_stop_tokens = {
        clean_text(token).casefold()
        for token in tuple(DETAIL_CATEGORY_BRANCH_STOP_TOKENS or ())
        if clean_text(token)
    }
    cleaned_parts: list[str] = []
    strip_chars = (
        "".join(map(str, DETAIL_BREADCRUMB_SEPARATOR_LABELS or ())) + " \t\n\r"
    )
    for part in parts:
        cleaned = clean_text(part.strip(strip_chars))
        lowered = cleaned.casefold()
        if (
            not cleaned
            or lowered in ui_tokens
            or any(lowered.startswith(prefix) for prefix in prefixes)
        ):
            continue
        if lowered in branch_stop_tokens:
            break
        cleaned_parts.append(cleaned)
    while cleaned_parts and detail_breadcrumb_is_root_label(
        cleaned_parts[0], page_url=page_url
    ):
        cleaned_parts.pop(0)

    identity_values = [clean_text(title), clean_text(sku)]
    while cleaned_parts and any(
        _category_part_matches_identity(cleaned_parts[-1], identity)
        for identity in identity_values
        if identity
    ):
        cleaned_parts.pop()
    return " > ".join(cleaned_parts)


def _category_part_matches_identity(part: object, identity: str) -> bool:
    part_key = re.sub(r"[^a-z0-9]+", "", clean_text(part).casefold())
    identity_key = re.sub(r"[^a-z0-9]+", "", clean_text(identity).casefold())
    if not part_key or not identity_key:
        return False
    if part_key == identity_key:
        return True
    if min(len(part_key), len(identity_key)) < 8:
        return False
    return SequenceMatcher(None, part_key, identity_key).ratio() >= float(
        DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO
    )


def detail_title_looks_like_placeholder(title: str) -> bool:
    normalized = clean_text(title)
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered in {"404"}:
        return True
    return any(
        pattern.search(normalized) for pattern in _DETAIL_PLACEHOLDER_TITLE_PATTERNS
    )


def _materials_value_looks_like_org_name(value: str) -> bool:
    lowered = value.lower()
    if any(token in lowered for token in _material_keyword_tokens):
        return False
    return bool(
        (_ORG_SUFFIX_PATTERN is not None and _ORG_SUFFIX_PATTERN.search(lowered))
        or re.fullmatch(r"[A-Z0-9 .,&'-]{6,}", value, re.IGNORECASE)
    )
