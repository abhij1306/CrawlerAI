from __future__ import annotations

__all__ = (
    "sanitize_detail_placeholder_scalars",
    "sanitize_detail_identity_scalars",
    "detail_title_looks_like_placeholder",
)

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse


from app.services.config.extraction_rules import (
    CANDIDATE_PLACEHOLDER_VALUES,
    CATEGORY_PLACEHOLDER_VALUES,
    COLOR_KEYWORD_PATTERN,
    DETAIL_BRAND_DESCRIPTION_PATTERNS,
    DETAIL_BRAND_HOST_FALLBACKS,
    DETAIL_BRAND_NUMERIC_PREFIX_ALLOWLIST,
    DETAIL_BRAND_PREFIX_CONTINUATION_TOKENS,
    DETAIL_BRAND_PREFIX_STOP_TOKENS,
    DETAIL_BRAND_SUFFIX_REJECT_TOKENS,
    DETAIL_BRAND_TITLE_PREFIX_MAX_WORDS,
    DETAIL_BRAND_TITLE_SUFFIX_PATTERN,
    DETAIL_BREADCRUMB_SEPARATOR_LABELS,
    DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO,
    DETAIL_CATEGORY_BRANCH_STOP_TOKENS,
    DETAIL_CATEGORY_LABEL_PREFIXES,
    DETAIL_CATEGORY_UI_TOKENS,
    DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX,
    DETAIL_NON_APPAREL_GENDER_DROP_CATEGORIES,
    DETAIL_NON_APPAREL_GENDER_DROP_URL_TOKENS,
    DETAIL_QUOTED_COLOR_PATTERN,
    DETAIL_SIZE_GUIDE_ALLOWED_HEADER_KEYS,
    DETAIL_SIZE_GUIDE_CONTEXT_TOKENS,
    DETAIL_TITLE_LEADING_SKU_PREFIX_PATTERN,
    DETAIL_TITLE_TRAILING_SIZE_VALUES,
)
from app.services.shared.field_coerce import (
    clean_text,
    coerce_brand_text,
    coerce_structured_scalar,
    is_title_noise,
    text_or_none,
)
from app.services.shared.text_coerce import slug_tokens
from app.services.extract.detail.identity.core import (
    detail_identity_codes_from_url as _detail_identity_codes_from_url,
    detail_slug_title_fallback_from_url as _detail_slug_title_fallback_from_url,
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
_DETAIL_TITLE_LEADING_SKU_PREFIX_RE = re.compile(
    str(DETAIL_TITLE_LEADING_SKU_PREFIX_PATTERN), re.I
)


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
        _sanitize_detail_category(record, identity_url=identity_url)
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
    _sanitize_detail_scalar_size(record)
    _sanitize_detail_color_redundant_repeat(record)
    _normalize_detail_tables(record)


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
    _drop_gender_for_non_apparel_category(record)
    _repair_detail_title_from_requested_identity(record, identity_url=identity_url)
    _repair_missing_detail_brand(record, identity_url=identity_url)
    _repair_detail_brand_from_host_fallback(record, identity_url=identity_url)
    _prefer_numeric_title_prefix_brand(record, identity_url=identity_url)
    _sanitize_detail_title_noise(record)
    _sanitize_detail_category(record, identity_url=identity_url)
    _repair_detail_color_from_title(record)
    _repair_detail_color_from_description(record)
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
        fallback_title = _detail_slug_title_fallback_from_url(identity_url)
        if fallback_title and not _fallback_title_is_low_signal(fallback_title):
            record["title"] = (
                fallback_title.title() if fallback_is_safe else fallback_title
            )
            field_sources = record.setdefault("_field_sources", {})
            field_sources["title"] = ["url_slug"]


# Categories that indicate a non-apparel product. Gender ("Women"/"Men") is
# meaningless for these and leaks animal sex or product-intended context
# (e.g. Petco "Female Blue Crowntail Betta" -> gender: "Women") when the
# title contains "male" or "female". The frozensets live in the centralized
# extraction_rules config module (see DETAIL_NON_APPAREL_GENDER_DROP_*).


def _drop_gender_for_non_apparel_category(record: dict[str, Any]) -> None:
    if not text_or_none(record.get("gender")):
        return
    category = clean_text(record.get("category")).lower()
    if category:
        category_tokens = {
            token.strip()
            for token in re.split(r"[/|>›»→|]+", category)
            if token.strip()
        }
        if category_tokens & DETAIL_NON_APPAREL_GENDER_DROP_CATEGORIES:
            record.pop("gender", None)
            field_sources = record.get("_field_sources")
            if isinstance(field_sources, dict):
                field_sources.pop("gender", None)
            return
    source_url = clean_text(record.get("source_url") or record.get("url")).lower()
    if source_url:
        url_tokens = set(re.split(r"[-/_.?=&#]+", source_url))
        url_tokens.discard("-")
        if url_tokens & DETAIL_NON_APPAREL_GENDER_DROP_URL_TOKENS:
            record.pop("gender", None)
            field_sources = record.get("_field_sources")
            if isinstance(field_sources, dict):
                field_sources.pop("gender", None)


def _repair_missing_detail_brand(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> None:
    if text_or_none(record.get("brand")) or record.get(
        "_irrelevant_detail_structured_product"
    ):
        return
    # Try the most specific (title-suffix, title-prefix) sources first, then
    # fall back to the more generic host-based repair. The host path used
    # to run before title-prefix, which caused retailers like END. Clothing
    # to be labelled "END." instead of the product-line brand "47" in
    # the title prefix (which is in DETAIL_BRAND_NUMERIC_PREFIX_ALLOWLIST).
    candidates = (
        _brand_from_title_suffix(record),
        _brand_from_title_prefix(record, identity_url=identity_url),
        _brand_from_host(identity_url),
        _brand_from_description(record),
    )
    for candidate in candidates:
        brand = coerce_brand_text(candidate)
        if not brand:
            continue
        record["brand"] = brand
        field_sources = record.setdefault("_field_sources", {})
        if isinstance(field_sources, dict):
            field_sources["brand"] = ["identity_repair"]
        return


def _brand_from_title_suffix(record: dict[str, Any]) -> str | None:
    title = clean_text(record.get("title"))
    if not title:
        return None
    match = re.search(str(DETAIL_BRAND_TITLE_SUFFIX_PATTERN), title)
    if match is None:
        return None
    candidate = clean_text(match.group("brand"))
    lowered = candidate.casefold()
    if (
        not candidate
        or any(token in lowered for token in DETAIL_BRAND_SUFFIX_REJECT_TOKENS)
        or re.fullmatch(str(COLOR_KEYWORD_PATTERN), candidate, flags=re.I)
    ):
        return None
    return candidate


# skipcq: PY-R1000
def _brand_from_title_prefix(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> str | None:
    title = clean_text(record.get("title"))
    title_parts = slug_tokens(title)
    path_parts = slug_tokens(urlparse(str(identity_url or "")).path)
    if not title_parts or not path_parts:
        return None
    first = title_parts[0]
    if first in DETAIL_BRAND_PREFIX_STOP_TOKENS:
        return None
    if first not in path_parts:
        return None
    raw_words = [word for word in re.findall(r"[A-Za-z0-9&'.-]+", title) if word]
    if not raw_words:
        return None
    if (
        raw_words[0].isdigit()
        and 2 <= len(raw_words[0]) <= 3
        and raw_words[0] in path_parts
    ):
        if raw_words[0] not in DETAIL_BRAND_NUMERIC_PREFIX_ALLOWLIST:
            return None
        return raw_words[0]
    max_words = max(1, int(DETAIL_BRAND_TITLE_PREFIX_MAX_WORDS))
    continuation_tokens = set(DETAIL_BRAND_PREFIX_CONTINUATION_TOKENS or ())
    take = 1
    while (
        take < min(max_words, len(title_parts), len(raw_words))
        and title_parts[take] in continuation_tokens
    ):
        take += 1
    if take == 1 and first not in DETAIL_BRAND_NUMERIC_PREFIX_ALLOWLIST:
        return None
    candidate_tokens = title_parts[:take]
    if not _tokens_appear_contiguously(path_parts, candidate_tokens):
        return None
    return " ".join(word.strip() for word in raw_words[:take] if word.strip())


def _repair_detail_brand_from_host_fallback(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> None:
    fallback = coerce_brand_text(_brand_from_host(identity_url))
    if not fallback:
        return
    current = text_or_none(record.get("brand"))
    title_prefix_brand = _brand_from_title_prefix(record, identity_url=identity_url)
    if (
        current
        and title_prefix_brand
        and _brand_value_is_numeric_prefix_allowlist_match(title_prefix_brand)
        and not _brand_values_look_equivalent(current, title_prefix_brand)
    ):
        record["brand"] = title_prefix_brand
        field_sources = record.setdefault("_field_sources", {})
        if isinstance(field_sources, dict):
            field_sources["brand"] = ["title_prefix_identity_repair"]
        return
    if current and (
        current.casefold() == fallback.casefold()
        or _brand_values_look_equivalent(current, fallback)
    ):
        if title_prefix_brand and _brand_value_is_numeric_prefix_allowlist_match(
            title_prefix_brand
        ):
            record["brand"] = title_prefix_brand
            field_sources = record.setdefault("_field_sources", {})
            if isinstance(field_sources, dict):
                field_sources["brand"] = ["title_prefix_identity_repair"]
        return
    if current and not _brand_value_is_weak_title_prefix(current, record):
        return
    # When the title-prefix path already produced a numeric-prefix match
    # (e.g. "47" on endclothing.com), the host label ("END.") is the
    # store name, not the product brand. Keep the numeric value.
    if current and _brand_value_is_numeric_prefix_allowlist_match(current):
        return
    record["brand"] = fallback
    field_sources = record.setdefault("_field_sources", {})
    if isinstance(field_sources, dict):
        field_sources["brand"] = ["host_identity_repair"]


def _prefer_numeric_title_prefix_brand(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> None:
    candidate = _brand_from_title_prefix(record, identity_url=identity_url)
    if not candidate or not _brand_value_is_numeric_prefix_allowlist_match(candidate):
        return
    current = text_or_none(record.get("brand"))
    if current and _brand_values_look_equivalent(current, candidate):
        return
    record["brand"] = candidate
    field_sources = record.setdefault("_field_sources", {})
    if isinstance(field_sources, dict):
        field_sources["brand"] = ["title_prefix_identity_repair"]


def _brand_value_is_numeric_prefix_allowlist_match(value: str) -> bool:
    return value.strip() in (DETAIL_BRAND_NUMERIC_PREFIX_ALLOWLIST or set())


def _brand_values_look_equivalent(left: str, right: str) -> bool:
    return re.sub(r"[^a-z0-9]+", "", left.casefold()) == re.sub(
        r"[^a-z0-9]+",
        "",
        right.casefold(),
    )


def _brand_value_is_weak_title_prefix(value: str, record: dict[str, Any]) -> bool:
    title = clean_text(record.get("title"))
    if not title:
        return False
    brand_tokens = slug_tokens(value)
    title_tokens = slug_tokens(title)
    if not brand_tokens or not title_tokens:
        return False
    return title_tokens[: len(brand_tokens)] == brand_tokens


def _sanitize_detail_title_noise(record: dict[str, Any]) -> None:
    title = clean_text(record.get("title"))
    if not title:
        return
    title = _dedupe_repeated_semicolon_title(title)
    title = clean_text(title.lstrip("+").strip())
    title = _strip_leading_sku_title_prefix(title, record)
    title = _strip_trailing_title_variant_params(title, record)
    if is_title_noise(title):
        title = ""
    if title:
        record["title"] = title
        return
    record.pop("title", None)
    field_sources = record.get("_field_sources")
    if isinstance(field_sources, dict):
        field_sources.pop("title", None)


def _dedupe_repeated_semicolon_title(title: str) -> str:
    parts = [clean_text(part) for part in title.split(";") if clean_text(part)]
    if len(parts) == 2 and parts[0].casefold() == parts[1].casefold():
        return parts[0]
    return title


def _strip_leading_sku_title_prefix(title: str, record: dict[str, Any]) -> str:
    brand = clean_text(record.get("brand"))
    if not brand:
        return title
    parts = title.split(" ", 1)
    if len(parts) != 2:
        return title
    prefix, rest = clean_text(parts[0]), clean_text(parts[1])
    if not prefix or not rest:
        return title
    if not _DETAIL_TITLE_LEADING_SKU_PREFIX_RE.fullmatch(prefix):
        return title
    if not re.search(r"[A-Za-z]", prefix) or not re.search(r"\d", prefix):
        return title
    if not rest.casefold().startswith(brand.casefold()):
        return title
    return rest


def _strip_trailing_title_variant_params(title: str, record: dict[str, Any]) -> str:
    parts = [clean_text(part) for part in re.split(r"\s[-\u2013\u2014]\s", title)]
    if len(parts) < 3:
        return title
    trailing_size = parts[-1]
    trailing_color = parts[-2]
    record_size = clean_text(record.get("size"))
    size_values = {
        clean_text(value).casefold()
        for value in tuple(DETAIL_TITLE_TRAILING_SIZE_VALUES or ())
        if clean_text(value)
    }
    if record_size:
        size_values.add(record_size.casefold())
    size_matches = trailing_size.casefold() in size_values
    color_matches = bool(
        trailing_color
        and (
            trailing_color.casefold() == clean_text(record.get("color")).casefold()
            or re.fullmatch(str(COLOR_KEYWORD_PATTERN), trailing_color, flags=re.I)
        )
    )
    if size_matches and color_matches:
        return clean_text(" - ".join(parts[:-2]))
    return title


def _tokens_appear_contiguously(tokens: list[str], needle: list[str]) -> bool:
    if not tokens or not needle or len(needle) > len(tokens):
        return False
    return any(
        tokens[index : index + len(needle)] == needle for index in range(len(tokens))
    )


def _brand_from_host(identity_url: str) -> str | None:
    host = (urlparse(str(identity_url or "")).hostname or "").casefold()
    if not host:
        return None
    labels = [label for label in host.split(".") if label and label != "www"]
    registrable_label = labels[-2] if len(labels) >= 2 else labels[0] if labels else ""
    if registrable_label in DETAIL_BRAND_HOST_FALLBACKS:
        return str(DETAIL_BRAND_HOST_FALLBACKS[registrable_label])
    return None


def _brand_from_description(record: dict[str, Any]) -> str | None:
    description = clean_text(record.get("description"))
    if not description:
        return None
    for pattern in tuple(DETAIL_BRAND_DESCRIPTION_PATTERNS or ()):
        match = re.search(str(pattern), description)
        if match is not None:
            return clean_text(match.group("brand"))
    return None


def _repair_detail_color_from_description(record: dict[str, Any]) -> None:
    description = clean_text(record.get("description"))
    if not description:
        return
    matches = [
        clean_text(match.group("color"))
        for match in re.finditer(str(DETAIL_QUOTED_COLOR_PATTERN), description)
        if clean_text(match.group("color"))
    ]
    if not matches:
        return
    current = clean_text(record.get("color"))
    field_sources = record.get("_field_sources")
    color_sources = (
        field_sources.get("color") if isinstance(field_sources, dict) else None
    )
    description_only_sources = {"description_color_repair", "description"}
    if current and (
        not isinstance(color_sources, list)
        or any(str(source) not in description_only_sources for source in color_sources)
    ):
        return
    if current and current.casefold() in {value.casefold() for value in matches}:
        return
    color = matches[0]
    record["color"] = color
    field_sources = record.setdefault("_field_sources", {})
    if isinstance(field_sources, dict):
        field_sources["color"] = ["description_color_repair"]


def _repair_detail_color_from_title(record: dict[str, Any]) -> None:
    title = clean_text(record.get("title"))
    if not title:
        return
    parts = [
        clean_text(part)
        for part in re.split(r"\s+[-–—]\s+|\s+\|\s+", title)
        if clean_text(part)
    ]
    candidate = parts[-1] if len(parts) >= 2 else _quoted_title_color(title)
    if not candidate:
        return
    if len(candidate.split()) > 4 or not re.search(
        str(COLOR_KEYWORD_PATTERN),
        candidate,
        flags=re.I,
    ):
        return
    current = clean_text(record.get("color"))
    if current and current.casefold() == candidate.casefold():
        return
    record["color"] = candidate
    field_sources = record.setdefault("_field_sources", {})
    if isinstance(field_sources, dict):
        field_sources["color"] = ["title_color_repair"]


def _quoted_title_color(title: str) -> str:
    matches = [
        clean_text(match.group(1))
        for match in re.finditer(r"['\"]([^'\"]{3,40})['\"]", title)
        if clean_text(match.group(1))
    ]
    if not matches:
        return ""
    candidate = matches[-1]
    if len(candidate.split()) > 4:
        return ""
    if not re.search(str(COLOR_KEYWORD_PATTERN), candidate, flags=re.I):
        return ""
    return candidate


# Detect a `color` value whose payload is a description + redundant
# "Color: <repeat>" suffix (Sephora, J.Crew product detail copy). The
# upstream selector / JS-state pass sometimes glues the swatch description
# and a `Color: <name> - <description>` repeat together. Strip the
# duplicate, prefer the head segment, and keep the original as a fallback.
_COLOR_REDUNDANT_REPEAT_RE = re.compile(
    r"\b(?:color|colour)\s*:\s*(.+)$",
    re.I,
)


def _sanitize_detail_color_redundant_repeat(record: dict[str, Any]) -> None:
    color = record.get("color")
    if not isinstance(color, str):
        return
    cleaned = clean_text(color)
    if not cleaned or len(cleaned) < 16:
        return
    match = _COLOR_REDUNDANT_REPEAT_RE.search(cleaned)
    if not match:
        return
    head, _, tail = cleaned.partition(match.group(0))
    head = clean_text(head.rstrip(" -–—:|"))
    tail_value = clean_text(match.group(1))
    if not head or not tail_value:
        return
    # The tail often reads "Color: <head> - <description>". Treat it as a
    # redundant repeat when the tail begins with the same head words.
    head_prefix = head[: min(len(head), 60)].casefold()
    tail_prefix = tail_value[: min(len(tail_value), 60)].casefold()
    if head_prefix and tail_prefix.startswith(head_prefix[:20]):
        record["color"] = head
        return
    # Otherwise just trim the trailing "Color: …" repeat and keep the head
    # even if it doesn't match the tail verbatim.
    record["color"] = head


def _fallback_title_is_low_signal(title: object) -> bool:
    text = clean_text(title)
    return bool(
        not text
        or detail_title_looks_like_placeholder(text)
        or detail_title_value_is_low_signal(text)
        or is_title_noise(text)
    )


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


def _sanitize_detail_category(
    record: dict[str, Any],
    *,
    identity_url: str,
) -> None:
    category = clean_text(record.get("category"))
    if not category:
        return
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


def _sanitize_detail_scalar_size(record: dict[str, Any]) -> None:
    size = clean_text(record.get("size"))
    if not size:
        return
    if _scalar_size_matches_price(size, record):
        record.pop("size", None)
        return
    if not size.isdigit():
        return
    try:
        max_low_signal = int(DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX)
    except (TypeError, ValueError):
        max_low_signal = 3
    if int(size) > max_low_signal:
        return
    title_tokens = set(slug_tokens(record.get("title")))
    category_tokens = set(slug_tokens(record.get("category")))
    if {"men", "mens", "women", "womens"} & (title_tokens | category_tokens):
        record.pop("size", None)


def _scalar_size_matches_price(size: str, record: dict[str, Any]) -> bool:
    size_decimal = _decimal_scalar(size)
    if size_decimal is None:
        return False
    for field_name in ("price", "sale_price", "original_price"):
        price_decimal = _decimal_scalar(record.get(field_name))
        if price_decimal is not None and size_decimal == price_decimal:
            return True
    return False


def _decimal_scalar(value: object) -> Decimal | None:
    text = re.sub(r"[^0-9.]+", "", clean_text(value))
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


# skipcq: PY-R1000
def _normalize_detail_tables(record: dict[str, Any]) -> None:
    tables = record.get("tables")
    if not isinstance(tables, list):
        return
    normalized_tables: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        headers = list(_table_headers(table))
        rows = table.get("rows")
        if not headers or not isinstance(rows, list):
            normalized_tables.append(table)
            continue
        if _table_is_size_guide(table):
            allowed = {
                clean_text(value).casefold()
                for value in tuple(DETAIL_SIZE_GUIDE_ALLOWED_HEADER_KEYS or ())
                if clean_text(value)
            }
            headers = [header for header in headers if header.casefold() in allowed]
        normalized_rows = [
            _normalized_table_row(row, headers=headers)
            for row in rows
            if isinstance(row, dict)
        ]
        normalized_rows = [row for row in normalized_rows if row]
        if not normalized_rows:
            continue
        normalized_table = dict(table)
        normalized_table["headers"] = headers
        normalized_table["rows"] = normalized_rows
        normalized_tables.append(normalized_table)
    if normalized_tables:
        record["tables"] = normalized_tables
    else:
        record.pop("tables", None)


def _table_headers(table: dict[str, Any]) -> list[str]:
    raw_headers = table.get("headers")
    if not isinstance(raw_headers, list):
        return []
    return [clean_text(header) for header in raw_headers if clean_text(header)]


def _normalized_table_row(row: dict[str, Any], *, headers: list[str]) -> dict[str, Any]:
    values_by_header = {
        clean_text(key): value
        for key, value in row.items()
        if clean_text(key) and value not in (None, "", [], {})
    }
    return {
        header: values_by_header[header]
        for header in headers
        if values_by_header.get(header) not in (None, "", [], {})
    }


def _table_is_size_guide(table: dict[str, Any]) -> bool:
    context = clean_text(table.get("context")).casefold()
    tokens = {
        clean_text(value).casefold()
        for value in tuple(DETAIL_SIZE_GUIDE_CONTEXT_TOKENS or ())
        if clean_text(value)
    }
    return bool(context and any(token in context for token in tokens))


def _clean_detail_category_path(
    value: object,
    *,
    title: object,
    sku: object,
    page_url: str = "",
) -> str:
    value = _category_literal_scalar(value)
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
        cleaned = _strip_category_ui_suffix(cleaned, ui_tokens=ui_tokens)
        if not cleaned_parts:
            cleaned = _strip_embedded_root_suffix_from_category_head(
                cleaned,
                page_url=page_url,
            )
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
    cleaned_parts = [
        part
        for part in cleaned_parts
        if not any(
            _category_part_matches_identity(part, identity)
            for identity in identity_values
            if identity
        )
    ]
    return " > ".join(cleaned_parts)


def _strip_category_ui_suffix(value: str, *, ui_tokens: set[str]) -> str:
    cleaned = clean_text(value)
    for token in sorted(ui_tokens, key=len, reverse=True):
        match = re.search(rf"\s*:\s*{re.escape(token)}\s*$", cleaned, re.I)
        if match:
            return clean_text(cleaned[: match.start()])
    return cleaned


def _category_literal_scalar(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return value
    parsed = coerce_structured_scalar(
        text,
        keys=("name", "title", "label", "value", "text", "en"),
    )
    if parsed is None:
        return value
    return parsed


def _strip_embedded_root_suffix_from_category_head(
    value: object,
    *,
    page_url: str,
) -> str:
    text = clean_text(value)
    match = re.fullmatch(
        r"(?i)(men|mens|men's|women|womens|women's|kids|boys|girls)\s+(home|shop|store)",
        text,
    )
    if not match:
        return text
    suffix = match.group(2)
    if not detail_breadcrumb_is_root_label(suffix, page_url=page_url):
        return text
    head = match.group(1)
    canonical = {
        "mens": "Men",
        "men's": "Men",
        "womens": "Women",
        "women's": "Women",
    }.get(head.casefold())
    return canonical or head[:1].upper() + head[1:]


def _category_part_matches_identity(part: object, identity: str) -> bool:
    part_key = _category_identity_key(part)
    identity_key = _category_identity_key(identity)
    if not part_key or not identity_key:
        return False
    if part_key == identity_key:
        return True
    if len(identity_key) >= 5 and identity_key in part_key:
        return part_key.startswith(identity_key) or part_key.startswith(
            ("buy", "shop", "choose")
        )
    if min(len(part_key), len(identity_key)) < 8:
        return False
    return SequenceMatcher(None, part_key, identity_key).ratio() >= float(
        DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO
    )


def _category_identity_key(value: object) -> str:
    text = clean_text(value)
    if "<" in text and ">" in text:
        text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


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
