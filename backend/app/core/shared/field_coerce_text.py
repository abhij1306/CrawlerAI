"""Text identity coercion helpers for public field shaping."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.config.extraction_rules import (
    DETAIL_BRAND_PREFIX_STOP_TOKENS,
    BARE_HOST_URL_RE,
    DETAIL_TITLE_INTERNAL_SYSTEM_PATTERN,
    LISTING_BRAND_MAX_WORDS,
)
from app.core.config.public_record_policy import (
    PUBLIC_RECORD_BARCODE_LENGTHS,
    PUBLIC_RECORD_BRAND_REGION_SUFFIX_TOKENS,
    PUBLIC_RECORD_GENDER_REJECT_TOKENS,
    PUBLIC_RECORD_GENDER_TAXONOMY,
    PUBLIC_RECORD_IDENTITY_INTERNAL_TOKENS,
    PUBLIC_RECORD_NUMERIC_BRAND_PATTERN,
    PUBLIC_RECORD_SKU_DRAFT_PREFIX_PATTERN,
)
from app.core.shared.text_coerce import clean_text, coerce_text, slug_tokens

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


def infer_brand_from_title_host(*, title: object, url: str) -> str | None:
    text = clean_text(title)
    host = urlparse(str(url or "")).hostname or ""
    if not text or not host:
        return None
    ignored_labels = {
        "www",
        "shop",
        "store",
        "us",
        "usa",
        "uk",
        "in",
        "com",
        "co",
        "net",
        "org",
    }
    labels = [
        label
        for label in host.casefold().split(".")
        if label and label not in ignored_labels
    ]
    if not labels:
        return None
    host_token = max(
        (re.sub(r"[^a-z0-9]+", "", label) for label in labels),
        key=len,
        default="",
    )
    title_tokens = slug_tokens(text)
    if not host_token or not title_tokens:
        return None
    original_words = text.split()
    for size in range(min(LISTING_BRAND_MAX_WORDS, len(title_tokens)), 0, -1):
        for start in range(0, len(title_tokens) - size + 1):
            candidate = title_tokens[start : start + size]
            if "".join(candidate) != host_token:
                continue
            original = " ".join(original_words[start : start + size]).strip(" |-–—")
            return original or None
    return None


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


def infer_brand_from_page_identity(
    *,
    url: str,
    title: object,
    evidence_values: tuple[object, ...],
    existing_brands: tuple[object, ...] = (),
) -> str | None:
    text = clean_text(title)
    host = urlparse(str(url or "")).hostname or ""
    labels = [
        label
        for label in host.casefold().split(".")
        if label
        not in {
            "",
            "www",
            "shop",
            "store",
            "us",
            "usa",
            "uk",
            "in",
            "com",
            "co",
            "net",
            "org",
        }
    ]
    if not text or not labels:
        return None
    host_label = max(labels, key=len)
    host_words = slug_tokens(host_label)
    compact_host = "".join(host_words)
    suffixes = ("beauty", "cosmetics", "official", "online", "shop", "store")
    compact_core = next(
        (
            compact_host[: -len(suffix)]
            for suffix in suffixes
            if compact_host.endswith(suffix)
        ),
        compact_host,
    )
    generic_host = compact_core in {"example", "invalid", "localhost", "test"}
    corpus = " ".join(
        clean_text(value) for value in evidence_values if clean_text(value)
    )
    corpus_words = corpus.split()
    title_words = text.split()
    title_tokens = slug_tokens(text)
    existing = tuple(
        clean_text(value) for value in existing_brands if clean_text(value)
    )
    if existing and title_words:
        first = "".join(slug_tokens(existing[0]))
        if (
            first == compact_core
            and len(title_words) >= 2
            and title_tokens[0] in slug_tokens(existing[0])
            and title_words[1].isupper()
        ):
            return " ".join(title_words[:2])
    for size in range(min(LISTING_BRAND_MAX_WORDS, len(corpus_words)), 0, -1):
        for start in range(len(corpus_words) - size + 1):
            candidate = " ".join(corpus_words[start : start + size]).strip(" |-–—")
            if "".join(slug_tokens(candidate)) in {compact_host, compact_core}:
                return candidate
    for brand in existing:
        compact_brand = "".join(slug_tokens(brand))
        if compact_brand and compact_core.startswith(compact_brand):
            remainder = compact_core[len(compact_brand) :]
            if remainder and remainder.isalpha():
                return f"{brand} {remainder.capitalize()}"
    if (
        not generic_host
        and compact_core
        and any(
            compact_core in "".join(slug_tokens(value)) for value in evidence_values
        )
    ):
        return compact_core.capitalize()
    if not generic_host and title_tokens and title_words:
        first = title_tokens[0]
        path_tokens = slug_tokens(urlparse(str(url or "")).path)
        corroborations = sum(first in slug_tokens(value) for value in evidence_values)
        if first in path_tokens and corroborations >= 2:
            return title_words[0]
    return None


def infer_brand_from_product_url(*, url: str, title: object) -> str | None:
    text = clean_text(title)
    title_parts = slug_tokens(text)
    if len(title_parts) < 2:
        return None
    path_parts = [
        part.split(".", 1)[0]
        for part in (urlparse(str(url or "")).path or "").split("/")
        if part
    ]
    title_segments = text.split(" - ", 1) if text else []
    leading_segment = title_segments[0].strip(" |-–—") if title_segments else ""
    trailing_segment = (
        title_segments[1].strip(" |-–—") if len(title_segments) == 2 else ""
    )
    leading_tokens = slug_tokens(leading_segment)
    first_token = title_parts[0] if title_parts else ""
    if (
        " - " in text
        and leading_segment[:1].isupper()
        and first_token
        and first_token not in DETAIL_BRAND_PREFIX_STOP_TOKENS
    ):
        matching_path_part = any(
            (tokens := slug_tokens(part))
            and len(tokens) >= len(leading_tokens)
            and tokens[: len(leading_tokens)] == leading_tokens
            for part in path_parts
        )
        if matching_path_part:
            host = urlparse(str(url or "")).hostname or ""
            host_labels = {
                "".join(slug_tokens(label))
                for label in host.split(".")
                if label.casefold()
                not in {"", "www", "shop", "store", "com", "co", "net", "org"}
            }
            trailing_compact = "".join(slug_tokens(trailing_segment))
            if trailing_compact and trailing_compact in host_labels:
                return leading_segment.split(" ", 1)[0].strip(" |-–—") or None
            if len(leading_tokens) <= LISTING_BRAND_MAX_WORDS:
                return leading_segment
    for path_part in reversed(path_parts):
        path_tokens = slug_tokens(path_part)
        if len(path_tokens) <= len(title_parts):
            continue
        for start in range(1, len(path_tokens) - len(title_parts) + 1):
            if path_tokens[start : start + len(title_parts)] != title_parts:
                continue
            brand_tokens = path_tokens[:start]
            while brand_tokens and brand_tokens[0].isdigit():
                brand_tokens = brand_tokens[1:]
            if (
                not brand_tokens
                or len(brand_tokens) > LISTING_BRAND_MAX_WORDS
                or not any(re.search(r"[a-z]", token) for token in brand_tokens)
            ):
                continue
            return " ".join(token.capitalize() for token in brand_tokens)
        title_anchor = title_parts[: min(2, len(title_parts))]
        for start in range(1, len(path_tokens) - len(title_anchor) + 1):
            if path_tokens[start : start + len(title_anchor)] != title_anchor:
                continue
            brand_tokens = path_tokens[:start]
            while brand_tokens and brand_tokens[0].isdigit():
                brand_tokens = brand_tokens[1:]
            if (
                brand_tokens
                and len(brand_tokens) <= LISTING_BRAND_MAX_WORDS
                and all(re.search(r"[a-z]", token) for token in brand_tokens)
            ):
                return " ".join(token.capitalize() for token in brand_tokens)
    path_token_set = {token for part in path_parts for token in slug_tokens(part)}
    words = text.split()
    # Marketplace fallback: when the title's first two slug tokens are also the
    # leading two tokens of a long product-slug path segment (>=5 tokens), treat
    # the title's first stop-free word as the brand. The 5-token floor avoids
    # firing on short brand-host slugs like calvinklein.us/bags/structured-
    # commuter-bag.html (3 tokens), where the title leads with a product
    # descriptor and the host carries the brand. Long marketplace product slugs
    # (StockX/Nike, Firstcry/Babyhug, Chewy/Wellness) clear the floor. Runs
    # before the all-caps fallback so "Wellness CORE+" returns "Wellness", not
    # the all-caps product-line token "CORE+".
    leading_word = words[0].strip(" |-–—'") if words else ""
    title_anchor = title_parts[:2]
    matching_title_anchor_index = next(
        (
            index
            for index, part in enumerate(path_parts)
            if len(tokens := slug_tokens(part)) >= 5 and tokens[:2] == title_anchor
        ),
        -1,
    )
    leading_word_token = "".join(slug_tokens(leading_word))
    has_product_id_signal = any(re.search(r"\d", part) for part in path_parts)
    has_brand_route_signal = (
        matching_title_anchor_index == 0 and has_product_id_signal
    ) or (
        matching_title_anchor_index > 0
        and slug_tokens(path_parts[matching_title_anchor_index - 1])
        == [leading_word_token]
    )
    if (
        len(title_anchor) == 2
        and first_token not in DETAIL_BRAND_PREFIX_STOP_TOKENS
        and leading_word
        and leading_word[:1].isupper()
        and leading_word_token
        and has_brand_route_signal
    ):
        return leading_word
    for index, original in enumerate(words):
        token = "".join(slug_tokens(original))
        next_token = (
            "".join(slug_tokens(words[index + 1])) if index + 1 < len(words) else ""
        )
        if (
            len(token) >= 3
            and token in path_token_set
            and token not in DETAIL_BRAND_PREFIX_STOP_TOKENS
            and original.strip("'-").isupper()
            and not re.fullmatch(r"[A-Za-z]{1,3}\d{1,4}[A-Za-z0-9]*", next_token)
        ):
            return original.strip(" |-–—'")
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
    if numeric_brand := re.fullmatch(PUBLIC_RECORD_NUMERIC_BRAND_PATTERN, text):
        return str(numeric_brand.group("brand"))
    if not text or not re.search(r"[A-Za-z]", text):
        return None
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https", "ftp", "mailto"} or parsed.netloc:
        return None
    if _BARE_HOST_URL_RE.fullmatch(text):
        return None
    cleaned = _BRAND_REGION_SUFFIX_RE.sub("", text).strip()
    cleaned = _strip_brand_marketing_tagline(cleaned) or cleaned
    return _normalize_brand_punctuation(cleaned) or cleaned or text


def _normalize_brand_punctuation(text: str) -> str | None:
    """Collapse runaway whitespace and strip a stray trailing sentence mark.

    Generic only — no brand vocabulary. A single-token brand ending in a
    sentence mark (``"Target."``) is a scraping artefact, so the trailing
    ``.,;:`` is dropped; multi-token values are left intact so legitimate
    abbreviations after a space (``"Acme Co."``) and internal punctuation
    (``"J.Crew"``, ``"Amazon.com"``) survive.
    """

    collapsed = re.sub(r"\s+", " ", str(text)).strip()
    if not collapsed:
        return None
    if " " not in collapsed:
        collapsed = collapsed.rstrip(".,;:")
    return collapsed or None


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
    if re.fullmatch(DETAIL_TITLE_INTERNAL_SYSTEM_PATTERN, cleaned, re.IGNORECASE):
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
