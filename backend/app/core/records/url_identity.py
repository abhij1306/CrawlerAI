from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from app.core.config.extraction_rules import (
    DETAIL_IMAGE_IDENTITY_ALNUM_MIN_LENGTH,
    DETAIL_IMAGE_IDENTITY_NUMERIC_MIN_LENGTH,
    DETAIL_IMAGE_OPAQUE_HEX_MIN_LENGTH,
    DETAIL_TITLE_PATH_EXTENSION_PATTERN,
    VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO,
    DETAIL_URL_TITLE_CODE_PATTERN,
    DETAIL_URL_TITLE_FALLBACK_MIN_TOKENS,
    DETAIL_URL_TITLE_IGNORED_SEGMENTS,
    DETAIL_URL_TITLE_LOCALE_PATTERN,
)

_UTILITY_TOKENS = frozenset(
    {
        "cart",
        "checkout",
        "login",
        "account",
        "search",
        "wishlist",
        "compare",
        "privacy",
        "terms",
    }
)
_COLLECTION_TOKENS = frozenset(
    {
        "collections",
        "collection",
        "category",
        "categories",
        "shop",
        "catalog",
        "products",
        "jobs",
        "careers",
    }
)
_DETAIL_MARKERS = (
    "/dp/",
    "/p/",
    "/pd/",
    "/product/",
    "/products/",
    "/item/",
    "/job/",
    "/jobs/",
    "/position/",
    "/posting/",
)


def detail_identity_codes_from_url(url: str) -> tuple[str, ...]:
    parsed = urlparse(str(url or ""))
    values = [
        parsed.path.rsplit("/", 1)[-1],
        *[part for part in parsed.query.split("&")],
    ]
    out: list[str] = []
    for value in values:
        normalized = re.sub(r"[^A-Za-z0-9]+", "", value).upper()
        if len(normalized) >= 4 and normalized not in out:
            out.append(normalized)
    return tuple(out)


def _detail_url_title_segment_is_code(value: str) -> bool:
    if re.fullmatch(DETAIL_URL_TITLE_CODE_PATTERN, value) is None:
        return False
    tokens = re.findall(r"[A-Za-z0-9]+", value)
    word_tokens = [token for token in tokens if token.isalpha() and len(token) >= 3]
    short_model_tokens = [
        token
        for token in tokens
        if re.fullmatch(r"(?:[A-Za-z]+\d{1,3}|\d{1,3})", token)
    ]
    return not (
        len(word_tokens) >= 2
        or (word_tokens and short_model_tokens)
    )


def detail_title_from_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    segments = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    for offset, segment in enumerate(reversed(segments)):
        candidate = re.sub(
            DETAIL_TITLE_PATH_EXTENSION_PATTERN, "", segment, flags=re.IGNORECASE
        )
        title = re.sub(r"[-_]+", " ", candidate).strip()
        key = " ".join(re.findall(r"[a-z0-9]+", title.casefold()))
        if not title or key in DETAIL_URL_TITLE_IGNORED_SEGMENTS:
            continue
        if re.fullmatch(DETAIL_URL_TITLE_LOCALE_PATTERN, candidate):
            continue
        if _detail_url_title_segment_is_code(candidate):
            continue
        if offset and len(semantic_identity_tokens(title)) < DETAIL_URL_TITLE_FALLBACK_MIN_TOKENS:
            continue
        return title
    return ""


def detail_urls_conflict(parent_url: str, candidate_url: str) -> bool:
    parent_codes = set(detail_identity_codes_from_url(parent_url))
    candidate_codes = set(detail_identity_codes_from_url(candidate_url))
    if not parent_codes or not candidate_codes:
        return False
    if any(
        left == right or left in right or right in left
        for left in parent_codes
        for right in candidate_codes
    ):
        return False
    parent_tokens = set(semantic_detail_identity_tokens(parent_url))
    candidate_tokens = set(semantic_detail_identity_tokens(candidate_url))
    if not parent_tokens or not candidate_tokens:
        return False
    overlap = len(parent_tokens & candidate_tokens) / len(
        parent_tokens | candidate_tokens
    )
    return overlap <= VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO


def detail_url_looks_like_product(url: str) -> bool:
    path = urlparse(str(url or "").lower()).path
    return any(marker in path for marker in _DETAIL_MARKERS)


def detail_url_is_collection_like(url: str) -> bool:
    parts = [part for part in urlparse(str(url or "").lower()).path.split("/") if part]
    return bool(parts and parts[-1] in _COLLECTION_TOKENS)


def detail_url_is_utility(url: str) -> bool:
    path = urlparse(str(url or "").lower()).path
    return any(f"/{token}" in path for token in _UTILITY_TOKENS)


def semantic_identity_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if len(token) >= 3 or (token.isdigit() and len(token) >= 2)
    )


def semantic_detail_identity_tokens(url: str) -> tuple[str, ...]:
    return semantic_identity_tokens(detail_title_from_url(url))


def conflicting_product_asset_urls(
    product_values: tuple[object, ...], asset_urls: tuple[str, ...]
) -> frozenset[str]:
    """Return asset URLs that conflict with available product identity evidence.

    A URL is marked conflicting only when at least one peer asset shares a product
    identity token while that URL has identity tokens but shares none. This
    conditional, some-but-not-all match prevents false positives when no asset can
    be tied to the product identity at all.

    Args:
        product_values: Product URLs or identifiers used to derive identity tokens.
        asset_urls: Candidate asset URLs to compare with those product tokens.

    Returns:
        A frozenset containing candidate URLs with conflicting identity tokens.
    """
    product_tokens: set[str] = set()
    for value in product_values:
        product_tokens.update(_commerce_identity_tokens(value))
    asset_tokens = {url: _commerce_identity_tokens(url) for url in asset_urls}
    if not product_tokens or not any(
        product_tokens & tokens for tokens in asset_tokens.values()
    ):
        return frozenset()
    return frozenset(
        url
        for url, tokens in asset_tokens.items()
        if tokens and product_tokens.isdisjoint(tokens)
    )


def _commerce_identity_tokens(value: object) -> frozenset[str]:
    parsed = urlparse(unquote(str(value or "")))
    terminal = f"{parsed.path.rsplit('/', 1)[-1]}&{parsed.query}".casefold()
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", terminal):
        if (
            len(token) >= DETAIL_IMAGE_OPAQUE_HEX_MIN_LENGTH
            and any(char.isalpha() for char in token)
            and re.fullmatch(r"[a-f0-9]+", token)
        ):
            continue
        if token.isdigit() and len(token) >= DETAIL_IMAGE_IDENTITY_NUMERIC_MIN_LENGTH:
            tokens.add(token)
        elif (
            len(token) >= DETAIL_IMAGE_IDENTITY_ALNUM_MIN_LENGTH
            and any(char.isalpha() for char in token)
            and any(char.isdigit() for char in token)
        ):
            tokens.add(token)
    return frozenset(tokens)


def title_looks_like_brand_shell(title: str, url: str = "") -> bool:
    text = re.sub(r"\W+", "", str(title or "")).lower()
    host = urlparse(str(url or "")).netloc.split(".")[-2:-1]
    return bool(text and host and text == re.sub(r"\W+", "", host[0]).lower())


def listing_detail_like_path(url: str) -> bool:
    return detail_url_looks_like_product(url)


def listing_url_is_structural(url: str) -> bool:
    return detail_url_is_collection_like(url) or detail_url_is_utility(url)
