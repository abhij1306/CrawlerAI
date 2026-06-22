from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from app.core.config.extraction_rules import (
    DETAIL_IMAGE_IDENTITY_ALNUM_MIN_LENGTH,
    DETAIL_IMAGE_IDENTITY_NUMERIC_MIN_LENGTH,
    DETAIL_IMAGE_OPAQUE_HEX_MIN_LENGTH,
    DETAIL_TITLE_PATH_EXTENSION_PATTERN,
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


def detail_title_from_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    leaf = unquote(parsed.path.strip("/").rsplit("/", 1)[-1])
    leaf = re.sub(DETAIL_TITLE_PATH_EXTENSION_PATTERN, "", leaf, flags=re.IGNORECASE)
    return re.sub(r"[-_]+", " ", leaf).strip()


def detail_url_looks_like_product(url: str) -> bool:
    path = urlparse(str(url or "").lower()).path
    return any(marker in path for marker in _DETAIL_MARKERS)


def detail_url_is_collection_like(url: str) -> bool:
    parts = [part for part in urlparse(str(url or "").lower()).path.split("/") if part]
    return bool(parts and parts[-1] in _COLLECTION_TOKENS)


def detail_url_is_utility(url: str) -> bool:
    path = urlparse(str(url or "").lower()).path
    return any(f"/{token}" in path for token in _UTILITY_TOKENS)


def semantic_detail_identity_tokens(url: str) -> tuple[str, ...]:
    title = detail_title_from_url(url)
    return tuple(token for token in re.split(r"\W+", title.lower()) if len(token) >= 3)


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
