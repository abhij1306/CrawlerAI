"""Text identity coercion helpers for public field shaping."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.config.extraction_rules import (
    DETAIL_BRAND_PREFIX_STOP_TOKENS,
    BARE_HOST_URL_RE,
    DETAIL_IDENTITY_TRADEMARK_SYMBOL_PATTERN,
    DETAIL_TITLE_INTERNAL_SYSTEM_PATTERN,
    LISTING_BRAND_MAX_WORDS,
)
from app.core.config.public_record_policy import (
    PUBLIC_RECORD_BARCODE_LENGTHS,
    PUBLIC_RECORD_BRAND_HOST_SUFFIXES,
    PUBLIC_RECORD_BRAND_IGNORED_HOST_LABELS,
    PUBLIC_RECORD_BRAND_REGION_SUFFIX_TOKENS,
    PUBLIC_RECORD_GENERIC_HOST_BRANDS,
    PUBLIC_RECORD_GENDER_REJECT_TOKENS,
    PUBLIC_RECORD_GENDER_TAXONOMY,
    PUBLIC_RECORD_IDENTITY_INTERNAL_TOKENS,
    PUBLIC_RECORD_NUMERIC_BRAND_PATTERN,
    PUBLIC_RECORD_SKU_DRAFT_PREFIX_PATTERN,
)
from app.core.config.url_path_markers import ECOMMERCE_DETAIL_PATH_SEGMENTS
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
# A DOM identifier often arrives with its own field label attached
# ("Item # 77295", "SKU: BT-1MW") because the label and value share a cell.
# The label is page furniture, never part of the identifier.
_IDENTIFIER_LABEL_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z.\s]{0,20}?\s*[#:]\s+(?=\S)")
# Without whitespace after the delimiter only a known label word may be stripped,
# so "SKU:BT-1MW" loses its label while an identifier that legitimately contains a
# delimiter ("ABC:123") is preserved.
_IDENTIFIER_LABEL_WORDS = (
    "article",
    "art",
    "item",
    "model",
    "mpn",
    "part",
    "product",
    "ref",
    "sku",
    "style",
)
_IDENTIFIER_TIGHT_LABEL_RE = re.compile(
    rf"^(?:{'|'.join(_IDENTIFIER_LABEL_WORDS)})"
    r"(?:\s*(?:no|number|code|id)\.?)?\s*[#:]\s*(?=\S)",
    re.IGNORECASE,
)


def infer_brand_from_title_host(*, title: object, url: str) -> str | None:
    text = clean_text(title)
    host = urlparse(str(url or "")).hostname or ""
    if not text or not host:
        return None
    labels = [
        label
        for label in host.casefold().split(".")
        if label not in PUBLIC_RECORD_BRAND_IGNORED_HOST_LABELS
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


def _without_trademark_symbols(value: str) -> str:
    """The marker locates where a brand name ends; it is not part of the name."""
    return re.sub(
        r"\s+", " ", re.sub(DETAIL_IDENTITY_TRADEMARK_SYMBOL_PATTERN, "", value)
    ).strip()


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
        return _without_trademark_symbols(brand) or None
    marker_positions = [
        index for marker in ("\u2122", "\u00ae") if (index := text.find(marker)) >= 0
    ]
    if not marker_positions:
        return None
    brand = clean_text(text[: min(marker_positions) + 1])
    if not brand or len(slug_tokens(brand)) > LISTING_BRAND_MAX_WORDS:
        return None
    return _without_trademark_symbols(brand) or None


def infer_brand_from_marked_title_path(*, url: str, title: object) -> str | None:
    text = clean_text(title)
    if not text or not any(marker in text for marker in ("\u2122", "\u00ae")):
        return None
    marker_positions = [
        index for marker in ("\u2122", "\u00ae") if (index := text.find(marker)) >= 0
    ]
    marker_prefix = text[: min(marker_positions) + 1] if marker_positions else ""
    brand_tokens = slug_tokens(marker_prefix)
    if not brand_tokens or len(brand_tokens) > LISTING_BRAND_MAX_WORDS:
        return None
    first_token = brand_tokens[0]
    if first_token in DETAIL_BRAND_PREFIX_STOP_TOKENS:
        return None
    path_tokens = slug_tokens(urlparse(str(url or "")).path)
    for start in range(0, len(path_tokens) - len(brand_tokens) + 1):
        if path_tokens[start : start + len(brand_tokens)] == brand_tokens:
            return marker_prefix.strip(" |-–—'") or None
    return None


def infer_brand_from_page_identity(
    *,
    url: str,
    title: object,
    evidence_values: tuple[object, ...],
    existing_brands: tuple[object, ...] = (),
) -> str | None:
    text = clean_text(title)
    host = _brand_host_identity(url)
    if not text or host is None:
        return None
    compact_host, compact_core, generic_host = host
    corpus_words = " ".join(
        clean_text(value) for value in evidence_values if clean_text(value)
    ).split()
    title_words = text.split()
    title_tokens = slug_tokens(text)
    existing = tuple(
        clean_text(value) for value in existing_brands if clean_text(value)
    )
    leading = _leading_existing_brand(compact_core, existing, title_words, title_tokens)
    if leading:
        return leading
    matched = _matching_host_brand(compact_host, compact_core, corpus_words, existing)
    if matched:
        return matched
    return _corroborated_page_brand(
        url=url,
        evidence_values=evidence_values,
        existing=existing,
        compact_core=compact_core,
        generic_host=generic_host,
        title_tokens=title_tokens,
        title_words=title_words,
    )


def _brand_host_identity(url: str) -> tuple[str, str, bool] | None:
    host = urlparse(str(url or "")).hostname or ""
    labels = [
        label
        for label in host.casefold().split(".")
        if label not in PUBLIC_RECORD_BRAND_IGNORED_HOST_LABELS
    ]
    if not labels:
        return None
    compact_host = "".join(slug_tokens(max(labels, key=len)))
    compact_core = next(
        (
            compact_host[: -len(suffix)]
            for suffix in PUBLIC_RECORD_BRAND_HOST_SUFFIXES
            if compact_host.endswith(suffix)
        ),
        compact_host,
    )
    return compact_host, compact_core, compact_core in PUBLIC_RECORD_GENERIC_HOST_BRANDS


def _leading_existing_brand(
    compact_core: str,
    existing: tuple[str, ...],
    title_words: list[str],
    title_tokens: list[str],
) -> str | None:
    if not existing or len(title_words) < 2 or not title_tokens:
        return None
    first = "".join(slug_tokens(existing[0]))
    if (
        first == compact_core
        and title_tokens[0] in slug_tokens(existing[0])
        and title_words[1].isupper()
    ):
        return " ".join(title_words[:2])
    return None


def _matching_host_brand(
    compact_host: str,
    compact_core: str,
    corpus_words: list[str],
    existing: tuple[str, ...],
) -> str | None:
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
    return None


def _corroborated_page_brand(
    *,
    url: str,
    evidence_values: tuple[object, ...],
    existing: tuple[str, ...],
    compact_core: str,
    generic_host: bool,
    title_tokens: list[str],
    title_words: list[str],
) -> str | None:
    if (
        not generic_host
        and compact_core
        and any(
            compact_core in "".join(slug_tokens(value)) for value in evidence_values
        )
    ):
        return compact_core.capitalize()
    if not existing or generic_host or not title_tokens or not title_words:
        return None
    first = title_tokens[0]
    path_tokens = slug_tokens(urlparse(str(url or "")).path)
    corroborations = sum(first in slug_tokens(value) for value in evidence_values)
    return title_words[0] if first in path_tokens and corroborations >= 2 else None


@dataclass(frozen=True, slots=True)
class _BrandUrlContext:
    text: str
    title_tokens: list[str]
    path_parts: list[str]
    path_text: str
    path_tokens: list[str]
    words: list[str]

    @property
    def first_token(self) -> str:
        return self.title_tokens[0]

    @property
    def first_word(self) -> str:
        return self.words[0].strip(" |-–—'") if self.words else ""


def infer_brand_from_product_url(*, url: str, title: object) -> str | None:
    text = clean_text(title)
    title_tokens = slug_tokens(text)
    if len(title_tokens) < 2:
        return None
    path_text = urlparse(str(url or "")).path or ""
    context = _BrandUrlContext(
        text=text,
        title_tokens=title_tokens,
        path_parts=[part.split(".", 1)[0] for part in path_text.split("/") if part],
        path_text=path_text,
        path_tokens=slug_tokens(path_text),
        words=text.split(),
    )
    for inference in (
        _direct_product_url_brand,
        _hyphenated_product_url_brand,
        _prefixed_product_url_brand,
        _route_product_url_brand,
    ):
        if brand := inference(context, url):
            return brand
    return None


def _direct_product_url_brand(context: _BrandUrlContext, _url: str) -> str | None:
    prefix_allowed = context.first_token not in DETAIL_BRAND_PREFIX_STOP_TOKENS
    shared = (
        context.path_tokens[:2] == context.title_tokens[:2]
        and context.first_word
        and prefix_allowed
    )
    path_segments = {part.casefold() for part in context.path_parts}
    standard = bool(
        shared and not path_segments.isdisjoint(ECOMMERCE_DETAIL_PATH_SEGMENTS)
    )
    single_path = (
        shared and len(context.title_tokens) >= 4 and len(context.path_parts) == 1
    )
    marked = (
        any(marker in context.text for marker in ("™", "®"))
        and context.path_parts
        and slug_tokens(context.path_parts[-1])[:1] == context.title_tokens[:1]
        and context.first_word
        and prefix_allowed
    )
    return context.first_word if standard or single_path or marked else None


def _hyphenated_product_url_brand(context: _BrandUrlContext, url: str) -> str | None:
    segments = context.text.split(" - ", 1)
    leading = segments[0].strip(" |-–—")
    leading_tokens = slug_tokens(leading)
    eligible = (
        len(segments) == 2
        and leading[:1].isupper()
        and context.first_token not in DETAIL_BRAND_PREFIX_STOP_TOKENS
        and any(
            (tokens := slug_tokens(part))
            and tokens[: len(leading_tokens)] == leading_tokens
            for part in context.path_parts
        )
    )
    if not eligible:
        return None
    host = urlparse(str(url or "")).hostname or ""
    host_labels = {
        "".join(slug_tokens(label))
        for label in host.split(".")
        if label.casefold() not in PUBLIC_RECORD_BRAND_IGNORED_HOST_LABELS
    }
    trailing = "".join(slug_tokens(segments[1].strip(" |-–—")))
    if trailing and trailing in host_labels:
        return leading.split(" ", 1)[0].strip(" |-–—") or None
    return leading if len(leading_tokens) <= LISTING_BRAND_MAX_WORDS else None


def _tokens_before_anchor(
    path_tokens: list[str], anchor: list[str], *, require_all_alpha: bool
) -> list[str] | None:
    for start in range(1, len(path_tokens) - len(anchor) + 1):
        if path_tokens[start : start + len(anchor)] != anchor:
            continue
        brand_tokens = path_tokens[:start]
        while brand_tokens and brand_tokens[0].isdigit():
            brand_tokens = brand_tokens[1:]
        if not brand_tokens or len(brand_tokens) > LISTING_BRAND_MAX_WORDS:
            continue
        matches = [bool(re.search(r"[a-z]", token)) for token in brand_tokens]
        if all(matches) if require_all_alpha else any(matches):
            return brand_tokens
    return None


def _prefixed_product_url_brand(context: _BrandUrlContext, _url: str) -> str | None:
    for part in reversed(context.path_parts):
        path_tokens = slug_tokens(part)
        if len(path_tokens) <= len(context.title_tokens):
            continue
        brand_tokens = _tokens_before_anchor(
            path_tokens, context.title_tokens, require_all_alpha=False
        ) or _tokens_before_anchor(
            path_tokens, context.title_tokens[:2], require_all_alpha=True
        )
        if brand_tokens:
            return " ".join(token.capitalize() for token in brand_tokens)
    return None


def _route_product_url_brand(context: _BrandUrlContext, _url: str) -> str | None:
    path_token_set = {
        token for part in context.path_parts for token in slug_tokens(part)
    }
    anchor = context.title_tokens[:2]
    matching_index = next(
        (
            index
            for index, part in enumerate(context.path_parts)
            if len(tokens := slug_tokens(part)) >= 5 and tokens[:2] == anchor
        ),
        -1,
    )
    leading_token = "".join(slug_tokens(context.first_word))
    if (
        matching_index > 0
        and slug_tokens(context.path_parts[matching_index - 1]) == [leading_token]
        and context.first_token not in DETAIL_BRAND_PREFIX_STOP_TOKENS
        and context.first_word[:1].isupper()
        and leading_token
    ):
        return context.first_word
    return _uppercase_path_brand(context, path_token_set)


def _uppercase_path_brand(
    context: _BrandUrlContext, path_token_set: set[str]
) -> str | None:
    for index, original in enumerate(context.words):
        token = "".join(slug_tokens(original))
        next_token = (
            "".join(slug_tokens(context.words[index + 1]))
            if index + 1 < len(context.words)
            else ""
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
    lowered = text.casefold()
    parsed = urlparse(text)
    has_explicit_url_shape = any(
        token in lowered for token in ("://", "/", "?", "#", "@")
    )
    if has_explicit_url_shape and (
        parsed.scheme in {"http", "https", "ftp", "mailto"} or parsed.netloc
    ):
        return None
    if _BARE_HOST_URL_RE.fullmatch(text) and " " in text:
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
    separator_index = min(
        (index for index, character in enumerate(text) if character in "|\u2013\u2014"),
        default=-1,
    )
    if separator_index < 0:
        return None
    prefix = clean_text(text[:separator_index])
    suffix = clean_text(text[separator_index + 1 :])
    if not prefix or not suffix:
        return None
    if not _valid_brand_prefix(prefix.split()) or len(suffix.split()) < 2:
        return None
    return prefix


def _valid_brand_prefix(tokens: list[str]) -> bool:
    allowed = frozenset("&'.-")
    return (
        bool(tokens)
        and len(tokens) <= LISTING_BRAND_MAX_WORDS
        and all(
            all(character.isalnum() or character in allowed for character in token)
            for token in tokens
        )
        and any(any(character.isalpha() for character in token) for token in tokens)
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


def strip_identifier_label_prefix(value: str) -> str:
    """Drop a field label that a DOM cell carried along with its identifier."""
    stripped = _IDENTIFIER_LABEL_PREFIX_RE.sub("", value, count=1)
    if stripped == value:
        stripped = _IDENTIFIER_TIGHT_LABEL_RE.sub("", value, count=1)
    return stripped.strip() or value


def coerce_sku(value: object) -> str | None:
    text = coerce_text(value)
    if not text:
        return None
    text = strip_identifier_label_prefix(text)
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
