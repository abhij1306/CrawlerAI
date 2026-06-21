from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from app.core.config.extraction_rules import DETAIL_TITLE_PATH_EXTENSION_PATTERN

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


def title_looks_like_brand_shell(title: str, url: str = "") -> bool:
    text = re.sub(r"\W+", "", str(title or "")).lower()
    host = urlparse(str(url or "")).netloc.split(".")[-2:-1]
    return bool(text and host and text == re.sub(r"\W+", "", host[0]).lower())


def listing_detail_like_path(url: str) -> bool:
    return detail_url_looks_like_product(url)


def listing_url_is_structural(url: str) -> bool:
    return detail_url_is_collection_like(url) or detail_url_is_utility(url)
