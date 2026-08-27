from __future__ import annotations

import re
from urllib.parse import parse_qsl, unquote, urlparse, urlsplit

from app.core.config.extraction_rules import (
    DETAIL_IMAGE_IDENTITY_ALNUM_MIN_LENGTH,
    DETAIL_IMAGE_IDENTITY_NUMERIC_MIN_LENGTH,
    DETAIL_IMAGE_SHORT_STYLE_CODE_MAX_LENGTH,
    DETAIL_IMAGE_SHORT_STYLE_CODE_MIN_LENGTH,
    DETAIL_IMAGE_OPAQUE_HEX_MIN_LENGTH,
    DETAIL_IDENTITY_CODE_MAX_LENGTH,
    DETAIL_IDENTITY_CODE_MIN_LENGTH,
    DETAIL_TITLE_ENDPOINT_FILENAME_PATTERN,
    DETAIL_TITLE_PATH_EXTENSION_PATTERN,
    DETAIL_TITLE_PRECEDES_ID_MARKERS,
    DETAIL_TITLE_STYLE_ONLY_MAX_WORDS,
    DETAIL_TITLE_STYLE_ONLY_TOKENS,
    DETAIL_TITLE_URL_TOKEN_MIN_OVERLAP,
    DETAIL_TITLE_SEO_POLLUTION_PATTERN,
    DETAIL_TITLE_SEO_PREFIXES,
    DETAIL_TITLE_SEO_PREFIX_MIN_WORDS,
    PRODUCT_ASSET_SEMANTIC_MIN_ANCHORED_ASSETS,
    PRODUCT_ASSET_SEMANTIC_MIN_DESCRIPTIVE_TOKENS,
    PRODUCT_ASSET_SEMANTIC_MIN_MATCH_TOKENS,
    PRODUCT_ASSET_SEMANTIC_NOISE_TOKENS,
    TRACKING_PRESERVED_SHORT_QUERY_KEYS,
    VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO,
    DETAIL_URL_TITLE_CODE_PATTERN,
    DETAIL_URL_TITLE_FALLBACK_MIN_TOKENS,
    DETAIL_URL_TITLE_IGNORED_SEGMENTS,
    DETAIL_URL_TITLE_LOCALE_PATTERN,
    DETAIL_TITLE_IDENTITY_METADATA_KEYS,
    DETAIL_URL_TARGET_FLAGS,
    DETAIL_NON_LOWER_ALNUM_PATTERN,
    VARIANT_DOM_URL_AXIS_PARAM_PATTERN,
    VARIANT_URL_AXIS_PARAMS,
    VARIANT_URL_PATH_AXIS_MARKERS,
)
from app.core.records.field_url_normalization import canonical_public_record_url


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
_TITLE_OVERLAP_KEY, _TITLE_PRECISION_KEY = DETAIL_TITLE_IDENTITY_METADATA_KEYS
_URL_MATCH_FLAG, _URL_MISMATCH_FLAG = DETAIL_URL_TARGET_FLAGS


def selected_variant_axes(url: str) -> dict[str, str]:
    parsed = urlsplit(url)
    axes: dict[str, str] = {}
    fragment = unquote(parsed.fragment).strip()
    query_sources = (parsed.query, fragment.lstrip("#?"))
    for key, value in (
        pair
        for source in query_sources
        for pair in parse_qsl(source, keep_blank_values=False)
    ):
        raw_key = key.casefold()
        axis = VARIANT_URL_AXIS_PARAMS.get(raw_key)
        if axis is None and (
            match := re.match(VARIANT_DOM_URL_AXIS_PARAM_PATTERN, raw_key, flags=re.I)
        ):
            axis = VARIANT_URL_AXIS_PARAMS.get(match.group("axis").casefold())
        if axis and value.strip():
            axes[axis] = value.strip()
    for source in (parsed.path, fragment.split("?", 1)[0]):
        parts = [unquote(part).strip() for part in source.split("/") if part]
        for index, part in enumerate(parts[:-1]):
            axis = VARIANT_URL_PATH_AXIS_MARKERS.get(part.casefold())
            if axis and parts[index + 1]:
                axes.setdefault(axis, parts[index + 1])
    return axes


def detail_identity_ranking(
    value: object, *, fact_type: str, page_url: str
) -> tuple[dict[str, object], set[str]]:
    flags: set[str] = set()
    metadata: dict[str, object] = {}
    if fact_type == "product.url":
        candidate = canonical_public_record_url(
            value, surface="ecommerce_detail", field_name="url"
        )
        target = canonical_public_record_url(
            page_url, surface="ecommerce_detail", field_name="url"
        )
        if candidate and target:
            flags.add(_URL_MATCH_FLAG if candidate == target else _URL_MISMATCH_FLAG)
    if fact_type != "product.title":
        return metadata, flags
    target_tokens = set(semantic_detail_identity_tokens(page_url))
    title_tokens = set(semantic_identity_tokens(str(value or "")))
    overlap = len(target_tokens & title_tokens)
    metadata[_TITLE_OVERLAP_KEY] = overlap
    metadata[_TITLE_PRECISION_KEY] = (
        overlap / len(title_tokens) if title_tokens else 0.0
    )
    return metadata, flags


def detail_title_rank_components(
    flags: tuple[str, ...], metadata: dict[str, object]
) -> tuple[object, ...]:
    overlap = metadata.get(_TITLE_OVERLAP_KEY)
    precision = metadata.get(_TITLE_PRECISION_KEY)
    return (
        int("url_derived_title" in flags),
        -overlap if isinstance(overlap, int) else 0,
        -float(precision) if isinstance(precision, (int, float)) else 0.0,
    )


def detail_url_rank_components(flags: tuple[str, ...]) -> tuple[int, int]:
    return (int(_URL_MISMATCH_FLAG in flags), -int(_URL_MATCH_FLAG in flags))


def detail_title_is_bare_site_identity(value: str, *, page_url: str) -> bool:
    host = str(urlparse(page_url).hostname or "").casefold().removeprefix("www.")
    host_key = re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, "", host)
    title_key = re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, "", value.casefold())
    return bool(host_key and title_key == host_key)


def detail_title_identity_flags(
    value: str, *, page_url: str, url_contains_title_code: bool
) -> set[str]:
    flags: set[str] = set()
    url_tokens = set(semantic_detail_identity_tokens(page_url))
    title_tokens = set(semantic_identity_tokens(value))
    overlap = len(url_tokens & title_tokens)
    if len(title_tokens) == 1 and len(url_tokens) >= 2 and title_tokens < url_tokens:
        flags.add("truncated_title")
    if url_tokens and title_tokens:
        required = min(
            DETAIL_TITLE_URL_TOKEN_MIN_OVERLAP, len(url_tokens), len(title_tokens)
        )
        flags.add(
            "title_url_match"
            if overlap >= required or url_contains_title_code
            else "title_url_mismatch"
        )
    return flags


def detail_identity_codes_from_url(url: str) -> tuple[str, ...]:
    parsed = urlparse(str(url or ""))
    values = [
        parsed.path.rstrip("/").rsplit("/", 1)[-1],
        *_path_identity_codes(parsed.path),
        *[part for part in parsed.query.split("&")],
    ]
    out: list[str] = []
    for value in values:
        normalized = re.sub(r"[^A-Za-z0-9]+", "", value).upper()
        if len(normalized) >= 4 and normalized not in out:
            out.append(normalized)
    return tuple(out)


def detail_style_code_from_url(url: str) -> str:
    haystack = unquote(str(url or "")).upper()
    candidates = re.findall(r"\b[A-Z]{1,8}\d{3,7}-\d{2,5}\b", haystack)
    return candidates[-1] if candidates else ""


def detail_title_is_url_corroborated_style_code(value: str, url: str) -> bool:
    title = value.strip()
    if not title:
        return False
    # Normalize both sides to alphanumeric-only casefolded keys so style codes
    # with different separators or URL encoding still corroborate (e.g. title
    # "ABC-123" inside URL path "/abc_123" or "/abc%2D123").
    title_key = re.sub(r"[^A-Za-z0-9]+", "", title).casefold()
    if not title_key:
        return False
    url_key = re.sub(r"[^A-Za-z0-9]+", "", unquote(str(url or ""))).casefold()
    if title_key not in url_key:
        return False
    return _has_style_code_separator(title)


def _has_style_code_separator(value: str) -> bool:
    index = 0
    while index < len(value):
        if value[index].isalnum():
            index += 1
            continue
        separator_start = index
        while index < len(value) and not value[index].isalnum():
            index += 1
        left = value[:separator_start]
        right = value[index:]
        left_letters = len(left) - len(
            left.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
        )
        right_letters = len(right) - len(
            right.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
        )
        if (left_letters >= 2 and right[:1].isdigit()) or (
            left[-1:].isdigit() and right_letters >= 2
        ):
            return True
    return False


def detail_title_has_seo_pollution(
    value: str, _raw_value: str, words: list[str]
) -> bool:
    return bool(
        re.search(DETAIL_TITLE_SEO_POLLUTION_PATTERN, value, re.IGNORECASE)
        or (
            len(words) >= DETAIL_TITLE_SEO_PREFIX_MIN_WORDS
            and value.casefold().startswith(DETAIL_TITLE_SEO_PREFIXES)
        )
    )


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
    return not (len(word_tokens) >= 2 or (word_tokens and short_model_tokens))


def detail_title_from_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    segments = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    segments = _title_bearing_path_segments(segments)
    if _terminal_code_has_non_title_parent(parsed.path, segments):
        return ""
    for offset, segment in enumerate(reversed(segments)):
        title, terminal_endpoint = _usable_detail_title_segment(segment, offset=offset)
        if terminal_endpoint:
            return ""
        if title:
            return title
    return ""


def _title_bearing_path_segments(segments: list[str]) -> list[str]:
    """Drop suffixes after an opaque detail identity when its prefix is descriptive."""
    for index, segment in enumerate(segments[:-1]):
        if segment.casefold() not in DETAIL_TITLE_PRECEDES_ID_MARKERS:
            continue
        if not _detail_url_title_segment_is_code(segments[index + 1]):
            continue
        prefix = segments[:index]
        if prefix and len(semantic_identity_tokens(prefix[-1])) >= 2:
            return prefix
    return segments


def _terminal_code_has_non_title_parent(path: str, segments: list[str]) -> bool:
    if not segments:
        return False
    terminal = re.sub(
        DETAIL_TITLE_PATH_EXTENSION_PATTERN, "", segments[-1], flags=re.IGNORECASE
    )
    if not _detail_url_title_segment_is_code(terminal):
        return False
    previous = segments[-2] if len(segments) >= 2 else ""
    previous_tokens = semantic_identity_tokens(previous)
    collection_code_shape = re.search(
        r"/(?:collections?|categories?)/.+/products?/[^/]+/?$", path, re.IGNORECASE
    )
    style_only_parent = bool(
        previous_tokens
        and len(previous_tokens) <= DETAIL_TITLE_STYLE_ONLY_MAX_WORDS
        and set(previous_tokens) <= DETAIL_TITLE_STYLE_ONLY_TOKENS
    )
    return bool(collection_code_shape or style_only_parent)


def _usable_detail_title_segment(segment: str, *, offset: int) -> tuple[str, bool]:
    candidate = re.sub(
        DETAIL_TITLE_PATH_EXTENSION_PATTERN, "", segment, flags=re.IGNORECASE
    )
    title = re.sub(r"[-_]+", " ", candidate).strip()
    key = " ".join(re.findall(r"[a-z0-9]+", title.casefold()))
    rejected = bool(
        not title
        or key in DETAIL_URL_TITLE_IGNORED_SEGMENTS
        or re.fullmatch(DETAIL_URL_TITLE_LOCALE_PATTERN, candidate)
        or _detail_url_title_segment_is_code(candidate)
    )
    if rejected:
        return "", False
    if not offset and re.fullmatch(
        DETAIL_TITLE_ENDPOINT_FILENAME_PATTERN, title, re.IGNORECASE
    ):
        return "", True
    if (
        offset
        and len(semantic_identity_tokens(title)) < DETAIL_URL_TITLE_FALLBACK_MIN_TOKENS
    ):
        return "", False
    return title, False


def detail_urls_conflict(
    parent_url: str,
    candidate_url: str,
    *,
    strict_terminal_code: bool = True,
) -> bool:
    parent_codes = set(detail_identity_codes_from_url(parent_url))
    candidate_codes = set(detail_identity_codes_from_url(candidate_url))
    if not parent_codes or not candidate_codes:
        return False
    parent_terminal_codes = set(_terminal_path_identity_codes(parent_url))
    candidate_terminal_codes = set(_terminal_path_identity_codes(candidate_url))
    distinct_terminal_codes = bool(
        parent_terminal_codes
        and candidate_terminal_codes
        and parent_terminal_codes.isdisjoint(candidate_terminal_codes)
    )
    if distinct_terminal_codes and strict_terminal_code:
        return True
    if not distinct_terminal_codes and any(
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


def _terminal_path_identity_codes(url: str) -> tuple[str, ...]:
    path = urlparse(str(url or "")).path.rstrip("/")
    terminal = path.rsplit("/", 1)[-1]
    return _path_identity_codes(terminal)


def _path_identity_codes(path: str) -> tuple[str, ...]:
    return tuple(
        token.upper()
        for token in re.findall(r"[A-Za-z0-9]+", unquote(path))
        if DETAIL_IDENTITY_CODE_MIN_LENGTH
        <= len(token)
        <= DETAIL_IDENTITY_CODE_MAX_LENGTH
        and any(char.isalpha() for char in token)
        and any(char.isdigit() for char in token)
    )


def detail_url_resource_identity(url: str) -> str:
    text = str(url or "").strip()
    if not text or not detail_url_looks_like_product(text):
        return ""
    parsed = urlparse(text)
    host = str(parsed.hostname or "").casefold().strip(".")
    path = unquote(parsed.path).casefold().rstrip("/")
    return f"{host}{path}" if host and path else ""


def detail_url_marker_identity(url: str) -> str:
    text = str(url or "").strip()
    if not text or not detail_url_looks_like_product(text):
        return ""
    parsed = urlparse(text)
    host = str(parsed.hostname or "").casefold().strip(".")
    parts = [unquote(part).casefold() for part in parsed.path.split("/") if part]
    markers = {marker.strip("/") for marker in _DETAIL_MARKERS}
    for index in range(len(parts) - 2, -1, -1):
        if parts[index] in markers:
            return f"{host}/{parts[index]}/{parts[index + 1]}" if host else ""
    return ""


def detail_url_resource_conflicts(parent_url: str, candidate_url: str) -> bool:
    candidate = detail_url_resource_identity(candidate_url)
    if not candidate:
        return False
    parent = detail_url_resource_identity(parent_url)
    if candidate == parent:
        return False
    parent_marker = detail_url_marker_identity(parent_url)
    return not parent_marker or parent_marker != detail_url_marker_identity(
        candidate_url
    )


def detail_url_looks_like_product(url: str) -> bool:
    parsed = urlparse(str(url or "").lower())
    path = parsed.path
    if any(marker in path for marker in _DETAIL_MARKERS):
        return True
    segment = unquote(path.rstrip("/").rsplit("/", 1)[-1])
    if segment.startswith("product.") and any(
        key.casefold() in TRACKING_PRESERVED_SHORT_QUERY_KEYS
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if value.strip()
    ):
        return True
    if not segment.endswith((".html", ".htm")):
        return False
    title = re.sub(
        DETAIL_TITLE_PATH_EXTENSION_PATTERN, "", segment, flags=re.IGNORECASE
    )
    return len(semantic_identity_tokens(title)) >= DETAIL_URL_TITLE_FALLBACK_MIN_TOKENS


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


def _identity_token_sets_overlap(
    left: set[str] | frozenset[str],
    right: set[str] | frozenset[str],
) -> bool:
    return any(
        first == second
        or (min(len(first), len(second)) >= 6 and first.endswith(second))
        or (min(len(first), len(second)) >= 6 and second.endswith(first))
        for first in left
        for second in right
    )


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
            if tokens and not _identity_token_sets_overlap(product_tokens, tokens)
        )
        if product_tokens
        and any(
            _identity_token_sets_overlap(product_tokens, tokens)
            for tokens in asset_tokens.values()
        )
        else frozenset()
    )
    return (
        code_conflicts
        | _semantic_product_asset_conflicts(product_values, asset_urls)
        | _short_numeric_product_asset_conflicts(product_values, asset_urls)
        | _color_product_asset_conflicts(product_values, asset_urls)
    )


def _color_product_asset_conflicts(
    product_values: tuple[object, ...], asset_urls: tuple[str, ...]
) -> frozenset[str]:
    product_color_ids = {
        color_id for value in product_values for color_id in _url_color_ids(value)
    }
    if not product_color_ids:
        return frozenset()
    asset_color_ids = {url: set(_url_color_ids(url)) for url in asset_urls}
    if not any(
        color_ids and not color_ids.isdisjoint(product_color_ids)
        for color_ids in asset_color_ids.values()
    ):
        return frozenset()
    return frozenset(
        url
        for url, color_ids in asset_color_ids.items()
        if color_ids and color_ids.isdisjoint(product_color_ids)
    )


def _url_color_ids(value: object) -> tuple[str, ...]:
    parsed = urlparse(str(value or ""))
    ids = [
        match.group("id")
        for match in re.finditer(
            r"(?:^|/)colors?/(?P<id>\d{2,})(?=[_./?#]|$)",
            parsed.path,
            flags=re.IGNORECASE,
        )
    ]
    ids.extend(
        raw_value
        for key, raw_value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.casefold() in {"color", "colour"} and raw_value.isdigit()
    )
    return tuple(dict.fromkeys(ids))


def _short_numeric_product_asset_conflicts(
    product_values: tuple[object, ...], asset_urls: tuple[str, ...]
) -> frozenset[str]:
    product_text = " ".join(unquote(str(value or "")) for value in product_values)
    product_codes = _short_style_codes(product_text)
    product_suffixes = {
        token for token in re.findall(r"\d+", product_text) if 2 <= len(token) <= 4
    }
    product_style_tokens = {
        token for value in product_values for token in _commerce_identity_tokens(value)
    }
    asset_codes = {
        url: _short_style_codes(
            urlparse(unquote(str(url or ""))).path.rsplit("/", 1)[-1]
        )
        for url in asset_urls
    }
    exact_anchors = product_codes & {
        token for codes in asset_codes.values() for token in codes
    }
    suffix_anchors = _short_style_suffix_anchors(
        product_suffixes, product_style_tokens, asset_codes
    )
    if not exact_anchors and not suffix_anchors:
        return frozenset()
    return frozenset(
        url
        for url, codes in asset_codes.items()
        if _short_style_codes_conflict(codes, exact_anchors, suffix_anchors)
    )


def _short_style_codes(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\d+", value)
        if DETAIL_IMAGE_SHORT_STYLE_CODE_MIN_LENGTH
        <= len(token)
        <= DETAIL_IMAGE_SHORT_STYLE_CODE_MAX_LENGTH
    }


def _short_style_suffix_anchors(
    product_suffixes: set[str],
    product_style_tokens: set[str],
    asset_codes: dict[str, set[str]],
) -> set[str]:
    return {
        suffix
        for suffix in product_suffixes
        if any(
            code.endswith(suffix)
            and product_style_tokens & _commerce_identity_tokens(url)
            for url, codes in asset_codes.items()
            for code in codes
        )
    }


def _short_style_codes_conflict(
    codes: set[str], exact_anchors: set[str], suffix_anchors: set[str]
) -> bool:
    return bool(
        codes
        and exact_anchors.isdisjoint(codes)
        and not any(
            code.endswith(suffix) for code in codes for suffix in suffix_anchors
        )
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
    opaque_peer_count = sum(
        len(tokens) < PRODUCT_ASSET_SEMANTIC_MIN_DESCRIPTIVE_TOKENS
        for tokens in asset_tokens.values()
    )
    if anchored >= PRODUCT_ASSET_SEMANTIC_MIN_ANCHORED_ASSETS or (
        len(conflicts) == 1 and opaque_peer_count >= 1
    ):
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
        numeric_identity = token.isdigit() and (
            len(token) >= DETAIL_IMAGE_IDENTITY_NUMERIC_MIN_LENGTH
        )
        alphanumeric_identity = (
            len(token) >= DETAIL_IMAGE_IDENTITY_ALNUM_MIN_LENGTH
            and any(char.isalpha() for char in token)
            and any(char.isdigit() for char in token)
        )
        if numeric_identity or alphanumeric_identity:
            tokens.add(token)
    return frozenset(tokens)


def listing_detail_like_path(url: str) -> bool:
    return detail_url_looks_like_product(url)


def listing_url_is_structural(url: str) -> bool:
    return detail_url_is_collection_like(url) or detail_url_is_utility(url)
