from __future__ import annotations

__all__ = (
    "variant_axis_value_exceeds_word_limit",
    "drop_invalid_variant_urls",
    "variant_url_is_product_like",
)

from collections.abc import Callable
from urllib.parse import urlparse

from app.services.config.variant_migration_rules import (
    VARIANT_COLOR_AXIS_FIELD,
    VARIANT_PRODUCT_DETAIL_PATH_MARKERS,
    VARIANT_PUBLIC_URL_FIELD_NAMES,
    VARIANT_PUBLIC_URL_SCHEMES,
    VARIANT_URL_BLOCKED_PATH_PREFIXES,
    VARIANT_URL_BLOCKED_PATH_SUFFIXES,
)
from app.services.config.public_record_policy import (
    PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS,
    PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES,
)
from app.services.shared.field_coerce import clean_text, text_or_none

_BLOCKED_SUFFIXES = tuple(clean_text(v).casefold() for v in VARIANT_URL_BLOCKED_PATH_SUFFIXES if clean_text(v))
_BLOCKED_PREFIXES = tuple(clean_text(v).casefold() for v in VARIANT_URL_BLOCKED_PATH_PREFIXES if clean_text(v))
_DETAIL_QUERY_KEYS = frozenset(
    clean_text(value).casefold()
    for value in tuple(PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS or ())
    if clean_text(value)
)
_DETAIL_QUERY_PREFIXES = tuple(
    clean_text(value).casefold()
    for value in tuple(PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES or ())
    if clean_text(value)
)


def variant_axis_value_exceeds_word_limit(
    axis_key: str,
    value: str,
    *,
    max_words: int,
    color_extractor: Callable[[object], str],
) -> bool:
    word_count = len([token for token in clean_text(value).split() if token])
    if word_count <= max_words:
        return False
    try:
        return not (axis_key == VARIANT_COLOR_AXIS_FIELD and color_extractor(value))
    except Exception:
        return True


def drop_invalid_variant_urls(variant: dict[str, object]) -> None:
    for field_name in VARIANT_PUBLIC_URL_FIELD_NAMES:
        value = text_or_none(variant.get(field_name))
        if value and (
            variant_url_is_product_like(value)
            if field_name == "url"
            else _url_is_public_http(urlparse(value))
        ):
            continue
        variant.pop(field_name, None)


def variant_url_is_product_like(value: str) -> bool:
    parsed = urlparse(value)
    if not _url_is_public_http(parsed):
        return False
    path = parsed.path.rstrip("/").casefold()
    query = parsed.query.casefold()
    if _path_has_product_detail_marker(path):
        return True
    if any(path.endswith(suffix) for suffix in _BLOCKED_SUFFIXES):
        return False
    if any(path.startswith(prefix) for prefix in _BLOCKED_PREFIXES):
        return False
    return any(
        token in query
        for token in _variant_query_tokens()
    )


def _variant_query_tokens() -> tuple[str, ...]:
    query_tokens = [f"{key}=" for key in _DETAIL_QUERY_KEYS]
    query_tokens.extend(f"{prefix}" for prefix in _DETAIL_QUERY_PREFIXES if prefix)
    query_tokens.append("piid=")
    return tuple(dict.fromkeys(token for token in query_tokens if token))


def _path_has_product_detail_marker(path: str) -> bool:
    for marker in VARIANT_PRODUCT_DETAIL_PATH_MARKERS:
        if marker not in path:
            continue
        marker_stem = marker.rstrip("/")
        if path.endswith(marker_stem) or path.endswith(f"{marker_stem}.json"):
            continue
        return True
    return False


def _url_is_public_http(parsed: object) -> bool:
    if not hasattr(parsed, "scheme") or not hasattr(parsed, "netloc"):
        return False
    return (
        str(getattr(parsed, "scheme", "")).lower() in VARIANT_PUBLIC_URL_SCHEMES
        and bool(getattr(parsed, "netloc", ""))
    )
