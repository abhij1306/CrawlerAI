"""DOM image URL scoring, dedupe, and page image extraction."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse, unquote

import regex as regex_lib
from bs4 import BeautifulSoup, Tag

from app.services.config.extraction_rules import (
    AMAZON_IMAGE_CDN_HOSTS,
    AMAZON_IMAGE_LOW_RES_MAX_DIMENSION,
    AMAZON_IMAGE_LOW_RES_SUFFIX_PATTERN,
    CDN_IMAGE_PATH_SUFFIX_PATTERN,
    CDN_IMAGE_QUERY_KEY_PATTERNS,
    CDN_IMAGE_QUERY_PARAMS,
    DETAIL_IMAGE_URL_ATTRS,
    DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS,
    MAX_SELECTOR_MATCHES,
    NON_PRODUCT_IMAGE_HINTS,
    NON_PRODUCT_PROVIDER_HINTS,
    PRODUCT_GALLERY_CONTEXT_HINTS,
    SEMANTIC_SECTION_NOISE,
    UNRESOLVED_TEMPLATE_URL_TOKENS,
)
from app.services.config.surface_hints import detail_path_hints
from app.services.shared.coerce_primitives import safe_int as _safe_int
from app.services.shared.field_coerce import absolute_url, clean_text, extract_urls

_candidate_cleanup_raw: dict[str, object] = {}
_IMAGE_FILE_EXTENSIONS = (".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp")
_PAGE_FILE_EXTENSIONS = (".asp", ".aspx", ".htm", ".html", ".jsp", ".php")
_IMAGE_URL_HINTS = (
    "/cdn/",
    "/image/",
    "/images/",
    "/img/",
    "/media/",
    "cloudinary",
    "scene7",
)
_NON_PRIMARY_IMAGE_SECTION_HINTS = tuple(
    str(token).lower()
    for token in (SEMANTIC_SECTION_NOISE.get("label_skip_tokens") or ())
)
_detail_text_scope_exclude_tokens = tuple(
    str(token).lower()
    for token in tuple(DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS or ())
    if str(token).strip()
)
_CDN_IMAGE_QUERY_PARAMS = frozenset(CDN_IMAGE_QUERY_PARAMS or ())
_CDN_IMAGE_QUERY_KEY_REGEXES = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(CDN_IMAGE_QUERY_KEY_PATTERNS or ())
    if str(pattern).strip()
)
_CDN_IMAGE_PATH_SUFFIX_RE = regex_lib.compile(
    str(CDN_IMAGE_PATH_SUFFIX_PATTERN),
    regex_lib.I,
)
_AMAZON_IMAGE_CDN_HOSTS = frozenset(
    str(host).lower() for host in AMAZON_IMAGE_CDN_HOSTS
)
_AMAZON_IMAGE_LOW_RES_SUFFIX_RE = re.compile(
    str(AMAZON_IMAGE_LOW_RES_SUFFIX_PATTERN),
    re.I,
)
_AMAZON_IMAGE_TRANSFORM_DIMENSION_RE = re.compile(
    r"\._[A-Z]+_[A-Z]{1,2}(\d{2,4})_",
    re.I,
)
_IMAGE_PATH_DIMENSION_RE = re.compile(
    r"(?:[/?_=-])(?:w|wid|width|h|hei|height|sl|sx|sy|us)?[_=-]?(\d{2,4})(?:x(\d{2,4}))?",
    re.I,
)
_DEMANDWARE_IMAGE_PATH_RE = re.compile(
    r"^/dw/image/v2/[^/]+/(on/demandware\.static/.+)$",
    re.I,
)
_CANONICAL_IMAGE_EXTENSION_RE = re.compile(
    r"\.(?:avif|gif|jpe?g|png|webp)$",
    re.I,
)
_UNRESOLVED_TEMPLATE_URL_RE = re.compile(
    "|".join(
        re.escape(str(token))
        for token in tuple(UNRESOLVED_TEMPLATE_URL_TOKENS or ())
        if str(token).strip()
    )
    or r"(?!)",
    re.IGNORECASE,
)
_max_selector_matches = _safe_int(MAX_SELECTOR_MATCHES, default=12) or 12


def srcset_urls(value: object) -> list[str]:
    urls: list[str] = []
    for part in str(value or "").split(","):
        token = " ".join(str(part or "").split()).strip()
        if not token:
            continue
        urls.append(token.split(" ", 1)[0].strip())
    return [url for url in urls if url]


def node_attr_text(node: Tag, *, max_depth: int = 6) -> str:
    values: list[str] = []
    current: Tag | None = node
    depth = 0
    while isinstance(current, Tag) and depth < max_depth:
        values.extend(
            str(value)
            for key, value in (getattr(current, "attrs", {}) or {}).items()
            if key in {"class", "id", "aria-label", "data-testid", "role"}
            and value not in (None, "", [], {})
        )
        current = current.parent
        depth += 1
    return clean_text(" ".join(values)).lower()


def looks_like_image_asset_url(url: str) -> bool:
    lowered = clean_text(url).lower()
    if not lowered or lowered.startswith(("data:", "javascript:", "mailto:")):
        return False
    parsed = urlparse(lowered)
    path = parsed.path or ""
    host_and_path = f"{parsed.netloc}{path}"
    if any(path.endswith(ext) for ext in _IMAGE_FILE_EXTENSIONS):
        return True
    if any(path.endswith(ext) for ext in _PAGE_FILE_EXTENSIONS):
        return False
    if any(marker in path for marker in detail_path_hints()):
        return False
    if any(hint in host_and_path for hint in _IMAGE_URL_HINTS):
        return True
    query = parsed.query
    return "format=" in query or "fm=" in query


def canonical_image_url(url: str) -> str:
    effective_url = _effective_image_url(url)
    parsed = urlparse(_normalize_image_url_text(effective_url))
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_cdn_image_query_key(str(key or "").strip())
    ]
    normalized_path = _canonical_image_path(parsed.path or "")
    return urlunparse(
        parsed._replace(
            path=normalized_path,
            params="",
            query=urlencode(filtered_query, doseq=True),
            fragment="",
        )
    ).lower()


def image_candidate_score(url: str) -> tuple[int, int, int, int]:
    normalized_url = _normalize_image_url_text(url)
    parsed = urlparse(normalized_url)
    numeric_params = {
        str(key or "").strip().lower(): str(value or "").strip()
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    }
    numeric_params.update(
        {
            str(key or "").strip().lower(): str(value or "").strip()
            for key, value in parse_qsl(
                str(parsed.params or "").replace(";", "&"),
                keep_blank_values=True,
            )
        }
    )

    def _int_param(*names: str) -> int:
        for name in names:
            raw_value = numeric_params.get(name)
            if not raw_value:
                continue
            try:
                return int(raw_value)
            except ValueError:
                continue
        return 0

    width = _int_param(
        *(
            p
            for p in ("width", "w", "wid", "sw", "imwidth", "odnwidth", "maxwidth")
            if p in _CDN_IMAGE_QUERY_PARAMS
        )
    )
    height = _int_param(
        *(
            p
            for p in ("height", "h", "hei", "sh", "odnheight", "maxheight")
            if p in _CDN_IMAGE_QUERY_PARAMS
        )
    )
    if not width or not height:
        for match in _IMAGE_PATH_DIMENSION_RE.finditer(normalized_url):
            first = int(match.group(1) or 0)
            second = int(match.group(2) or 0)
            if not width:
                width = max(width, first)
            if not height:
                height = max(height, second or first)
    area = width * height if width and height else max(width, height)
    return (0 if _is_proxy_image_url(url) else 1, area, width, height)


def dedupe_image_urls(urls: list[str]) -> list[str]:
    best_by_key: dict[str, tuple[tuple[int, int, int, int], int, str]] = {}
    order: list[str] = []
    for index, url in enumerate(urls):
        normalized_url = _normalize_image_url_text(url)
        lowered = normalized_url.lower()
        if (
            not lowered
            or lowered.endswith(".mp4")
            or any(token in lowered for token in NON_PRODUCT_IMAGE_HINTS)
            or any(token in lowered for token in NON_PRODUCT_PROVIDER_HINTS)
        ):
            continue
        canonical = canonical_image_url(url)
        if not canonical:
            continue
        score = image_candidate_score(url)
        current = best_by_key.get(canonical)
        if current is None:
            best_by_key[canonical] = (score, index, normalized_url)
            order.append(canonical)
            continue
        current_score, current_index, current_url = current
        if score > current_score or (score == current_score and index < current_index):
            best_by_key[canonical] = (
                score,
                current_index,
                normalized_url if score > current_score else current_url,
            )
    return [best_by_key[key][2] for key in order]


def _canonical_image_path(path: str) -> str:
    normalized_path = _CDN_IMAGE_PATH_SUFFIX_RE.sub("", path or "")
    demandware_match = _DEMANDWARE_IMAGE_PATH_RE.match(normalized_path)
    if demandware_match is not None:
        normalized_path = f"/{demandware_match.group(1)}"
    return _CANONICAL_IMAGE_EXTENSION_RE.sub("", normalized_path)


def upgrade_low_resolution_image_url(url: str) -> str:
    normalized_url = _normalize_image_url_text(url)
    parsed = urlparse(normalized_url)
    host = str(parsed.netloc or "").lower()
    if host not in _AMAZON_IMAGE_CDN_HOSTS:
        return normalized_url
    transform_dimension_match = _AMAZON_IMAGE_TRANSFORM_DIMENSION_RE.search(
        parsed.path or ""
    )
    if (
        transform_dimension_match is not None
        and int(transform_dimension_match.group(1))
        > int(AMAZON_IMAGE_LOW_RES_MAX_DIMENSION)
    ):
        return normalized_url
    path = _AMAZON_IMAGE_LOW_RES_SUFFIX_RE.sub("", parsed.path or "")
    return urlunparse(parsed._replace(path=path))


def candidate_image_urls_from_node(node: Tag, page_url: str) -> list[str]:
    candidates: list[str] = []
    for raw_value in (
        node.get("srcset"),
        node.get("data-srcset"),
    ):
        if raw_value not in (None, "", [], {}):
            candidates.extend(extract_urls(srcset_urls(raw_value), page_url))
    for attr_name in tuple(DETAIL_IMAGE_URL_ATTRS or ()):
        raw_value = node.get(str(attr_name))
        if raw_value not in (None, "", [], {}):
            candidates.extend(extract_urls(raw_value, page_url))
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def extract_page_images(
    root: BeautifulSoup | Tag,
    page_url: str,
    *,
    exclude_linked_detail_images: bool = False,
    surface: str | None = None,
    other_detail_link_checker=None,
) -> list[str]:
    scored_values: list[tuple[int, int, str]] = []
    for index, node in enumerate(root.find_all(["img", "source"])):
        if is_non_primary_image_context(node):
            continue
        if exclude_linked_detail_images:
            link = node.find_parent("a", href=True)
            if link is not None and (
                not callable(other_detail_link_checker)
                or other_detail_link_checker(
                    absolute_url(page_url, link.get("href")),
                    page_url,
                    surface=surface,
                    link_node=link,
                )
            ):
                continue
        for candidate in candidate_image_urls_from_node(node, page_url):
            lowered = candidate.lower()
            if lowered.startswith("data:"):
                continue
            if any(
                token in lowered
                for token in (
                    "analytics",
                    "tracking",
                    "pixel",
                    "spacer",
                    "blank.gif",
                    "doubleclick",
                    "google-analytics",
                    "googletagmanager",
                )
            ):
                continue
            if is_garbage_image_candidate(node, candidate):
                continue
            scored_values.append((gallery_image_score(node, candidate), index, candidate))
    ordered = [
        candidate
        for _score, _index, candidate in sorted(
            scored_values,
            key=lambda row: (-int(row[0]), int(row[1]), str(row[2])),
        )
    ]
    return dedupe_image_urls(ordered)[:_max_selector_matches]


def is_non_primary_image_context(node: Tag) -> bool:
    context = node_attr_text(node)
    return any(hint in context for hint in _NON_PRIMARY_IMAGE_SECTION_HINTS) or any(
        token in context for token in _detail_text_scope_exclude_tokens
    )


def is_garbage_image_candidate(node: Tag, candidate_url: str) -> bool:
    lowered = str(candidate_url or "").lower()
    context = image_node_context(node)
    if lowered.endswith(".svg") and not is_in_product_gallery_context(node):
        return True
    if _UNRESOLVED_TEMPLATE_URL_RE.search(candidate_url or ""):
        return True
    if any(token in lowered for token in NON_PRODUCT_IMAGE_HINTS):
        return True
    if any(token in lowered for token in NON_PRODUCT_PROVIDER_HINTS):
        return True
    return any(
        token in context
        for token in (*NON_PRODUCT_IMAGE_HINTS, *NON_PRODUCT_PROVIDER_HINTS)
    )


def gallery_image_score(node: Tag, candidate_url: str) -> int:
    context = image_node_context(node)
    score = 0
    if any(hint in context for hint in PRODUCT_GALLERY_CONTEXT_HINTS):
        score += 4
    elif node.find_parent(["main"]) is not None and looks_like_image_asset_url(
        candidate_url
    ):
        score += 2
    width = str(node.get("width") or "").strip()
    height = str(node.get("height") or "").strip()
    try:
        if int(width or "0") >= 120 or int(height or "0") >= 120:
            score += 1
    except ValueError:
        # Non-numeric width/height attributes contribute no size bonus.
        pass
    if "srcset" in node.attrs or "data-srcset" in node.attrs:
        score += 1
    if looks_like_image_asset_url(candidate_url):
        score += 1
    if node.find_parent("picture") is not None:
        score += 1
    return score


def image_node_context(node: Tag) -> str:
    parts = [node_attr_text(node)]
    alt = node.get("alt")
    if alt not in (None, "", [], {}):
        parts.append(str(alt))
    return " ".join(parts).lower()


def is_in_product_gallery_context(node: Tag, *, max_depth: int = 6) -> bool:
    current: Tag | None = node
    depth = 0
    in_main = False
    while isinstance(current, Tag) and depth < max_depth:
        if (
            current.name == "main"
            or str(current.get("role") or "").strip().lower() == "main"
        ):
            in_main = True
        context = node_attr_text(current)
        if any(hint in context for hint in PRODUCT_GALLERY_CONTEXT_HINTS):
            if in_main or any(
                token in context for token in ("gallery", "media", "pdp", "product")
            ):
                return True
        current = current.parent
        depth += 1
    return False


def _is_cdn_image_query_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return False
    if normalized == "v":
        return False
    return normalized in _CDN_IMAGE_QUERY_PARAMS or any(
        pattern.fullmatch(normalized) for pattern in _CDN_IMAGE_QUERY_KEY_REGEXES
    )


def _effective_image_url(url: str) -> str:
    text = _normalize_image_url_text(url)
    if not text:
        return ""
    parsed = urlparse(text)
    path = str(parsed.path or "").lower()
    if "/_next/image" not in path:
        return text
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    wrapped = str(query.get("url") or "").strip()
    if not wrapped:
        return text
    return unquote(wrapped) or text


def _normalize_image_url_text(url: object) -> str:
    text = str(url or "").strip()
    for scheme in ("https", "http"):
        prefix = f"{scheme}:"
        if text.lower().startswith(prefix):
            remainder = text[len(prefix) :]
            if remainder.startswith("/"):
                return f"{scheme}://{remainder.lstrip('/')}"
    return text


def _is_proxy_image_url(url: str) -> bool:
    path = str(urlparse(str(url or "").strip()).path or "").lower()
    return "/_next/image" in path
