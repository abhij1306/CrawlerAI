from __future__ import annotations

import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from app.services.config.product_intelligence import (
    DISCOVERY_GENERIC_PRODUCT_TOKENS,
    DISCOVERY_LISTING_PATH_SEGMENTS,
    DISCOVERY_NON_PRODUCT_PATH_SEGMENTS,
    DISCOVERY_PRODUCT_DETAIL_EXTENSIONS,
    DISCOVERY_PRODUCT_PATH_HINTS,
    DISCOVERY_VOLATILE_QUERY_PARAMS,
)

__all__ = (
    "candidate_dedupe_key",
    "clean_result_url",
    "looks_like_product_detail_url",
    "normalized_compare_url",
)


def clean_result_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def looks_like_product_detail_url(value: object) -> bool:
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return False
    path = unquote(parsed.path or "").casefold()
    if not path or path == "/":
        return False
    has_product_hint = any(hint in path for hint in DISCOVERY_PRODUCT_PATH_HINTS)
    segments = [segment for segment in path.strip("/").split("/") if segment]
    if any(_non_product_path_segment(segment) for segment in segments):
        return False
    if not has_product_hint and any(
        segment in DISCOVERY_LISTING_PATH_SEGMENTS for segment in segments
    ):
        return False
    if has_product_hint:
        return True
    terminal = segments[-1] if segments else ""
    if terminal.endswith(tuple(DISCOVERY_PRODUCT_DETAIL_EXTENSIONS)):
        return True
    if _descriptive_product_slug(terminal):
        return True
    return _product_id_like(terminal)


def normalized_compare_url(value: object) -> str:
    cleaned = clean_result_url(value)
    if not cleaned:
        return ""
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return ""
    return parsed._replace(fragment="").geturl().rstrip("/")


def candidate_dedupe_key(value: object) -> str:
    """Collapse same-product candidate URLs across size/color/tracking params."""
    cleaned = clean_result_url(value)
    if not cleaned:
        return ""
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return ""
    kept_params = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=False)
        if key.casefold() not in DISCOVERY_VOLATILE_QUERY_PARAMS
    ]
    query = urlencode(sorted(kept_params))
    host = (parsed.hostname or "").removeprefix("www.").lower()
    path = parsed.path.rstrip("/")
    return f"{host}{path}?{query}" if query else f"{host}{path}"


def _non_product_path_segment(segment: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(segment or "").casefold()).strip()
    return any(
        normalized == token or normalized.startswith(f"{token} ")
        for token in DISCOVERY_NON_PRODUCT_PATH_SEGMENTS
    )


def _descriptive_product_slug(value: str) -> bool:
    terminal = str(value or "").casefold()
    if "-" not in terminal:
        return False
    tokens = [
        _normalize_slug_token(token)
        for re_match in re.split(r"[^a-z0-9]+", terminal)
        if (token := re_match)
    ]
    alpha_tokens = [token for token in tokens if re.search(r"[a-z]", token)]
    distinctive_tokens = [
        token for token in alpha_tokens if token not in DISCOVERY_GENERIC_PRODUCT_TOKENS
    ]
    return len(alpha_tokens) >= 3 and len(set(distinctive_tokens)) >= 2


def _normalize_slug_token(value: str) -> str:
    token = str(value or "").casefold()
    if token in {"series", "business", "news", "analysis", "species"}:
        return token
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _product_id_like(value: str) -> bool:
    token = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    if len(token) < 6:
        return False
    return any(char.isdigit() for char in token) and any(
        char.isalpha() for char in token
    )
