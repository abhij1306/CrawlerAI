from __future__ import annotations

__all__ = (
    "prune_irrelevant_detail_dom_nodes",
    "detail_title_fallback_looks_like_code",
    "listing_url_is_structural",
    "listing_detail_like_path",
    "detail_identity_codes_match",
    "detail_identity_codes_from_record_fields",
    "detail_identity_codes_from_url",
    "detail_query_identity_codes_from_url",
    "detail_identity_tokens",
    "detail_redirect_identity_is_mismatched",
    "detail_slug_title_fallback_from_url",
    "detail_title_from_url",
    "detail_url_candidate_is_low_signal",
    "detail_url_is_collection_like",
    "detail_url_is_utility",
    "detail_url_looks_like_product",
    "detail_url_matches_requested_identity",
    "preferred_detail_identity_url",
    "record_matches_requested_detail_identity",
    "semantic_detail_identity_tokens",
)

import json
import logging
import re
from urllib.parse import parse_qsl, urlparse

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    CANDIDATE_PLACEHOLDER_VALUES,
    DETAIL_COLLECTION_PATH_TOKENS,
    DETAIL_GENERIC_TERMINAL_TOKENS,
    DETAIL_IDENTITY_CODE_MIN_LENGTH,
    DETAIL_NOISE_SECTION_SELECTORS,
    DETAIL_IDENTITY_STOPWORDS,
    DETAIL_MODEL_CONFLICT_MIN_SHARED_WORDS,
    DETAIL_MODEL_NUMBER_TOKEN_PATTERNS,
    DETAIL_MODEL_SMALL_NUMERIC_TOKEN_PATTERN,
    DETAIL_NON_PAGE_FILE_EXTENSIONS,
    DETAIL_PRODUCT_PATH_TOKENS,
    DETAIL_SEARCH_QUERY_KEYS,
    DETAIL_TITLE_FALLBACK_CODE_PATTERN,
    DETAIL_TITLE_FALLBACK_MIN_SEMANTIC_TOKENS,
    DETAIL_UTILITY_PATH_TOKENS,
    AVAILABILITY_UNKNOWN,
    JOB_LISTING_DETAIL_ROOT_MARKERS,
    JOB_LISTING_DETAIL_PATH_MARKERS,
    LISTING_CATEGORY_PATH_SEGMENTS,
    LISTING_CATEGORY_PATH_PREFIXES,
    LISTING_DETAIL_PATH_MARKERS,
    LISTING_LOCALE_PATH_SEGMENT_PATTERN,
    LISTING_NON_LISTING_PATH_TOKENS,
    LISTING_PRODUCT_DETAIL_ID_RE,
    LISTING_STRUCTURAL_QUERY_CATEGORY_TOKENS,
    LISTING_STRUCTURAL_QUERY_FILTER_TOKENS,
    PRODUCT_SLUG_MIN_TERMINAL_TOKENS,
    YEAR_SLUG_PATTERN,
)
from app.services.config.public_record_policy import (
    PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS,
    PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES,
)
from app.services.config.surface_hints import detail_path_hints
from app.services.extract.listing_candidate_ranking import (
    job_listing_url_is_hub as _job_listing_url_is_hub,
    job_listing_url_looks_like_posting as _job_listing_url_looks_like_posting,
)
from app.services.shared.field_coerce import (
    PRODUCT_URL_HINTS,
    absolute_url,
    clean_text,
    is_title_noise,
    text_or_none,
)
from app.services.field_url_normalization import same_site
from app.services.extract.detail.identity.jsonld_identity import (
    jsonld_item_candidate_record,
    jsonld_item_product_name,
    jsonld_item_supports_identity,
    jsonld_items,
    prune_duplicate_product_headings,
)

logger = logging.getLogger(__name__)
_DETAIL_IDENTITY_QUERY_KEYS = frozenset(
    str(value).strip().lower()
    for value in tuple(PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS or ())
    if str(value).strip()
)
_DETAIL_IDENTITY_QUERY_PREFIXES = tuple(
    str(value).strip().lower()
    for value in tuple(PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES or ())
    if str(value).strip()
)
_DETAIL_URL_PLACEHOLDER_SEGMENTS = frozenset(
    {
        str(value).strip().lower()
        for value in tuple(CANDIDATE_PLACEHOLDER_VALUES or ())
        if str(value).strip()
    }
)
_LISTING_CATEGORY_PATH_SEGMENTS = frozenset(
    {
        str(value).strip().lower()
        for value in tuple(LISTING_CATEGORY_PATH_SEGMENTS or ())
        if str(value).strip()
    }
)
_LISTING_LOCALE_PATH_SEGMENT_RE = re.compile(
    str(LISTING_LOCALE_PATH_SEGMENT_PATTERN or ""), re.IGNORECASE
)
_LOWER_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_MIXED_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")
_HTML_SUFFIX_RE = re.compile(r"\.htm(?:l)?$", re.IGNORECASE)
_SLUG_SEPARATOR_RE = re.compile(r"[-_]+")


def _path_segment_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[\-\.]+", str(value or "").strip().lower())
        if token
    }


def _listing_url_has_product_detail_identity(url: str) -> bool:
    return LISTING_PRODUCT_DETAIL_ID_RE.search(str(url or "")) is not None


def _jsonld_item_matches_requested_identity(
    item: dict[str, object],
    *,
    page_url: str,
    requested_page_url: str,
) -> bool:
    raw_url = item.get("url") or item.get("@id")
    if raw_url:
        abs_url = absolute_url(page_url, raw_url)
        if _detail_url_matches_requested_identity(
            abs_url,
            requested_page_url=requested_page_url,
        ):
            return True
    return _record_matches_requested_detail_identity(
        jsonld_item_candidate_record(item),
        requested_page_url=requested_page_url,
    )


def prune_irrelevant_detail_dom_nodes(
    soup: BeautifulSoup,
    *,
    page_url: str,
    requested_page_url: str,
) -> None:
    pruned_product_names: list[str] = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(script.get_text())
            items = jsonld_items(payload)
            if not items:
                continue

            match_found = False
            script_product_name = ""
            for item in items:
                if not isinstance(item, dict) or not jsonld_item_supports_identity(item):
                    continue
                if not script_product_name:
                    script_product_name = jsonld_item_product_name(item)
                if _jsonld_item_matches_requested_identity(
                    item,
                    page_url=page_url,
                    requested_page_url=requested_page_url,
                ):
                    match_found = True
                    break

            if not match_found:
                if script_product_name:
                    pruned_product_names.append(script_product_name)
                script.decompose()
        except json.JSONDecodeError as exc:
            logger.debug(
                "Skipping malformed detail JSON-LD",
                extra={
                    "page_url": page_url,
                    "requested_page_url": requested_page_url,
                    "error": str(exc),
                    "snippet": script.get_text()[:200],
                },
            )
            continue

    if pruned_product_names:
        prune_duplicate_product_headings(
            soup,
            pruned_product_names=pruned_product_names,
        )

    for selector in tuple(DETAIL_NOISE_SECTION_SELECTORS or ()):
        for node in soup.select(str(selector)):
            node.decompose()


def _listing_url_has_category_path_segment(path: str) -> bool:
    segments = [
        segment.strip().lower()
        for segment in str(path or "").split("/")
        if segment.strip()
    ]
    for segment in segments:
        # Broader split is intentional here, unlike _path_segment_tokens:
        # _LISTING_CATEGORY_PATH_SEGMENTS may be embedded behind "_" or mixed punctuation.
        segment_tokens = {token for token in _LOWER_NON_ALNUM_RE.split(segment) if token}
        if segment in _LISTING_CATEGORY_PATH_SEGMENTS:
            return True
        if _LISTING_CATEGORY_PATH_SEGMENTS.intersection(segment_tokens):
            return True
    return False


def _listing_query_looks_structural(query: str) -> bool:
    pairs = [
        (
            str(key or "").strip().lower(),
            str(value or "").strip().lower(),
        )
        for key, value in parse_qsl(str(query or ""), keep_blank_values=True)
    ]
    if not pairs:
        return False
    generic_filter_keys = {"f", "filter", "filters", "facet", "facets", "rf"}
    filter_tokens = tuple(
        str(token or "").strip().lower().rstrip("=")
        for token in LISTING_STRUCTURAL_QUERY_FILTER_TOKENS
        if str(token or "").strip()
    )
    for key, value in pairs:
        if key not in generic_filter_keys:
            continue
        haystack = " ".join(part for part in (key, value) if part)
        if any(
            token in haystack for token in LISTING_STRUCTURAL_QUERY_CATEGORY_TOKENS
        ) and any(token in haystack for token in filter_tokens):
            return True
    return False


def _strip_listing_locale_segments(segments: list[str]) -> list[str]:
    index = 0
    while index < len(segments) and _LISTING_LOCALE_PATH_SEGMENT_RE.fullmatch(
        segments[index]
    ):
        index += 1
    return segments[index:]


def _listing_url_is_sibling_category(
    *,
    candidate_path: str,
    page_path: str,
) -> bool:
    if _listing_url_has_category_path_segment(
        page_path
    ) and _listing_url_has_category_path_segment(candidate_path):
        return True
    return any(
        page_path.startswith(prefix) and candidate_path.startswith(prefix)
        for prefix in LISTING_CATEGORY_PATH_PREFIXES
    )


def _listing_url_is_locale_sibling_category(
    *,
    candidate_path: str,
    page_path: str,
) -> bool:
    candidate_segments = [seg for seg in candidate_path.strip("/").split("/") if seg]
    page_segments = [seg for seg in page_path.strip("/").split("/") if seg]
    if not candidate_segments or not page_segments:
        return False
    candidate_remainder_segments = _strip_listing_locale_segments(candidate_segments)
    page_remainder_segments = _strip_listing_locale_segments(page_segments)
    if len(candidate_remainder_segments) == len(candidate_segments) and len(
        page_remainder_segments
    ) == len(page_segments):
        return False
    if not candidate_remainder_segments or not page_remainder_segments:
        return False
    return _listing_url_is_sibling_category(
        candidate_path="/" + "/".join(candidate_remainder_segments),
        page_path="/" + "/".join(page_remainder_segments),
    )


def _listing_terminal_looks_like_product_slug(
    *,
    terminal_token_list: list[str],
    terminal_raw: str,
) -> bool:
    year_led_terminal = bool(
        terminal_token_list and re.fullmatch(YEAR_SLUG_PATTERN, terminal_token_list[0])
    )
    return (
        len(terminal_token_list) >= PRODUCT_SLUG_MIN_TERMINAL_TOKENS
        and any(re.search(r"[a-z]", token) for token in terminal_token_list)
        and "-" in terminal_raw
        and not year_led_terminal
    )


def _listing_url_has_non_listing_prefix(
    *,
    leading_tokens: list[set[str]],
    leading_raw: list[str],
    non_listing_tokens: set[str],
) -> bool:
    return any(tokens & non_listing_tokens for tokens in leading_tokens) or any(
        segment in non_listing_tokens for segment in leading_raw
    )


def listing_url_is_structural(url: str, page_url: str) -> bool:
    lowered = url.lower()
    if lowered.startswith(("javascript:", "#", "mailto:")):
        return True
    if lowered == page_url.lower():
        return True
    try:
        parsed = urlparse(url)
        page_parsed = urlparse(page_url)
        if parsed.path in ("", "/"):
            return True
        same_path = parsed.path.rstrip("/").lower() == page_parsed.path.rstrip("/").lower()
        if same_path and _job_detail_query_has_identity(parsed.query):
            return False
        if same_path:
            return True
        if _listing_url_has_product_detail_identity(lowered):
            return False
        # Detail-like URLs (product pages) are exempt from sibling-category
        # rejection even when they share a category path prefix with the page.
        # This covers sites like B&H Photo where product URLs start with /c/product/
        # and the listing page starts with /c/buy/ — both share /c/ but the
        # product URL is clearly a detail page, not a sibling category.
        if listing_detail_like_path(lowered, is_job=False):
            return False
        # Sibling-category rejection.
        # When both the listing page and the candidate share a known
        # category path prefix (e.g. both /c/<slug>), the candidate is
        # a navigation link to another category, not a product.
        candidate_path = parsed.path.lower()
        page_path = page_parsed.path.lower()
        if _listing_url_is_sibling_category(
            candidate_path=candidate_path,
            page_path=page_path,
        ) or _listing_url_is_locale_sibling_category(
            candidate_path=candidate_path,
            page_path=page_path,
        ):
            return True
        raw_segments = [
            segment.strip().lower()
            for segment in parsed.path.split("/")
            if segment.strip()
        ]
        tokenized_segments = [_path_segment_tokens(segment) for segment in raw_segments]
        terminal_tokens = tokenized_segments[-1] if tokenized_segments else set()
        terminal_raw = raw_segments[-1] if raw_segments else ""
        non_listing_tokens = set(LISTING_NON_LISTING_PATH_TOKENS)
        if terminal_tokens & non_listing_tokens or terminal_raw in non_listing_tokens:
            return True
        leading_tokens = tokenized_segments[:-1] if len(tokenized_segments) <= 2 else []
        leading_raw = raw_segments[:-1] if len(raw_segments) <= 2 else []
        terminal_token_list = [
            token for token in re.split(r"[-.]+", terminal_raw) if token
        ]
        terminal_looks_like_product_slug = _listing_terminal_looks_like_product_slug(
            terminal_token_list=terminal_token_list,
            terminal_raw=terminal_raw,
        )
        if (
            not terminal_looks_like_product_slug
            and _listing_query_looks_structural(parsed.query)
        ):
            return True
        if not terminal_looks_like_product_slug and _listing_url_has_non_listing_prefix(
            leading_tokens=leading_tokens,
            leading_raw=leading_raw,
            non_listing_tokens=non_listing_tokens,
        ):
            return True
    except ValueError:
        logger.debug("URL structural check failed for %s", page_url, exc_info=True)
    return False


def listing_detail_like_path(url: str, *, is_job: bool) -> bool:
    lowered = url.lower()
    if is_job:
        return _job_detail_like_path(lowered)
    parsed = urlparse(lowered)
    if _listing_url_has_product_detail_identity(lowered):
        return True
    if _listing_url_has_category_path_segment(parsed.path):
        return False
    segments = [
        segment.strip().lower() for segment in parsed.path.split("/") if segment.strip()
    ]
    if "products" in segments:
        products_index = segments.index("products")
        tail_segments = segments[products_index + 1 :]
        if (
            len(tail_segments) > 2
            and not parsed.query
            and not any(re.search(r"\d", segment) for segment in tail_segments[-2:])
        ):
            return False
    if any(
        _detail_marker_matches(lowered, marker)
        for marker in LISTING_DETAIL_PATH_MARKERS
    ):
        return True
    hints = detail_path_hints("ecommerce_detail")
    return any(_detail_marker_matches(lowered, marker) for marker in hints)


def _detail_marker_matches(url: str, marker: str) -> bool:
    """Check if *marker* matches in *url* at a segment boundary.

    Prevents false positives like ``/product`` matching ``/product-care``
    or ``/product-advice``.  When the marker does NOT end with a path
    separator, the character following the match must be a boundary
    (``/``, ``?``, ``.``, ``#``, ``&``, end-of-string, or a digit) — not
    a hyphen or letter continuation.  Markers ending with ``/`` already
    encode their own boundary and are matched as plain substrings.
    """
    # Markers that end with '/' already have a built-in boundary.
    if marker.endswith("/"):
        return marker in url
    start = 0
    while True:
        idx = url.find(marker, start)
        if idx < 0:
            return False
        end = idx + len(marker)
        if end >= len(url):
            return True
        next_char = url[end]
        # Valid boundary: path separator, query, fragment, or digit (product ID)
        if next_char in "/?.#&" or next_char.isdigit():
            return True
        # Continuation character (hyphen, letter, underscore) → not a boundary
        start = end


def _job_detail_like_path(url: str) -> bool:
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return False
    terminal = segments[-1].strip().lower()
    if not terminal or _job_listing_url_is_hub(url):
        return False
    query = parsed.query.lower()
    if _job_detail_query_has_identity(query):
        return True
    if any(marker in parsed.path.lower() for marker in JOB_LISTING_DETAIL_PATH_MARKERS):
        return True
    if _job_listing_url_looks_like_posting(url):
        return True
    if re.match(r"jobs?-\d", terminal):
        return True
    for index, segment in enumerate(segments[:-1]):
        normalized = segment.strip().lower()
        if normalized not in JOB_LISTING_DETAIL_ROOT_MARKERS:
            continue
        next_segment = segments[index + 1].strip().lower()
        if next_segment and not _job_listing_url_is_hub(
            f"https://example.com/{next_segment}/"
        ):
            return True
    return False


def _job_detail_query_has_identity(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(token in lowered for token in ("showjob=", "jobid=", "job_id=", "gh_jid="))


def _detail_url_path_segments(url: str) -> list[str]:
    parsed = urlparse(str(url or ""))
    segments = [
        segment for segment in str(parsed.path or "").strip("/").split("/") if segment
    ]
    fragment = str(parsed.fragment or "").strip()
    if fragment:
        fragment_path = fragment.split("?", 1)[0].split("&", 1)[0].strip()
        if "/" in fragment_path:
            segments.extend(
                segment for segment in fragment_path.strip("!/").split("/") if segment
            )
    return segments


def _detail_title_from_url(page_url: str) -> str | None:
    path_segments = _detail_url_path_segments(page_url)
    if not path_segments:
        return None
    generic_terminal_tokens = set(DETAIL_GENERIC_TERMINAL_TOKENS)
    for index in range(len(path_segments) - 1, -1, -1):
        segment = path_segments[index]
        terminal = _HTML_SUFFIX_RE.sub("", segment)
        if _detail_segment_is_shop_merchant_namespace(path_segments, index):
            continue
        if _detail_terminal_is_ignored(
            terminal,
            generic_terminal_tokens=generic_terminal_tokens,
        ):
            continue
        if _detail_segment_looks_like_identity_code(terminal):
            if _detail_terminal_parent_is_collection(path_segments, index):
                return None
            continue
        title = clean_text(_SLUG_SEPARATOR_RE.sub(" ", terminal))
        if title and not is_title_noise(title):
            return title
    return None


def _detail_terminal_embedded_codes_are_generic(
    terminal: str,
    *,
    generic_terminal_tokens: set[str],
) -> bool:
    embedded_codes = [
        normalized
        for match in re.findall(
            rf"[A-Za-z0-9]{{{DETAIL_IDENTITY_CODE_MIN_LENGTH},}}", terminal
        )
        if (normalized := _normalized_detail_identity_code(match))
    ]
    if not embedded_codes:
        return False
    alpha_chunks = [chunk.lower() for chunk in re.findall(r"[A-Za-z]+", terminal)]
    return not alpha_chunks or all(
        set(_path_segment_tokens(chunk)) <= generic_terminal_tokens
        for chunk in alpha_chunks
    )


def _detail_terminal_is_generic(
    terminal: str,
    *,
    generic_terminal_tokens: set[str],
) -> bool:
    terminal_tokens = _path_segment_tokens(terminal)
    return terminal in generic_terminal_tokens or bool(
        terminal_tokens and terminal_tokens <= generic_terminal_tokens
    )


def _detail_terminal_is_ignored(
    terminal: str,
    *,
    generic_terminal_tokens: set[str],
) -> bool:
    if not terminal or terminal.isdigit():
        return True
    if re.fullmatch(r"[a-z]{2}(?:[_-][a-z]{2})?", terminal, re.I):
        return True
    if _detail_terminal_embedded_codes_are_generic(
        terminal,
        generic_terminal_tokens=generic_terminal_tokens,
    ):
        return True
    if re.fullmatch(r"[a-f0-9]{8,}(?:-[a-f0-9]{4,}){2,}", terminal, re.I):
        return True
    return _detail_terminal_is_generic(
        terminal,
        generic_terminal_tokens=generic_terminal_tokens,
    )


def _detail_terminal_parent_is_collection(
    path_segments: list[str],
    index: int,
) -> bool:
    parent_segment = str(path_segments[index - 1]).strip().lower() if index > 0 else ""
    return parent_segment in {"product", "products", "item", "items"}


def _detail_segment_is_shop_merchant_namespace(
    path_segments: list[str],
    index: int,
) -> bool:
    if index <= 0 or index + 1 >= len(path_segments):
        return False
    previous_segment = str(path_segments[index - 1]).strip().lower()
    next_segment = str(path_segments[index + 1]).strip().lower()
    return previous_segment == "shop" and next_segment in {"p", "product", "products"}


def _detail_url_candidate_is_low_signal(
    candidate_url: object, *, page_url: str
) -> bool:
    candidate = text_or_none(candidate_url)
    if not candidate:
        return False
    candidate_parsed = urlparse(candidate)
    page_parsed = urlparse(page_url)
    candidate_host = (candidate_parsed.hostname or "").lower()
    page_host = (page_parsed.hostname or "").lower()
    if candidate_host and page_host and not same_site(page_url, candidate):
        return True
    candidate_path = str(candidate_parsed.path or "").strip()
    page_path = str(page_parsed.path or "").strip()
    if any(
        candidate_path.lower().endswith(ext) for ext in DETAIL_NON_PAGE_FILE_EXTENSIONS
    ):
        return True
    candidate_segments = {
        segment.strip().lower()
        for segment in candidate_path.split("/")
        if segment.strip()
    }
    if candidate_segments & _DETAIL_URL_PLACEHOLDER_SEGMENTS:
        return True
    if same_site(page_url, candidate) and _detail_url_is_utility(candidate):
        return True
    return page_path not in {"", "/"} and candidate_path in {"", "/"}


def _preferred_detail_identity_url(
    *,
    surface: str,
    page_url: str,
    requested_page_url: str | None,
) -> str:
    if str(surface or "").strip().lower() != "ecommerce_detail":
        return page_url
    requested = text_or_none(requested_page_url) or text_or_none(page_url)
    current = text_or_none(page_url)
    if not requested or not current or requested == current:
        return current or requested or page_url
    if not same_site(requested, current):
        return current
    if not _detail_url_looks_like_product(requested):
        return current
    if not _detail_url_is_utility(current):
        return current
    return requested


def _detail_url_looks_like_product(url: str) -> bool:
    path_segments = _detail_url_path_segments(url)
    path = f"/{'/'.join(path_segments)}".lower() if path_segments else ""
    if any(hint in path for hint in PRODUCT_URL_HINTS):
        return True
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return False
    terminal = next(
        (segment.strip().lower() for segment in reversed(segments) if segment.strip()),
        "",
    )
    if not terminal or terminal.isdigit():
        terminal = next(
            (
                segment.strip().lower()
                for segment in reversed(segments[:-1])
                if segment.strip() and not segment.strip().isdigit()
            ),
            "",
        )
        if not terminal:
            return False
    if _detail_url_is_utility(url):
        return False
    if _detail_url_is_collection_like(url):
        return False
    if any(
        token in terminal for token in ("category", "collections", "search", "sale")
    ):
        return False
    return any(separator in terminal for separator in ("-", "_"))


def _detail_url_is_utility(url: str) -> bool:
    path_tokens = _detail_url_path_tokens(url)
    if any(token in path_tokens for token in DETAIL_PRODUCT_PATH_TOKENS):
        return False
    if any(token in path_tokens for token in DETAIL_UTILITY_PATH_TOKENS):
        return True
    query_keys = {
        str(key).strip().lower()
        for key, value in parse_qsl(
            str(urlparse(url).query or ""), keep_blank_values=False
        )
        if str(key).strip() and str(value).strip()
    }
    if not query_keys:
        return False
    return any(
        str(key).strip().lower() in query_keys for key in DETAIL_SEARCH_QUERY_KEYS
    )


def _detail_url_is_collection_like(url: str) -> bool:
    path_tokens = _detail_url_path_tokens(url)
    if any(token in path_tokens for token in DETAIL_PRODUCT_PATH_TOKENS):
        return False
    return any(token in path_tokens for token in DETAIL_COLLECTION_PATH_TOKENS)


def _detail_url_path_tokens(url: str) -> set[str]:
    return {
        token
        for token in _LOWER_NON_ALNUM_RE.split(
            "/".join(_detail_url_path_segments(url)).lower()
        )
        if token
    }


def _record_matches_requested_detail_identity(
    record: dict[str, object],
    *,
    requested_page_url: str,
) -> bool:
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    requested_query_codes = _detail_query_identity_codes_from_url(requested_page_url)
    record_field_codes = _detail_identity_codes_from_record_fields(record)
    if requested_query_codes and detail_identity_codes_match(
        requested_query_codes,
        record_field_codes,
    ):
        return True
    if detail_identity_codes_match(requested_codes, record_field_codes):
        return True
    record_url_codes = _detail_identity_codes_from_url(record.get("url"))
    record_query_codes = _detail_query_identity_codes_from_url(record.get("url"))
    if requested_query_codes and detail_identity_codes_match(
        requested_query_codes,
        record_query_codes,
    ):
        return True
    if requested_query_codes and record_query_codes:
        return False
    requested_title = _detail_title_from_url(requested_page_url)
    requested_tokens = _detail_identity_tokens(requested_title)
    candidate_tokens = _detail_identity_tokens(record.get("title"))
    if not candidate_tokens:
        candidate_tokens = _detail_identity_tokens(record.get("description"))
    title_matches = _detail_token_overlap_matches(requested_tokens, candidate_tokens)
    if not title_matches and requested_tokens:
        supplemental_tokens = _detail_identity_record_tokens(record)
        title_matches = _detail_token_overlap_matches(
            requested_tokens,
            supplemental_tokens,
        )
    if title_matches:
        return True
    return bool(
        requested_codes
        and not requested_tokens
        and detail_identity_codes_match(requested_codes, record_url_codes)
    )


def _detail_identity_record_tokens(record: dict[str, object]) -> set[str]:
    tokens: set[str] = set()
    for field_name in ("title", "brand", "color", "size", "description"):
        tokens.update(_detail_identity_tokens(record.get(field_name)))
    return tokens


def _detail_token_overlap_matches(
    requested_tokens: set[str],
    candidate_tokens: set[str],
) -> bool:
    if not requested_tokens or not candidate_tokens:
        return False
    overlap = requested_tokens & candidate_tokens
    if len(requested_tokens) == 1:
        return bool(overlap)
    return len(overlap) >= min(2, len(requested_tokens))


def _detail_requested_identity_text(page_url: object) -> str:
    raw_url = str(page_url or "")
    title = _detail_title_from_url(raw_url)
    if title:
        return title
    generic_terminal_tokens = set(DETAIL_GENERIC_TERMINAL_TOKENS)
    path_segments = _detail_url_path_segments(raw_url)
    for index in range(len(path_segments) - 1, -1, -1):
        if _detail_segment_is_shop_merchant_namespace(path_segments, index):
            continue
        segment = path_segments[index]
        terminal = _HTML_SUFFIX_RE.sub("", segment)
        if not terminal or terminal.isdigit():
            continue
        terminal_tokens = _path_segment_tokens(terminal)
        if terminal_tokens and terminal_tokens <= generic_terminal_tokens:
            continue
        title = clean_text(_SLUG_SEPARATOR_RE.sub(" ", terminal))
        semantic_tokens = _semantic_detail_identity_tokens(title)
        if _detail_segment_looks_like_identity_code(terminal) and len(semantic_tokens) < 2:
            continue
        if semantic_tokens:
            return title
    return ""


def _detail_model_numbers_conflict(
    requested_title: object,
    candidate_title: object,
    *,
    record: dict[str, object] | None = None,
) -> bool:
    requested_numbers = _detail_model_number_tokens(requested_title)
    candidate_numbers = _detail_model_number_tokens(candidate_title)
    if not requested_numbers or not candidate_numbers:
        requested_numbers = _detail_small_numeric_model_tokens(requested_title)
        candidate_numbers = _detail_small_numeric_model_tokens(candidate_title)
        if not (
            requested_numbers
            and candidate_numbers
            and _detail_has_sku_evidence(
                record or {}, tokens=requested_numbers | candidate_numbers
            )
        ):
            return False
    if not requested_numbers or not candidate_numbers:
        return False
    if _detail_model_number_sets_compatible(requested_numbers, candidate_numbers):
        return False
    requested_words = _semantic_detail_identity_tokens(requested_title)
    candidate_words = _semantic_detail_identity_tokens(candidate_title)
    shared_words = requested_words & candidate_words
    required_shared_words = min(
        int(DETAIL_MODEL_CONFLICT_MIN_SHARED_WORDS),
        len(requested_words),
        len(candidate_words),
    )
    return required_shared_words > 0 and len(shared_words) >= required_shared_words


def _detail_model_number_sets_compatible(
    requested_numbers: set[str],
    candidate_numbers: set[str],
) -> bool:
    for requested in requested_numbers:
        for candidate in candidate_numbers:
            if requested == candidate:
                return True
            shorter, longer = sorted((requested, candidate), key=len)
            if (
                len(shorter) >= 5
                and len(longer) - len(shorter) <= 2
                and longer.startswith(shorter)
                and any(char.isalpha() for char in shorter)
            ):
                return True
    return False


def _detail_model_number_tokens(value: object) -> set[str]:
    tokens: set[str] = set()
    text = clean_text(value)
    for pattern in tuple(DETAIL_MODEL_NUMBER_TOKEN_PATTERNS or ()):
        if not str(pattern).strip():
            continue
        for match in re.findall(str(pattern), text):
            raw_token = match[0] if isinstance(match, tuple) else match
            normalized = _normalized_model_token(raw_token)
            if normalized:
                tokens.add(normalized)
    return tokens


def _detail_small_numeric_model_tokens(value: object) -> set[str]:
    pattern = str(DETAIL_MODEL_SMALL_NUMERIC_TOKEN_PATTERN or "").strip()
    if not pattern:
        return set()
    return {
        token.lstrip("0") or "0"
        for token in re.findall(pattern, clean_text(value))
    }


def _detail_has_sku_evidence(
    record: dict[str, object],
    *,
    tokens: set[str],
) -> bool:
    if not tokens:
        return False
    for field_name in ("sku", "product_id", "variant_id", "part_number", "barcode"):
        normalized = _normalized_model_token(record.get(field_name))
        if normalized and any(token in normalized for token in tokens):
            return True
    return False


def _record_has_strong_requested_identity_code(
    record: dict[str, object],
    *,
    requested_codes: set[str],
) -> bool:
    if not requested_codes:
        return False
    for field_name in ("product_id", "variant_id", "part_number", "barcode"):
        normalized = _normalized_detail_identity_code(record.get(field_name))
        if normalized and detail_identity_codes_match(requested_codes, {normalized}):
            return True
    return False


def _normalized_model_token(value: object) -> str:
    normalized = _MIXED_NON_ALNUM_RE.sub("", str(value or "")).lower()
    if not normalized:
        return ""
    if normalized.isdigit():
        return normalized.lstrip("0") or "0"
    return normalized


def _detail_slug_title_fallback_from_url(identity_url: str) -> str | None:
    generic_terminal_tokens = set(DETAIL_GENERIC_TERMINAL_TOKENS)
    path_segments = _detail_url_path_segments(identity_url)
    for index in range(len(path_segments) - 1, -1, -1):
        if _detail_segment_is_shop_merchant_namespace(path_segments, index):
            continue
        segment = path_segments[index]
        terminal = _HTML_SUFFIX_RE.sub("", segment)
        if not terminal:
            continue
        title = clean_text(_SLUG_SEPARATOR_RE.sub(" ", terminal))
        semantic_tokens = _semantic_detail_identity_tokens(title)
        if _detail_title_fallback_looks_like_code(terminal) and (
            len(semantic_tokens) < int(DETAIL_TITLE_FALLBACK_MIN_SEMANTIC_TOKENS)
        ):
            continue
        terminal_tokens = _path_segment_tokens(terminal)
        if terminal_tokens and terminal_tokens <= generic_terminal_tokens:
            continue
        if len(semantic_tokens) >= int(DETAIL_TITLE_FALLBACK_MIN_SEMANTIC_TOKENS):
            return title
    return None


def _detail_title_fallback_looks_like_code(value: object) -> bool:
    terminal = str(value or "").strip()
    if not terminal:
        return False
    if _MIXED_NON_ALNUM_RE.search(terminal):
        return False
    text = clean_text(value)
    if not text:
        return False
    compact = _MIXED_NON_ALNUM_RE.sub("", text)
    pattern = str(DETAIL_TITLE_FALLBACK_CODE_PATTERN or "").strip()
    return bool(
        compact and re.search(r"\d", compact) and re.fullmatch(pattern, compact)
    )


detail_title_fallback_looks_like_code = _detail_title_fallback_looks_like_code


def _detail_url_matches_requested_identity(
    candidate_url: str,
    *,
    requested_page_url: str,
) -> bool:
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    candidate_codes = _detail_identity_codes_from_url(candidate_url)
    requested_query_codes = _detail_query_identity_codes_from_url(requested_page_url)
    candidate_query_codes = _detail_query_identity_codes_from_url(candidate_url)
    if requested_query_codes:
        if detail_identity_codes_match(requested_query_codes, candidate_query_codes):
            return True
        if candidate_query_codes:
            return False
    if detail_identity_codes_match(requested_codes, candidate_codes):
        return True
    requested_title = _detail_title_from_url(requested_page_url)
    requested_tokens = _detail_identity_tokens(requested_title)
    if not requested_tokens:
        return False
    candidate_title = _detail_title_from_url(candidate_url) or candidate_url
    candidate_tokens = _detail_identity_tokens(candidate_title)
    if not candidate_tokens:
        return False
    overlap = requested_tokens & candidate_tokens
    if len(requested_tokens) == 1:
        return bool(overlap)
    return len(overlap) >= min(2, len(requested_tokens))


def _detail_identity_tokens(value: object) -> set[str]:
    cleaned = clean_text(value).lower()
    return {
        token
        for token in _LOWER_NON_ALNUM_RE.split(cleaned)
        if len(token) >= 3 and token not in DETAIL_IDENTITY_STOPWORDS
    }


def _semantic_detail_identity_tokens(value: object) -> set[str]:
    return {
        token
        for token in _detail_identity_tokens(value)
        if re.search(r"[a-z]", token) and not re.search(r"\d", token)
    }


def _detail_identity_codes_from_url(url: object) -> set[str]:
    text = text_or_none(url)
    if not text:
        return set()
    parsed = urlparse(text)
    codes: set[str] = set()
    for segment in _detail_url_path_segments(text):
        terminal = _HTML_SUFFIX_RE.sub("", segment)
        code_like_terminal = _detail_segment_code(terminal)
        if code_like_terminal:
            codes.add(code_like_terminal)
        for match in re.findall(
            rf"[A-Za-z0-9]{{{DETAIL_IDENTITY_CODE_MIN_LENGTH},}}", terminal
        ):
            normalized = _normalized_detail_identity_code(match)
            if normalized:
                codes.add(normalized)
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        match = re.match(
            r"dwvar_([A-Za-z0-9][A-Za-z0-9_-]{6,}[A-Za-z0-9])_",
            str(key or ""),
            flags=re.I,
        )
        if match is None:
            continue
        normalized = _detail_segment_code(match.group(1))
        if normalized:
            codes.add(normalized)
    codes.update(_detail_query_identity_codes_from_url(text))
    return codes


def _detail_query_identity_codes_from_url(url: object) -> set[str]:
    text = text_or_none(url)
    if not text:
        return set()
    parsed = urlparse(text)
    codes: set[str] = set()
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        normalized_key = str(key or "").strip().lower()
        if not normalized_key:
            continue
        if normalized_key in _DETAIL_IDENTITY_QUERY_KEYS or any(
            normalized_key.startswith(prefix)
            for prefix in _DETAIL_IDENTITY_QUERY_PREFIXES
        ):
            normalized_value = _detail_segment_code(value)
            if normalized_value:
                codes.add(normalized_value)
    return codes


def _detail_identity_codes_from_record_fields(record: dict[str, object]) -> set[str]:
    codes: set[str] = set()
    for field_name in ("sku", "product_id", "variant_id", "part_number"):
        normalized = _normalized_detail_identity_code(record.get(field_name))
        if normalized:
            codes.add(normalized)
    return codes


def _detail_segment_looks_like_identity_code(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if re.fullmatch(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+){0,2}", text) is None:
        return False
    return _normalized_detail_identity_code(text) is not None


def _detail_segment_code(value: object) -> str | None:
    text = str(value or "").strip()
    if not _detail_segment_looks_like_identity_code(text):
        return None
    return _normalized_detail_identity_code(text)


def _normalized_detail_identity_code(value: object) -> str | None:
    text = _MIXED_NON_ALNUM_RE.sub("", str(value or "")).upper()
    if len(text) < DETAIL_IDENTITY_CODE_MIN_LENGTH:
        return None
    if not re.search(r"\d", text):
        return None
    return text


def detail_identity_codes_match(
    expected_codes: set[str],
    candidate_codes: set[str],
) -> bool:
    if not expected_codes or not candidate_codes:
        return False
    return not expected_codes.isdisjoint(candidate_codes)


def _detail_redirect_identity_is_mismatched(
    record: dict[str, object],
    *,
    page_url: str,
    requested_page_url: str | None,
) -> bool:
    requested = text_or_none(requested_page_url) or text_or_none(page_url)
    current = text_or_none(page_url)
    if not requested:
        return False
    if not _detail_url_looks_like_product(requested):
        return False

    if current and requested == current:
        candidate_url = text_or_none(record.get("url"))
        if (
            candidate_url
            and candidate_url != requested
            and same_site(requested, candidate_url)
            and not _detail_url_matches_requested_identity(
                candidate_url,
                requested_page_url=requested,
            )
        ):
            return True
        requested_title = _detail_requested_identity_text(requested)
        requested_tokens = _detail_identity_tokens(requested_title)
        candidate_title = record.get("title")
        candidate_tokens = _detail_identity_tokens(record.get("title"))
        requested_codes = _detail_identity_codes_from_url(requested)
        record_field_codes = _detail_identity_codes_from_record_fields(record)
        has_matching_record_identity_code = detail_identity_codes_match(
            requested_codes,
            record_field_codes,
        )
        has_matching_strong_identity_code = _record_has_strong_requested_identity_code(
            record,
            requested_codes=requested_codes,
        )
        requested_small_numbers = _detail_small_numeric_model_tokens(requested_title)
        candidate_small_numbers = _detail_small_numeric_model_tokens(candidate_title)
        has_matching_small_model_number = bool(
            requested_small_numbers & candidate_small_numbers
        )
        record_matches_requested_identity = _record_matches_requested_detail_identity(
            record,
            requested_page_url=requested,
        )
        if _detail_model_numbers_conflict(
            requested_title,
            candidate_title,
            record=record,
        ) and not (
            has_matching_small_model_number
            or (has_matching_record_identity_code and has_matching_strong_identity_code)
        ):
            return True
        has_strong_same_url_product_evidence = any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in (
                "sku",
                "product_id",
                "part_number",
                "barcode",
                "description",
                "brand",
                "product_details",
                "variants",
            )
        )
        if not has_strong_same_url_product_evidence:
            availability = text_or_none(record.get("availability"))
            has_strong_same_url_product_evidence = bool(
                availability and availability != AVAILABILITY_UNKNOWN
            )
        has_same_url_mismatch_evidence = (
            any(
                record.get(field_name) not in (None, "", [], {})
                for field_name in (
                    "price",
                    "original_price",
                    "currency",
                    "image_url",
                )
            )
            or len(candidate_tokens) >= 4
        )
        if (
            not has_strong_same_url_product_evidence
            and has_same_url_mismatch_evidence
            and len(requested_tokens) >= 2
            and len(candidate_tokens) >= 2
            and len(requested_tokens & candidate_tokens) < min(2, len(requested_tokens))
            and not record_matches_requested_identity
        ):
            return True
        return False

    requested_codes = _detail_identity_codes_from_url(requested)
    record_field_codes = _detail_identity_codes_from_record_fields(record)
    if (
        requested_codes
        and record_field_codes
        and not detail_identity_codes_match(
            requested_codes,
            record_field_codes,
        )
    ):
        candidate_url = text_or_none(record.get("url")) or current
        if not (
            candidate_url
            and _detail_url_matches_requested_identity(
                candidate_url,
                requested_page_url=requested,
            )
            and _record_matches_requested_detail_identity(
                record,
                requested_page_url=requested,
            )
        ):
            return True
    candidate_url = text_or_none(record.get("url")) or current
    if (
        candidate_url
        and candidate_url != requested
        and same_site(requested, candidate_url)
    ):
        if not _detail_url_matches_requested_identity(
            candidate_url,
            requested_page_url=requested,
        ):
            return True
        if not _record_matches_requested_detail_identity(
            record,
            requested_page_url=requested,
        ):
            return True

    if not current:
        return False
    if not same_site(requested, current):
        return False
    if not _detail_url_is_utility(current):
        return False
    return not _record_matches_requested_detail_identity(
        record,
        requested_page_url=requested,
    )


(
    detail_identity_codes_from_record_fields,
    detail_identity_codes_from_url,
    detail_query_identity_codes_from_url,
    detail_identity_tokens,
    detail_redirect_identity_is_mismatched,
    detail_slug_title_fallback_from_url,
    detail_title_from_url,
    detail_url_candidate_is_low_signal,
    detail_url_is_collection_like,
    detail_url_is_utility,
    detail_url_looks_like_product,
    detail_url_matches_requested_identity,
    preferred_detail_identity_url,
    record_matches_requested_detail_identity,
    semantic_detail_identity_tokens,
) = (
    _detail_identity_codes_from_record_fields,
    _detail_identity_codes_from_url,
    _detail_query_identity_codes_from_url,
    _detail_identity_tokens,
    _detail_redirect_identity_is_mismatched,
    _detail_slug_title_fallback_from_url,
    _detail_title_from_url,
    _detail_url_candidate_is_low_signal,
    _detail_url_is_collection_like,
    _detail_url_is_utility,
    _detail_url_looks_like_product,
    _detail_url_matches_requested_identity,
    _preferred_detail_identity_url,
    _record_matches_requested_detail_identity,
    _semantic_detail_identity_tokens,
)
