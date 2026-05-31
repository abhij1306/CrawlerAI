"""Text identity coercion helpers for public field shaping."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.services.config.extraction_rules import (
    BARE_HOST_URL_RE,
    LISTING_BRAND_MAX_WORDS,
)
from app.services.config.public_record_policy import (
    PUBLIC_RECORD_BARCODE_LENGTHS,
    PUBLIC_RECORD_BRAND_REGION_SUFFIX_TOKENS,
    PUBLIC_RECORD_GENDER_REJECT_TOKENS,
    PUBLIC_RECORD_GENDER_TAXONOMY,
    PUBLIC_RECORD_IDENTITY_INTERNAL_TOKENS,
    PUBLIC_RECORD_SKU_DRAFT_PREFIX_PATTERN,
)
from app.services.shared.text_coerce import clean_text, coerce_text, slug_tokens

_PUBLIC_RECORD_BARCODE_LENGTHS_SET = frozenset(PUBLIC_RECORD_BARCODE_LENGTHS or ())
_BARE_HOST_URL_RE = BARE_HOST_URL_RE
_brand_region_suffix_tokens = tuple(PUBLIC_RECORD_BRAND_REGION_SUFFIX_TOKENS or ())
_BRAND_REGION_SUFFIX_RE = (
    re.compile(
        r"\s*[|\-\u2013\u2014]\s*(?:"
        + "|".join(
            re.escape(str(token))
            for token in sorted(
                _brand_region_suffix_tokens,
                key=len,
                reverse=True,
            )
        )
        + r")\.?\s*$",
        re.IGNORECASE,
    )
    if _brand_region_suffix_tokens
    else re.compile(r"(?!)")
)
_CATEGORY_URL_PATH_PATTERN = re.compile(
    r"""
    (?:^|\s)
    (?:https?\s*:|www\.|[a-z0-9-]+\.(?:com|net|org|io|co|shop|store))
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_GENDER_TAXONOMY = {
    str(key).casefold(): str(value)
    for key, value in dict(PUBLIC_RECORD_GENDER_TAXONOMY or {}).items()
}
_gender_reject_tokens = frozenset(
    str(token).casefold() for token in tuple(PUBLIC_RECORD_GENDER_REJECT_TOKENS or ())
)
_identity_internal_tokens = frozenset(
    str(token).casefold()
    for token in tuple(PUBLIC_RECORD_IDENTITY_INTERNAL_TOKENS or ())
)
_SKU_DRAFT_PREFIX_RE = re.compile(
    str(PUBLIC_RECORD_SKU_DRAFT_PREFIX_PATTERN), re.IGNORECASE
)
_BARCODE_SEPARATOR_RE = re.compile(r"[\s-]+")


def infer_brand_from_title_marker(title: object) -> str | None:
    text = clean_text(title)
    if not text:
        return None
    leading_marker = next(
        (marker for marker in ("\u2122", "\u00ae") if text.startswith(marker)), ""
    )
    if leading_marker:
        leading_token = clean_text(text[len(leading_marker) :]).split(" ", 1)[0].strip()
        brand = clean_text(f"{leading_marker}{leading_token}") if leading_token else ""
        if not brand or len(slug_tokens(brand)) > LISTING_BRAND_MAX_WORDS:
            return None
        return brand
    marker_positions = [
        index for marker in ("\u2122", "\u00ae") if (index := text.find(marker)) >= 0
    ]
    if not marker_positions:
        return None
    brand = clean_text(text[: min(marker_positions) + 1])
    if not brand or len(slug_tokens(brand)) > LISTING_BRAND_MAX_WORDS:
        return None
    return brand


def infer_brand_from_product_url(*, url: str, title: object) -> str | None:
    title_parts = slug_tokens(title)
    if len(title_parts) < 2:
        return None
    path_parts = [
        part.split(".", 1)[0]
        for part in (urlparse(str(url or "")).path or "").split("/")
        if part
    ]
    for path_part in reversed(path_parts):
        path_tokens = slug_tokens(path_part)
        if len(path_tokens) <= len(title_parts):
            continue
        for start in range(1, len(path_tokens) - len(title_parts) + 1):
            if path_tokens[start : start + len(title_parts)] != title_parts:
                continue
            brand_tokens = path_tokens[:start]
            if (
                not brand_tokens
                or len(brand_tokens) > LISTING_BRAND_MAX_WORDS
                or not any(re.search(r"[a-z]", token) for token in brand_tokens)
            ):
                continue
            return " ".join(token.capitalize() for token in brand_tokens)
    return None


def category_value_is_url_path(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    if "://" in lowered:
        return True
    if "https:" in lowered or "http:" in lowered:
        return True
    return _CATEGORY_URL_PATH_PATTERN.search(lowered) is not None


def coerce_brand_text(value: object) -> str | None:
    text = coerce_text(value)
    if not text:
        return None
    text = re.sub(r"^\s*\d+\s+(?=[A-Za-z])", "", text).strip()
    if not text or not re.search(r"[A-Za-z]", text):
        return None
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https", "ftp", "mailto"} or parsed.netloc:
        return None
    if _BARE_HOST_URL_RE.fullmatch(text):
        return None
    cleaned = _BRAND_REGION_SUFFIX_RE.sub("", text).strip()
    cleaned = _strip_brand_marketing_tagline(cleaned) or cleaned
    return cleaned or text


def _strip_brand_marketing_tagline(text: str) -> str | None:
    """Drop a marketing tagline that follows a clear separator.

    Brand fields sometimes carry a site tagline (e.g. JSON-LD ``Brand.name``
    such as ``"Gymshark | We Do Gym"``). When the prefix is a short, clean
    brand-shaped token (1–3 words, alphabetic/digit only, no URL shape) and
    the suffix is multi-word (a tagline, not a region/storefront token already
    handled by ``_BRAND_REGION_SUFFIX_RE``), keep only the prefix.

    Conservative: returns ``None`` when the input does not look like a
    ``brand <sep> tagline`` shape so callers can keep the original text.
    """
    if not text:
        return None
    match = _BRAND_TAGLINE_SPLIT_RE.match(text)
    if match is None:
        return None
    prefix = clean_text(match.group("prefix"))
    suffix = clean_text(match.group("suffix"))
    if not prefix or not suffix:
        return None
    prefix_tokens = [token for token in re.split(r"\s+", prefix) if token]
    suffix_tokens = [token for token in re.split(r"\s+", suffix) if token]
    if len(prefix_tokens) > LISTING_BRAND_MAX_WORDS:
        return None
    if not all(re.fullmatch(r"[A-Za-z0-9&'.\-]+", token) for token in prefix_tokens):
        return None
    if not any(re.search(r"[A-Za-z]", token) for token in prefix_tokens):
        return None
    if len(suffix_tokens) < 2:
        return None
    return prefix


_BRAND_TAGLINE_SPLIT_RE = re.compile(
    r"^(?P<prefix>.+?)\s*[|\u2013\u2014]\s*(?P<suffix>\S.+)$"
)


def coerce_gender(value: object) -> str | None:
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("title")
            or value.get("label")
            or value.get("value")
        )
    text = coerce_text(value)
    if not text:
        return None
    folded = text.strip().lower()
    if folded in _gender_reject_tokens:
        return None
    return _GENDER_TAXONOMY.get(folded, text)


def coerce_barcode(value: object) -> str | None:
    text = coerce_text(value)
    if not text:
        return None
    if not re.fullmatch(r"[\d\s-]+", text):
        return None
    digits = _BARCODE_SEPARATOR_RE.sub("", text)
    if not digits or len(digits) not in _PUBLIC_RECORD_BARCODE_LENGTHS_SET:
        return None
    return digits


def coerce_sku(value: object) -> str | None:
    text = coerce_text(value)
    if not text:
        return None
    had_draft_prefix = bool(_SKU_DRAFT_PREFIX_RE.match(text))
    cleaned = _SKU_DRAFT_PREFIX_RE.sub("", text).strip()
    if cleaned.startswith(("{", "[")):
        return None
    if had_draft_prefix and re.fullmatch(r"\d{10,}", cleaned):
        return None
    if _looks_like_tracking_hash_sku(cleaned):
        return None
    return cleaned or None


def _looks_like_tracking_hash_sku(value: str) -> bool:
    if len(value) <= 20 or re.search(r"[-_\s]", value):
        return False
    if not re.fullmatch(r"[A-Za-z0-9]+", value):
        return False
    has_alpha = bool(re.search(r"[A-Za-z]", value))
    has_digit = bool(re.search(r"\d", value))
    return has_alpha and has_digit


def coerce_identity_token_or_none(value: object) -> str | None:
    text = coerce_text(value)
    if not text:
        return None
    folded = text.strip().lower()
    if folded in _identity_internal_tokens:
        return None
    return text


def identity_internal_tokens() -> frozenset[str]:
    return _identity_internal_tokens
