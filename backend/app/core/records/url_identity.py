from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from app.core.config.extraction_rules import (
    DETAIL_IMAGE_IDENTITY_ALNUM_MIN_LENGTH,
    DETAIL_IMAGE_IDENTITY_NUMERIC_MIN_LENGTH,
    DETAIL_IMAGE_OPAQUE_HEX_MIN_LENGTH,
    DETAIL_TITLE_ENDPOINT_FILENAME_PATTERN,
    DETAIL_TITLE_PATH_EXTENSION_PATTERN,
    DETAIL_TITLE_STYLE_ONLY_MAX_WORDS,
    DETAIL_TITLE_STYLE_ONLY_TOKENS,
    PRODUCT_ASSET_SEMANTIC_MIN_ANCHORED_ASSETS,
    PRODUCT_ASSET_SEMANTIC_MIN_DESCRIPTIVE_TOKENS,
    PRODUCT_ASSET_SEMANTIC_MIN_MATCH_TOKENS,
    PRODUCT_ASSET_SEMANTIC_NOISE_TOKENS,
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
        parsed.path.rstrip("/").rsplit("/", 1)[-1],
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
    if segments:
        terminal = re.sub(
            DETAIL_TITLE_PATH_EXTENSION_PATTERN,
            "",
            segments[-1],
            flags=re.IGNORECASE,
        )
        if _detail_url_title_segment_is_code(terminal):
            previous = segments[-2] if len(segments) >= 2 else ""
            previous_tokens = semantic_identity_tokens(previous)
            collection_code_shape = bool(
                re.search(r"/(?:collections?|categories?)/.+/products?/[^/]+/?$", parsed.path, re.IGNORECASE)
            )
            style_only_parent = bool(
                previous_tokens
                and len(previous_tokens) <= DETAIL_TITLE_STYLE_ONLY_MAX_WORDS
                and set(previous_tokens) <= DETAIL_TITLE_STYLE_ONLY_TOKENS
            )
            if collection_code_shape or style_only_parent:
                return ""
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
        if offset == 0 and re.fullmatch(
            DETAIL_TITLE_ENDPOINT_FILENAME_PATTERN, title, re.IGNORECASE
        ):
            return ""
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


def detail_url_resource_identity(url: str) -> str:
    text = str(url or "").strip()
    if not text or not detail_url_looks_like_product(text):
        return ""
    parsed = urlparse(text)
    host = str(parsed.hostname or "").casefold().strip(".")
    path = unquote(parsed.path).casefold().rstrip("/")
    return f"{host}{path}" if host and path else ""


def detail_url_looks_like_product(url: str) -> bool:
    path = urlparse(str(url or "").lower()).path
    if any(marker in path for marker in _DETAIL_MARKERS):
        return True
    segment = unquote(path.rstrip("/").rsplit("/", 1)[-1])
    if not segment.endswith((".html", ".htm")):
        return False
    title = re.sub(DETAIL_TITLE_PATH_EXTENSION_PATTERN, "", segment, flags=re.IGNORECASE)
    return len(semantic_identity_tokens(title)) >= DETAIL_URL_TITLE_FALLBACK_MIN_TOKENS


def detail_url_is_locale_root(url: str) -> bool:
    parts = [part for part in urlparse(str(url or "")).path.split("/") if part]
    if len(parts) != 1:
        return False
    locale = parts[0]
    return bool(
        (len(locale) == 2 and locale.isalpha())
        or (
            len(locale) == 5
            and locale[2] in {"-", "_"}
            and locale[:2].isalpha()
            and locale[3:].isalpha()
        )
    )


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
    code_conflicts = (
        frozenset(
            url
            for url, tokens in asset_tokens.items()
            if tokens and product_tokens.isdisjoint(tokens)
        )
        if product_tokens
        and any(product_tokens & tokens for tokens in asset_tokens.values())
        else frozenset()
    )
    return code_conflicts | _semantic_product_asset_conflicts(
        product_values, asset_urls
    )


def _semantic_product_asset_conflicts(
    product_values: tuple[object, ...], asset_urls: tuple[str, ...]
) -> frozenset[str]:
    product_tokens = {
        token
        for value in product_values
        for token in _product_asset_semantic_tokens(value)
        if token not in PRODUCT_ASSET_SEMANTIC_NOISE_TOKENS
    }
    if len(product_tokens) < PRODUCT_ASSET_SEMANTIC_MIN_MATCH_TOKENS:
        return frozenset()
    asset_tokens = {url: _asset_semantic_tokens(url) for url in asset_urls}
    anchored = sum(
        len(product_tokens & tokens) >= PRODUCT_ASSET_SEMANTIC_MIN_MATCH_TOKENS
        for tokens in asset_tokens.values()
    )
    conflicts = frozenset(
        url
        for url, tokens in asset_tokens.items()
        if len(tokens) >= PRODUCT_ASSET_SEMANTIC_MIN_DESCRIPTIVE_TOKENS
        and len(product_tokens & tokens) < PRODUCT_ASSET_SEMANTIC_MIN_MATCH_TOKENS
    )
    if anchored >= PRODUCT_ASSET_SEMANTIC_MIN_ANCHORED_ASSETS:
        return conflicts
    opaque_peer_count = sum(
        len(tokens) < PRODUCT_ASSET_SEMANTIC_MIN_DESCRIPTIVE_TOKENS
        for tokens in asset_tokens.values()
    )
    if len(conflicts) == 1 and opaque_peer_count >= 1:
        return conflicts
    return frozenset()


def _product_asset_semantic_tokens(value: object) -> tuple[str, ...]:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        return semantic_detail_identity_tokens(text)
    return semantic_identity_tokens(text)


def _asset_semantic_tokens(value: object) -> frozenset[str]:
    parsed = urlparse(unquote(str(value or "")))
    filename = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0]
    return frozenset(
        token
        for token in semantic_identity_tokens(stem)
        if token not in PRODUCT_ASSET_SEMANTIC_NOISE_TOKENS
        and not token.isdigit()
        and not (
            len(token) >= DETAIL_IMAGE_OPAQUE_HEX_MIN_LENGTH
            and re.fullmatch(r"[a-f0-9]+", token)
        )
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
