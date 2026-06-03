from __future__ import annotations

__all__ = ("sanitize_variant_row",)

import logging
import re
from decimal import Decimal
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse


from app.services.config.extraction_rules import (
    AMAZON_VARIANT_OPTION_VALUE_NOISE_PHRASES,
    BROKEN_FETCH_IMAGE_PATH_PATTERN,
    LOW_RES_SWATCH_IMAGE_PATH_PATTERN,
    SCALAR_FIELD_MAX_OPTION_TOKENS,
    VARIANT_OPTION_LABEL_MAX_WORDS,
)
from app.services.config.variant_policy import (
    DETAIL_VARIANT_SIZE_MIN_FOR_NUMERIC_PARENT_DROP,
)
from app.services.shared.field_coerce import (
    clean_text,
    text_or_none,
)
from app.services.shared.image_utils import query_dimension_is_tiny
from app.services.field_url_normalization import same_site
from app.services.dom.selector_engine import upgrade_low_resolution_image_url
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
    detail_identity_codes_from_url,
    detail_url_looks_like_product as _detail_url_looks_like_product,
    record_matches_requested_detail_identity as _record_matches_requested_detail_identity,
)
from app.services.extract.detail.text.sanitizer import (
    detail_scalar_size_is_low_signal,
)

logger = logging.getLogger(__name__)
try:
    scalar_field_max_option_tokens = max(1, int(SCALAR_FIELD_MAX_OPTION_TOKENS))
except (TypeError, ValueError):
    scalar_field_max_option_tokens = 1
try:
    variant_option_label_max_words = max(1, int(VARIANT_OPTION_LABEL_MAX_WORDS))
except (TypeError, ValueError):
    variant_option_label_max_words = 6
_amazon_variant_option_value_noise_phrases = frozenset(
    clean_text(value).casefold()
    for value in tuple(AMAZON_VARIANT_OPTION_VALUE_NOISE_PHRASES or ())
    if clean_text(value)
)
_BROKEN_FETCH_IMAGE_PATH_RE = re.compile(
    getattr(
        BROKEN_FETCH_IMAGE_PATH_PATTERN, "pattern", BROKEN_FETCH_IMAGE_PATH_PATTERN
    ),
    re.I,
)
_LOW_RES_SWATCH_IMAGE_PATH_RE = re.compile(str(LOW_RES_SWATCH_IMAGE_PATH_PATTERN), re.I)


def _sanitize_detail_variant_payload(
    record: dict[str, Any], *, identity_url: str
) -> None:
    cleaned_variants: list[dict[str, Any]] = []
    title_hint = clean_text(record.get("title"))
    for variant in record.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        if not sanitize_variant_row(
            variant, identity_url=identity_url, title_hint=title_hint
        ):
            continue
        cleaned_variants.append(variant)
    if _detail_variant_cluster_is_low_signal_numeric_only(cleaned_variants):
        cleaned_variants = []
    _drop_size_values_that_are_variant_colors(cleaned_variants)
    cleaned_variants = _drop_color_only_rows_when_sized_color_exists(cleaned_variants)
    cleaned_variants = _drop_low_signal_same_url_option_rows(cleaned_variants)
    if cleaned_variants:
        record["variants"] = cleaned_variants
        record["variant_count"] = len(cleaned_variants)
    else:
        record.pop("variants", None)
        record.pop("variant_count", None)
    record.pop("selected_variant", None)
    record.pop("variant_axes", None)
    record.pop("available_sizes", None)
    for field_name in tuple(record):
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
    axis_value_rejected = False
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        cleaned_options: dict[str, str] = {}
        for axis_name, axis_value in option_values.items():
            axis_key = normalized_variant_axis_key(axis_name)
            cleaned_value = clean_text(axis_value)
            if not axis_key or not cleaned_value:
                continue
            if (
                axis_key.startswith("toggle")
                or _variant_option_value_is_noise(cleaned_value)
                or _amazon_variant_axis_value_is_noise(
                    cleaned_value,
                    axis_key=axis_key,
                    identity_url=identity_url,
                )
            ):
                axis_value_rejected = True
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
        cleaned_value = _clean_variant_axis_label(cleaned_value)
        if not cleaned_value:
            if raw_value in (None, "", [], {}):
                variant.pop(field_name, None)
            continue
        if _variant_option_value_is_noise(cleaned_value):
            variant.pop(field_name, None)
            axis_value_rejected = True
            continue
        if _amazon_variant_axis_value_is_noise(
            cleaned_value,
            axis_key=field_name,
            identity_url=identity_url,
        ):
            variant.pop(field_name, None)
            axis_value_rejected = True
            continue
        if _option_value_repeats_product_title(cleaned_value, title_hint=title_hint):
            variant.pop(field_name, None)
            axis_value_rejected = True
            continue
        variant[field_name] = cleaned_value
    variant_url = text_or_none(variant.get("url"))
    if variant_url and _variant_url_is_child_product_for_adult_parent(
        variant_url,
        identity_url=identity_url,
        title_hint=title_hint,
        variant=variant,
    ):
        return False
    if (
        variant_url
        and same_site(identity_url, variant_url)
        and _detail_url_looks_like_product(variant_url)
        and not _variant_url_matches_requested_base(
            variant_url, identity_url=identity_url
        )
        and not _variant_url_shares_requested_identity(
            variant_url, identity_url=identity_url
        )
        and not _cross_asin_variant_url_can_be_option(
            variant,
            variant_url=variant_url,
            identity_url=identity_url,
            title_hint=title_hint,
        )
        and not _cross_product_variant_url_can_be_option(
            variant,
            variant_url=variant_url,
            title_hint=title_hint,
        )
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
        parsed_image = urlparse(normalized_image)
        if _BROKEN_FETCH_IMAGE_PATH_RE.fullmatch(parsed_image.path or "") or (
            _LOW_RES_SWATCH_IMAGE_PATH_RE.search(normalized_image)
            and query_dimension_is_tiny(parsed_image.query)
        ):
            variant.pop("image_url", None)
        else:
            variant["image_url"] = normalized_image
    if axis_value_rejected and not _variant_has_public_axis_or_identity_signal(variant):
        return False
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


def _amazon_variant_axis_value_is_noise(
    value: str,
    *,
    axis_key: str,
    identity_url: str,
) -> bool:
    if axis_key not in {"color", "size"} or not _url_is_amazon(identity_url):
        return False
    normalized = clean_text(value).casefold()
    if not normalized:
        return False
    if normalized in _amazon_variant_option_value_noise_phrases:
        return True
    if normalized.startswith("shop the store on amazon"):
        return True
    if "sponsored video" in normalized:
        return True
    words = re.findall(r"[a-z0-9]+", normalized)
    if len(words) <= variant_option_label_max_words:
        return False
    # Amazon media/related-product clusters can be mistaken for color swatches.
    # Real Twister values are short labels; long hardware/product names are not.
    return bool(
        re.search(r"\b(?:gpu|bracket|screw|magnetic|base|psu|tower|pc)\b", normalized)
    )


def _clean_variant_axis_label(value: str) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    choose_match = re.fullmatch(r"choose\s+(.+?)\s+variant", cleaned, flags=re.I)
    if choose_match:
        return clean_text(choose_match.group(1))
    return cleaned


def _url_is_amazon(value: object) -> bool:
    hostname = urlparse(str(value or "")).hostname or ""
    hostname = hostname.casefold()
    return bool(re.search(r"(^|\.)amazon\.", hostname))


def _cross_asin_variant_url_can_be_option(
    variant: dict[str, Any],
    *,
    variant_url: str,
    identity_url: str,
    title_hint: str,
) -> bool:
    if not (
        _url_is_amazon(identity_url)
        and _url_is_amazon(variant_url)
        and _variant_has_public_axis_or_identity_signal(variant)
    ):
        return False
    requested_codes = detail_identity_codes_from_url(identity_url)
    variant_codes = detail_identity_codes_from_url(variant_url)
    if not (requested_codes and variant_codes and requested_codes != variant_codes):
        return False
    option_values = variant.get("option_values")
    has_color_axis = bool(clean_text(variant.get("color"))) or (
        isinstance(option_values, dict) and bool(clean_text(option_values.get("color")))
    )
    if has_color_axis and _variant_has_public_axis_or_identity_signal(variant):
        return True
    return _cross_product_variant_url_can_be_option(
        variant,
        variant_url=variant_url,
        title_hint=title_hint,
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
        normalized_variant_axis_key(axis_name) and clean_text(axis_value)
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


def _variant_url_shares_requested_identity(
    variant_url: str, *, identity_url: str
) -> bool:
    requested_codes = detail_identity_codes_from_url(identity_url)
    variant_codes = detail_identity_codes_from_url(variant_url)
    return bool(requested_codes and variant_codes and requested_codes & variant_codes)


def _cross_product_variant_url_can_be_option(
    variant: dict[str, Any],
    *,
    variant_url: str,
    title_hint: str,
) -> bool:
    if not _variant_has_public_axis_or_identity_signal(variant):
        return False
    parent_tokens = _product_family_tokens(title_hint)
    if not parent_tokens:
        return True
    variant_tokens = _product_family_tokens(urlparse(variant_url).path)
    if not variant_tokens:
        return False
    required_overlap = 1 if len(parent_tokens) == 1 else 2
    return len(parent_tokens & variant_tokens) >= required_overlap


def _product_family_tokens(value: object) -> set[str]:
    tokens: set[str] = set()
    for raw_token in re.findall(r"[a-z0-9]+", clean_text(value).casefold()):
        if len(raw_token) < 3:
            continue
        tokens.add(_singular_family_token(raw_token))
    return tokens


def _singular_family_token(token: str) -> str:
    # Irregular plural token: normalize "mens" to "men"; nosec because this is not a secret.
    if token == "mens":  # nosec B105
        return "men"
    if token.endswith("ies") and len(token) > 5:
        return f"{token[:-3]}y"
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


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
    return (
        bool(size_value)
        and re.fullmatch(r"\d+", size_value) is not None
        and int(size_value) <= 4
    )


def _detail_variant_cluster_is_low_signal_numeric_only(
    variants: list[dict[str, Any]],
) -> bool:
    return bool(variants) and all(
        _detail_variant_row_is_low_signal_numeric_only(variant) for variant in variants
    )


def _drop_low_signal_same_url_option_rows(
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(variants) < 2:
        return variants
    urls = {text_or_none(variant.get("url")) for variant in variants}
    urls.discard(None)
    if len(urls) != 1:
        return variants
    stable_fields = (
        "sku",
        "variant_id",
        "barcode",
        "image_url",
        "price",
        "original_price",
        "stock_quantity",
        "size",
    )
    if any(
        text_or_none(variant.get(field_name))
        for variant in variants
        for field_name in stable_fields
    ):
        return variants
    axis_fields = ("color", "style", "scent", "material")
    if not all(
        any(_variant_axis_value(variant, field_name) for field_name in axis_fields)
        for variant in variants
    ):
        return variants
    return []


def _variant_axis_value(variant: dict[str, Any], field_name: str) -> str | None:
    value = text_or_none(variant.get(field_name))
    if value:
        return value
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        return text_or_none(option_values.get(field_name))
    return None


def _drop_size_values_that_are_variant_colors(variants: list[dict[str, Any]]) -> None:
    color_values = {
        clean_text(row.get("color")).casefold()
        for row in variants
        if clean_text(row.get("color"))
    }
    if not color_values:
        return
    for row in variants:
        size = clean_text(row.get("size"))
        if not size or _variant_size_value_looks_real(size):
            continue
        if size.casefold() in color_values:
            row.pop("size", None)
            options = row.get("option_values")
            if (
                isinstance(options, dict)
                and clean_text(options.get("size")).casefold() in color_values
            ):
                options.pop("size", None)
                if not options:
                    row.pop("option_values", None)


def _drop_color_only_rows_when_sized_color_exists(
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sized_colors = {
        clean_text(row.get("color")).casefold()
        for row in variants
        if clean_text(row.get("size")) and clean_text(row.get("color"))
    }
    if not sized_colors:
        return variants
    cleaned: list[dict[str, Any]] = []
    for row in variants:
        color = clean_text(row.get("color")).casefold()
        if (
            color
            and color in sized_colors
            and not clean_text(row.get("size"))
            and not any(
                text_or_none(row.get(field_name))
                for field_name in (
                    "sku",
                    "variant_id",
                    "barcode",
                    "image_url",
                    "price",
                    "original_price",
                    "stock_quantity",
                )
            )
        ):
            continue
        cleaned.append(row)
    return cleaned


def _variant_size_value_looks_real(value: str) -> bool:
    cleaned = clean_text(value)
    if not cleaned:
        return False
    return bool(
        re.fullmatch(r"\d+(?:\.\d+)?(?:[A-Z])?", cleaned, re.I)
        or re.fullmatch(r"(?:XXS|XS|S|M|L|XL|XXL|XXXL|\d+XL)", cleaned, re.I)
    )


def _variant_url_is_child_product_for_adult_parent(
    variant_url: str,
    *,
    identity_url: str,
    title_hint: str,
    variant: dict[str, Any],
) -> bool:
    parent_text = clean_text(f"{identity_url} {title_hint}").casefold()
    if not re.search(r"\b(?:men|mens|women|womens)\b", parent_text):
        return False
    if re.search(
        r"\b(?:kid|kids|child|children|toddler|grade school|pre school|preschool)\b",
        parent_text,
    ):
        return False
    candidate_text = clean_text(
        " ".join(
            str(value or "")
            for value in (
                variant_url,
                variant.get("title"),
                variant.get("color"),
                variant.get("option_values"),
            )
        )
    ).casefold()
    return bool(
        re.search(
            r"\b(?:grade school|pre school|preschool|toddler|infant|little kids?|kids?)\b",
            candidate_text,
        )
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
    for field_name in tuple(record):
        if str(field_name).startswith("toggle_"):
            record.pop(field_name, None)
    for field_name in ("size", "color"):
        cleaned_value = clean_text(record.get(field_name))
        if field_name == "color" and _scalar_color_is_numeric_swatch_id(cleaned_value):
            record.pop(field_name, None)
            continue
        if field_name == "size" and _scalar_size_looks_like_option_list(cleaned_value):
            record.pop(field_name, None)
            continue
        if field_name == "size" and detail_scalar_size_is_low_signal(
            cleaned_value,
            title=record.get("title"),
        ):
            record.pop(field_name, None)
            continue
        if field_name == "size" and _scalar_size_is_js_state_numeric_noise(
            record,
            cleaned_value,
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


def _scalar_color_is_numeric_swatch_id(value: str) -> bool:
    return bool(value and re.fullmatch(r"\d{4,}", value))


def _scalar_size_is_js_state_numeric_noise(
    record: dict[str, Any],
    value: str,
) -> bool:
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return False
    if any(isinstance(row, dict) for row in record.get("variants") or []):
        return False
    field_sources = record.get("_field_sources")
    if not isinstance(field_sources, dict):
        return False
    return "js_state" in [str(source) for source in field_sources.get("size") or []]


def _scalar_size_looks_like_option_list(value: str) -> bool:
    if not value:
        return False
    tokens = [token for token in re.split(r"[\s,|/]+", value.casefold()) if token]
    if len(tokens) <= scalar_field_max_option_tokens + 3:
        return False
    numeric_tokens = sum(1 for token in tokens if re.search(r"\d", token))
    repeated_tokens = len(tokens) - len(set(tokens))
    return numeric_tokens >= 2 and repeated_tokens >= 1


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
    variants = [row for row in record.get("variants") or [] if isinstance(row, dict)]
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
        if field_name in (
            "color",
            "size",
        ) and _parent_axis_value_looks_like_variant_dump(
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


def _numeric_size_value_in_variants(
    parent_value: str, variant_values: set[str]
) -> bool:
    try:
        parent_number = Decimal(parent_value).normalize()
    except Exception:
        return False
    normalized_values: set[str] = set()
    for value in variant_values:
        try:
            normalized_value = str(Decimal(value).normalize())
        except Exception:
            normalized_value = None
        if normalized_value is not None:
            normalized_values.add(normalized_value)
    return str(parent_number) in normalized_values
