from __future__ import annotations

__all__ = (
    "sanitize_variant_row",
)

import json
import logging
import re
from decimal import Decimal
from functools import lru_cache
from typing import Any
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    AVAILABILITY_IN_STOCK,
    AVAILABILITY_OUT_OF_STOCK,
    AVAILABILITY_UNKNOWN,
    CANDIDATE_PLACEHOLDER_VALUES,
    CATEGORY_PLACEHOLDER_VALUES,
    DETAIL_CATEGORY_BRANCH_STOP_TOKENS,
    DETAIL_CATEGORY_LABEL_PREFIXES,
    DETAIL_CATEGORY_UI_TOKENS,
    DETAIL_BREADCRUMB_SEPARATOR_LABELS,
    DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO,
    IMAGE_FAMILY_NOISE_TOKENS,
    IMAGE_PATH_TOKENS,
    DETAIL_LOW_SIGNAL_PARENT_MIN,
    DETAIL_LOW_SIGNAL_PRICE_MAX,
    DETAIL_PRICE_COMPARISON_TOLERANCE,
    VARIANT_OPTION_LABEL_MAX_WORDS,
)
from app.services.config.variant_policy import (
    DETAIL_VARIANT_SIZE_MIN_FOR_NUMERIC_PARENT_DROP,
)
from app.services.extract.variant_normalization.contract import (
    enforce_flat_variant_public_contract,
)
from app.services.shared.field_coerce import (
    absolute_url,
    clean_text,
    extract_urls,
    text_or_none,
)
from app.services.field_url_normalization import same_site
from app.services.dom.selector_engine import dedupe_image_urls, upgrade_low_resolution_image_url
from app.services.extract.variant_axis import (
    normalized_variant_axis_key,
    variant_axis_allowed_single_tokens,
    variant_axis_name_is_semantic,
)
from app.services.extract.variant_option_value import (
    variant_option_value_matches_noise_token,
    variant_option_value_is_noise as _variant_option_value_is_noise,
)
from app.services.extract.detail.identity.core import (
    detail_identity_codes_match,
    detail_identity_codes_from_record_fields as _detail_identity_codes_from_record_fields,
    detail_identity_codes_from_url as _detail_identity_codes_from_url,
    detail_identity_tokens as _detail_identity_tokens,
    detail_title_from_url as _detail_title_from_url,
    detail_url_looks_like_product as _detail_url_looks_like_product,
    detail_url_matches_requested_identity as _detail_url_matches_requested_identity,
    record_matches_requested_detail_identity as _record_matches_requested_detail_identity,
    semantic_detail_identity_tokens as _semantic_detail_identity_tokens,
)
from app.services.extract.detail.variants.dom_extraction import (
    backfill_variants_from_dom_if_missing,
)
from app.services.extract.detail.variants.numbered_options import (
    hydrate_numbered_variant_options_from_dom,
)
from app.services.extract.detail.assembly.raw_signals import detail_breadcrumb_is_root_label
from app.services.extract.detail.price.core import (
    backfill_detail_price_from_html,
    detail_price_decimal,
    format_detail_price_decimal,
    reconcile_detail_currency_with_url,
    reconcile_detail_price_magnitudes,
    reconcile_parent_price_against_variant_range,
)
from app.services.extract.variant_normalization import normalize_variant_record
from app.services.extract.detail.text.sanitizer import (
    detail_product_type_is_low_signal,
    detail_scalar_size_is_low_signal,
    detail_title_value_is_low_signal,
    sanitize_detail_long_text_fields,
)

logger = logging.getLogger(__name__)

def _sanitize_detail_variant_payload(
    record: dict[str, Any], *, identity_url: str
) -> None:
    cleaned_variants: list[dict[str, Any]] = []
    title_hint = clean_text(record.get("title"))
    for variant in list(record.get("variants") or []):
        if not isinstance(variant, dict):
            continue
        if not sanitize_variant_row(
            variant, identity_url=identity_url, title_hint=title_hint
        ):
            continue
        cleaned_variants.append(variant)
    if _detail_variant_cluster_is_low_signal_numeric_only(cleaned_variants):
        cleaned_variants = []
    if cleaned_variants:
        record["variants"] = cleaned_variants
        record["variant_count"] = len(cleaned_variants)
    else:
        record.pop("variants", None)
        record.pop("variant_count", None)
    record.pop("selected_variant", None)
    record.pop("variant_axes", None)
    record.pop("available_sizes", None)
    for field_name in list(record):
        if re.fullmatch(r"option\d+_(?:name|values?)", str(field_name)):
            record.pop(field_name, None)
    _drop_detail_variant_scalar_noise(record)
    _drop_variant_derived_parent_axis_scalars(record)


def sanitize_variant_row(
    variant: dict[str, Any],
    *,
    identity_url: str,
    title_hint: str = "",
) -> bool:
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        cleaned_options: dict[str, str] = {}
        for axis_name, axis_value in option_values.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned_value = clean_text(axis_value)
            if not axis_key or not cleaned_value:
                continue
            if axis_key.startswith("toggle") or _variant_option_value_is_noise(
                cleaned_value
            ):
                continue
            if not variant_axis_name_is_semantic(axis_name):
                continue
            cleaned_options[axis_key] = cleaned_value
            if axis_key in {"size", "color"} and variant.get(axis_key) not in (
                None,
                "",
                [],
                {},
            ):
                variant[axis_key] = cleaned_value
        if cleaned_options:
            variant["option_values"] = cleaned_options
        else:
            variant.pop("option_values", None)
    for field_name in ("size", "color"):
        raw_value = variant.get(field_name)
        cleaned_value = clean_text(raw_value)
        if not cleaned_value:
            if raw_value in (None, "", [], {}):
                variant.pop(field_name, None)
            continue
        if _variant_option_value_is_noise(cleaned_value):
            variant.pop(field_name, None)
            continue
        if _option_value_repeats_product_title(cleaned_value, title_hint=title_hint):
            variant.pop(field_name, None)
            continue
        variant[field_name] = cleaned_value
    variant_url = text_or_none(variant.get("url"))
    if (
        variant_url
        and same_site(identity_url, variant_url)
        and _detail_url_looks_like_product(variant_url)
        and not _detail_url_matches_requested_identity(
            variant_url,
            requested_page_url=identity_url,
        )
        and not _variant_has_public_axis_or_identity_signal(variant)
    ):
        return False
    title = clean_text(variant.get("title"))
    if (
        title
        and not _variant_url_matches_requested_base(
            variant.get("url"), identity_url=identity_url
        )
        and _variant_title_looks_like_other_product(title, identity_url=identity_url)
        and not _variant_title_can_be_option_label(variant, title=title)
    ):
        return False
    image_url = text_or_none(variant.get("image_url"))
    if image_url:
        normalized_image = upgrade_low_resolution_image_url(image_url)
        if normalized_image.lower().startswith("http://"):
            normalized_image = "https://" + normalized_image[7:]
        variant["image_url"] = normalized_image
    return any(
        variant.get(field_name) not in (None, "", [], {})
        for field_name in (
            "sku",
            "variant_id",
            "barcode",
            "image_url",
            "availability",
            "option_values",
            "size",
            "color",
            *variant_axis_allowed_single_tokens,
        )
    )


def _variant_has_public_axis_or_identity_signal(variant: dict[str, Any]) -> bool:
    if any(
        clean_text(variant.get(field_name))
        for field_name in ("sku", "variant_id", "barcode", "size", "color")
    ):
        return True
    option_values = variant.get("option_values")
    if not isinstance(option_values, dict):
        return False
    return any(
        normalized_variant_axis_key(axis_name)
        and clean_text(axis_value)
        for axis_name, axis_value in option_values.items()
    )



def _variant_title_is_low_signal(title: str) -> bool:
    normalized = clean_text(title)
    return bool(normalized) and (
        normalized.isdigit()
        or variant_option_value_matches_noise_token(normalized)
        or len(normalized) <= 2
    )


def _variant_title_from_parent(parent_title: str, row: dict[str, Any]) -> str | None:
    if not parent_title:
        return None
    option_values = row.get("option_values")
    values: list[str] = []
    if isinstance(option_values, dict):
        values.extend(
            clean_text(value) for value in option_values.values() if clean_text(value)
        )
    for field_name in ("size", "color"):
        value = clean_text(row.get(field_name))
        if value and value not in values:
            values.append(value)
    if values:
        return f"{parent_title} - {' / '.join(values)}"
    return parent_title


def _variant_url_matches_requested_base(value: object, *, identity_url: str) -> bool:
    variant_url = text_or_none(value)
    if not variant_url or not identity_url or not same_site(identity_url, variant_url):
        return False
    requested = urlparse(identity_url)
    candidate = urlparse(variant_url)
    return requested.path.rstrip("/") == candidate.path.rstrip("/")


def _detail_variant_row_is_low_signal_numeric_only(variant: object) -> bool:
    if not isinstance(variant, dict):
        return False
    if any(
        clean_text(variant.get(field_name))
        for field_name in ("variant_id", "barcode", "image_url", "title")
    ):
        return False
    if clean_text(variant.get("url")):
        return False
    option_values = variant.get("option_values")
    if not isinstance(option_values, dict) or set(option_values) != {"size"}:
        return False
    size_value = clean_text(option_values.get("size") or variant.get("size"))
    return bool(size_value) and size_value.isdigit() and int(size_value) <= 4


def _detail_variant_cluster_is_low_signal_numeric_only(
    variants: list[dict[str, Any]],
) -> bool:
    return bool(variants) and all(
        _detail_variant_row_is_low_signal_numeric_only(variant) for variant in variants
    )


def _variant_title_looks_like_other_product(title: str, *, identity_url: str) -> bool:
    candidate: dict[str, object] = {"title": title}
    return not _record_matches_requested_detail_identity(
        candidate,
        requested_page_url=identity_url,
    )


def _variant_title_can_be_option_label(variant: dict[str, Any], *, title: str) -> bool:
    title_words = clean_text(title).split()
    if len(title_words) > int(VARIANT_OPTION_LABEL_MAX_WORDS):
        return False
    has_option_axis = any(
        variant.get(field_name) not in (None, "", [], {})
        for field_name in (
            "option_values",
            "size",
            "color",
        )
    )
    if has_option_axis:
        return True
    return len(title_words) == 1 and any(
        variant.get(field_name) not in (None, "", [], {})
        for field_name in ("sku", "variant_id", "barcode")
    )


def _drop_detail_variant_scalar_noise(record: dict[str, Any]) -> None:
    for field_name in list(record.keys()):
        if str(field_name).startswith("toggle_"):
            record.pop(field_name, None)
    for field_name in ("size", "color"):
        cleaned_value = clean_text(record.get(field_name))
        if field_name == "size" and detail_scalar_size_is_low_signal(
            cleaned_value,
            title=record.get("title"),
        ):
            record.pop(field_name, None)
            continue
        if (
            cleaned_value
            and not _variant_option_value_is_noise(cleaned_value)
            and not _option_value_repeats_product_title(
                cleaned_value,
                title_hint=clean_text(record.get("title")),
            )
        ):
            record[field_name] = cleaned_value
            continue
        record.pop(field_name, None)


def _option_value_repeats_product_title(value: str, *, title_hint: str) -> bool:
    if not value or not title_hint:
        return False
    value_key = re.sub(r"[^a-z0-9]+", "", clean_text(value).casefold())
    title_key = re.sub(r"[^a-z0-9]+", "", clean_text(title_hint).casefold())
    if not value_key or not title_key or len(title_key) < 8:
        return False
    return title_key in value_key


@lru_cache(maxsize=4096)
def _whole_value_pattern(value: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])")


def _drop_variant_derived_parent_axis_scalars(record: dict[str, Any]) -> None:
    variants = [
        row for row in list(record.get("variants") or []) if isinstance(row, dict)
    ]
    if not variants:
        return
    field_sources = record.get("_field_sources")
    sources = field_sources if isinstance(field_sources, dict) else {}
    for field_name in ("size", "color"):
        parent_value = clean_text(record.get(field_name))
        if not parent_value:
            continue
        variant_values = {
            clean_text(row.get(field_name)).casefold()
            for row in variants
            if clean_text(row.get(field_name))
        }
        if (
            field_name == "size"
            and len(variant_values) >= DETAIL_VARIANT_SIZE_MIN_FOR_NUMERIC_PARENT_DROP
            and re.fullmatch(r"\d+(?:\.\d+)?", parent_value)
            and not _numeric_size_value_in_variants(parent_value, variant_values)
            and parent_value.casefold() not in variant_values
        ):
            record.pop(field_name, None)
            continue
        # Drop parent axis strings that are just a dump of child variant values.
        if field_name in ("color", "size") and _parent_axis_value_looks_like_variant_dump(
            parent_value,
            variant_values,
        ):
            record.pop(field_name, None)
            continue
        if sources.get(field_name):
            continue
        if variant_values == {parent_value.casefold()}:
            record.pop(field_name, None)
            continue


def _parent_axis_value_looks_like_variant_dump(
    parent_value: str,
    variant_values: set[str],
) -> bool:
    if len(variant_values) < 2:
        return False
    normalized_parent = clean_text(parent_value).casefold()
    if not normalized_parent:
        return False
    if not all(
        value and _whole_value_pattern(value).search(normalized_parent)
        for value in variant_values
    ):
        return False
    residual = normalized_parent
    for value in sorted(variant_values, key=len, reverse=True):
        residual = _whole_value_pattern(value).sub(" ", residual)
    residual = clean_text(re.sub(r"[\d+\-−/]+", " ", residual)).casefold()
    if residual:
        return True
    return (
        re.search(r"\b\d+\b", normalized_parent) is not None
        or "+" in normalized_parent
        or "-" in normalized_parent
        or "−" in normalized_parent
        or "/" in normalized_parent
    )


def _numeric_size_value_in_variants(parent_value: str, variant_values: set[str]) -> bool:
    try:
        parent_number = Decimal(parent_value).normalize()
    except Exception:
        return False
    normalized_values: set[str] = set()
    for value in variant_values:
        try:
            normalized_values.add(str(Decimal(value).normalize()))
        except Exception:
            continue
    return str(parent_number) in normalized_values
