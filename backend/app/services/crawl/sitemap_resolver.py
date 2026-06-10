from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from defusedxml import ElementTree
import httpx
from bs4 import BeautifulSoup, Tag

from app.services.config.sitemap import (
    SITEMAP_CATEGORY_ANCHOR_TEXT_EXCLUDED_TOKENS,
    SITEMAP_CATEGORY_ANCHOR_TEXT_TOKENS,
    SITEMAP_CATEGORY_EXCLUDED_PATH_TOKENS,
    SITEMAP_CATEGORY_PATH_TOKENS,
    SITEMAP_DEFAULT_FILTER_KEYWORD,
    SITEMAP_DEFAULT_MAX_URLS,
    SITE_LINK_DISCOVERY_MAX_DEPTH,
    SITE_LINK_DISCOVERY_MAX_PAGES,
    SITEMAP_FETCH_MAX_REDIRECTS,
    SITEMAP_FETCH_RETRY_ATTEMPTS,
    SITEMAP_FETCH_RETRY_DELAY_SECONDS,
    SITEMAP_FETCH_RETRY_STATUS_CODES,
    SITEMAP_FETCH_TIMEOUT_SECONDS,
    SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_EXTENSIONS,
    SITEMAP_HOMEPAGE_FALLBACK_MAX_ANCHORS,
    SITEMAP_HOMEPAGE_CATEGORY_PATH_SCORE_BOOST,
    SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_PATH_TOKENS,
    SITEMAP_HOMEPAGE_FALLBACK_MAX_LINK_TEXT_WORDS,
    SITEMAP_HOMEPAGE_FALLBACK_MAX_VALIDATIONS,
    SITEMAP_THIN_RESULT_THRESHOLD,
    SITEMAP_USER_AGENT,
)
from app.services.crawl.utils import normalize_target_url, text_has_token
from app.services.shared.url_utils import absolute_url
from app.services.surface_resolver import resolve_auto_surface
from app.services.url_safety import validate_public_target

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SitemapResolutionResult:
    urls: list[str]
    source: str
    nav_tree: list[dict[str, object]] | None = None
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HomepageCandidate:
    url: str
    label: str | None = None


def _normalize_sitemap_url(domain: str) -> str:
    candidate = str(domain or "").strip().rstrip("/")
    if not candidate:
        raise ValueError("empty domain")
    if candidate.startswith(("http://", "https://")):
        if candidate.endswith(".xml"):
            return candidate
        return f"{candidate}/sitemap.xml"
    return f"https://{candidate}/sitemap.xml"


def _normalize_homepage_url(domain: str) -> str:
    candidate = str(domain or "").strip()
    if not candidate:
        raise ValueError("empty domain")
    if candidate.startswith(("http://", "https://")):
        return candidate
    return f"https://{candidate}"


def _candidate_sitemap_urls(domain: str) -> list[str]:
    homepage_url = _normalize_homepage_url(domain)
    parsed = urlsplit(homepage_url)
    origin_url = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    candidates = [_normalize_sitemap_url(origin_url)]
    if parsed.path.strip("/"):
        candidates.append(_normalize_sitemap_url(homepage_url))
    return list(dict.fromkeys(candidates))


async def resolve_category_urls_from_sitemap(
    domain: str,
    filter_keyword: str = SITEMAP_DEFAULT_FILTER_KEYWORD,
    max_urls: int = SITEMAP_DEFAULT_MAX_URLS,
    allow_homepage_fallback: bool = False,
    category_only: bool = False,
) -> list[str]:
    result = await resolve_category_urls_from_sitemap_result(
        domain=domain,
        filter_keyword=filter_keyword,
        max_urls=max_urls,
        allow_homepage_fallback=allow_homepage_fallback,
        category_only=category_only,
    )
    return result.urls


# skipcq: PY-R1000
async def resolve_category_urls_with_site_links(
    domain: str,
    filter_keyword: str = SITEMAP_DEFAULT_FILTER_KEYWORD,
    max_urls: int = SITEMAP_DEFAULT_MAX_URLS,
    allow_homepage_fallback: bool = False,
    category_only: bool = False,
    *,
    strategy: str = "static_then_rendered",
    max_depth: int = SITE_LINK_DISCOVERY_MAX_DEPTH,
    max_pages: int = SITE_LINK_DISCOVERY_MAX_PAGES,
    validate_candidates: bool = False,
) -> SitemapResolutionResult:
    """Resolve category URLs through static discovery plus rendered site links."""

    normalized_strategy = str(strategy or "static_then_rendered").strip().lower()
    allowed = {"static_then_rendered", "static_only", "rendered_only"}
    if normalized_strategy not in allowed:
        raise ValueError("Unsupported category discovery strategy")
    limit = max(1, int(max_urls or SITEMAP_DEFAULT_MAX_URLS))
    static_result: SitemapResolutionResult | None = None
    static_error: Exception | None = None
    if normalized_strategy != "rendered_only":
        try:
            static_result = await resolve_category_urls_from_sitemap_result(
                domain=domain,
                filter_keyword=filter_keyword,
                max_urls=limit,
                allow_homepage_fallback=allow_homepage_fallback,
                category_only=category_only,
            )
        except Exception as exc:
            static_error = exc
        else:
            if (
                normalized_strategy == "static_only"
                or len(static_result.urls) >= SITEMAP_THIN_RESULT_THRESHOLD
            ):
                return static_result
    if normalized_strategy == "static_only":
        if static_result is not None:
            return static_result
        if static_error is not None:
            raise static_error
        raise ValueError(f"Unable to resolve sitemap for {_normalize_homepage_url(domain)}")

    try:
        discover_rendered_category_links = importlib.import_module(
            "app.services.crawl.site_link_discovery"
        ).discover_rendered_category_links
        rendered_result = await discover_rendered_category_links(
            _normalize_homepage_url(domain),
            limit=limit,
            max_depth=max_depth,
            max_pages=max_pages,
            validate_candidates=validate_candidates,
        )
    except Exception as exc:
        if static_result is not None:
            static_result.diagnostics["rendered_fallback_error"] = {
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            return static_result
        raise exc

    if static_result is None or not static_result.urls:
        if static_error is not None:
            rendered_result.diagnostics["static_error"] = {
                "error_type": type(static_error).__name__,
                "message": str(static_error),
            }
        return rendered_result

    merged = _merge_dedupe_urls(static_result.urls, rendered_result.urls, limit=limit)
    labels = {
        **_labels_by_url_from_tree(static_result.nav_tree or []),
        **_labels_by_url_from_tree(rendered_result.nav_tree or []),
    }
    return SitemapResolutionResult(
        urls=merged,
        source=f"{static_result.source}+{rendered_result.source}",
        nav_tree=_build_nav_tree(merged, labels_by_url=labels),
        diagnostics={
            "static": static_result.diagnostics,
            "rendered": rendered_result.diagnostics,
            "static_url_count": len(static_result.urls),
            "rendered_url_count": len(rendered_result.urls),
        },
    )


async def resolve_category_urls_from_sitemap_result(
    domain: str,
    filter_keyword: str = SITEMAP_DEFAULT_FILTER_KEYWORD,
    max_urls: int = SITEMAP_DEFAULT_MAX_URLS,
    allow_homepage_fallback: bool = False,
    category_only: bool = False,
) -> SitemapResolutionResult:
    keyword = str(
        filter_keyword
        if filter_keyword is not None
        else SITEMAP_DEFAULT_FILTER_KEYWORD
    ).strip().lower()
    limit = max(1, int(max_urls or SITEMAP_DEFAULT_MAX_URLS))
    homepage_url = _normalize_homepage_url(domain)
    last_sitemap_error: ValueError | None = None
    sitemap_attempts: list[dict[str, str]] = []

    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=SITEMAP_FETCH_MAX_REDIRECTS,
        timeout=SITEMAP_FETCH_TIMEOUT_SECONDS,
    ) as client:
        sitemap_result: SitemapResolutionResult | None = None
        for root_url in _candidate_sitemap_urls(domain):
            try:
                sitemap_result = await _resolve_sitemap_urls(
                    client,
                    root_url=root_url,
                    keyword=keyword,
                    limit=limit,
                    category_only=category_only,
                )
                sitemap_result.diagnostics.setdefault("sitemap_attempts", sitemap_attempts)
                sitemap_result.diagnostics.setdefault("static_status", "sitemap_success")
                break
            except ValueError as exc:
                last_sitemap_error = exc
                sitemap_attempts.append(
                    {
                        "url": root_url,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )

        # If we got a sitemap but it's thin (e.g. only policy pages), and
        # homepage fallback is allowed, also harvest the homepage and merge
        # the two ranked sets so coverage doesn't collapse on token sitemaps.
        if (
            sitemap_result is not None
            and allow_homepage_fallback
            and len(sitemap_result.urls) < SITEMAP_THIN_RESULT_THRESHOLD
        ):
            try:
                homepage_result = await _resolve_homepage_urls(
                    client,
                    homepage_url=homepage_url,
                    keyword=keyword,
                    limit=limit,
                    category_only=category_only,
                )
            except ValueError as exc:
                sitemap_result.diagnostics["homepage_fallback_error"] = {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
                return sitemap_result
            if not sitemap_result.urls:
                homepage_result.diagnostics.setdefault(
                    "sitemap_attempts", sitemap_attempts
                )
                homepage_result.diagnostics.setdefault(
                    "static_status", "homepage_fallback_success"
                )
                return homepage_result
            merged = _merge_dedupe_urls(
                sitemap_result.urls, homepage_result.urls, limit=limit
            )
            labels = _labels_by_url_from_tree(homepage_result.nav_tree or [])
            return SitemapResolutionResult(
                urls=merged,
                source="sitemap+homepage",
                nav_tree=_build_nav_tree(merged, labels_by_url=labels),
                diagnostics={
                    "sitemap_attempts": sitemap_attempts,
                    "static_status": "sitemap_plus_homepage_success",
                    "sitemap_url_count": len(sitemap_result.urls),
                    "homepage_url_count": len(homepage_result.urls),
                },
            )

        if sitemap_result is not None:
            return sitemap_result

        if allow_homepage_fallback:
            try:
                homepage_result = await _resolve_homepage_urls(
                    client,
                    homepage_url=homepage_url,
                    keyword=keyword,
                    limit=limit,
                    category_only=category_only,
                )
            except ValueError as exc:
                sitemap_attempts.append(
                    {
                        "url": homepage_url,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
            else:
                homepage_result.diagnostics.setdefault(
                    "sitemap_attempts", sitemap_attempts
                )
                homepage_result.diagnostics.setdefault(
                    "static_status", "homepage_fallback_success"
                )
                return homepage_result

    if last_sitemap_error is not None:
        raise last_sitemap_error
    raise ValueError(f"Unable to resolve sitemap for {homepage_url}")


async def _resolve_sitemap_urls(
    client: httpx.AsyncClient,
    *,
    root_url: str,
    keyword: str,
    limit: int,
    category_only: bool,
) -> SitemapResolutionResult:
    root_xml = await _fetch_xml(client, root_url)
    root_tag = _local_tag(root_xml.tag)
    if root_tag == "sitemapindex":
        child_urls = [
            loc.text.strip()
            for sitemap in root_xml.findall(f"{{{SITEMAP_NS}}}sitemap")
            if (loc := sitemap.find(f"{{{SITEMAP_NS}}}loc")) is not None
            and loc.text
        ]
        if not child_urls:
            raise ValueError(f"No child sitemaps found in {root_url}.")
        filtered = await _resolve_child_sitemap_urls(
            child_urls, keyword, limit, category_only=category_only
        )
        if not filtered:
            raise ValueError(f"No URLs matched filter '{keyword}' in {root_url}.")
        return SitemapResolutionResult(
            urls=filtered,
            source="sitemap",
            nav_tree=_build_nav_tree(filtered),
        )

    if root_tag == "urlset":
        urls = _filter_urls(
            await _safe_locs(root_xml), keyword, category_only=category_only
        )
        if not urls:
            if keyword:
                raise ValueError(f"No URLs matched filter '{keyword}' in {root_url}.")
            raise ValueError(f"No URLs found in sitemap {root_url}.")
        limited_urls = urls[:limit]
        return SitemapResolutionResult(
            urls=limited_urls,
            source="sitemap",
            nav_tree=_build_nav_tree(limited_urls),
        )

    raise ValueError(f"Unrecognised sitemap root tag: {root_tag}")


async def _resolve_child_sitemap_urls(
    child_urls: list[str], keyword: str, max_urls: int, *, category_only: bool
) -> list[str]:
    all_urls: list[str] = []
    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=SITEMAP_FETCH_MAX_REDIRECTS,
        timeout=SITEMAP_FETCH_TIMEOUT_SECONDS,
    ) as client:
        for child_url in child_urls:
            try:
                child_xml = await _fetch_xml(client, child_url)
            except ValueError as exc:
                logger.warning("Skipping failed child sitemap %s: %s", child_url, exc)
                continue
            all_urls.extend(
                _filter_urls(
                    await _safe_locs(child_xml),
                    keyword,
                    category_only=category_only,
                )
            )
    return all_urls[:max_urls]


def _filter_urls(
    urls: list[str],
    keyword: str,
    *,
    category_only: bool = False,
) -> list[str]:
    filtered = urls
    if keyword:
        filtered = [url for url in filtered if keyword in url.lower()]
    if category_only:
        filtered = [url for url in filtered if _looks_like_category_url(url)]
    return filtered


def _merge_dedupe_urls(
    primary: list[str], secondary: list[str], *, limit: int
) -> list[str]:
    """Merge two ranked URL lists preserving primary order, dropping dupes.

    Used when a thin sitemap is augmented with homepage-harvested links.
    Canonicalisation is intentionally minimal — we strip fragments and
    trailing slashes and rely on `normalize_target_url` having run upstream.
    """

    def _key(value: str) -> str:
        return _strip_fragment(value).rstrip("/").lower()

    seen: set[str] = set()
    merged: list[str] = []
    for url in (*primary, *secondary):
        key = _key(url)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(url)
        if len(merged) >= limit:
            break
    return merged


async def _resolve_homepage_urls(
    client: httpx.AsyncClient,
    *,
    homepage_url: str,
    keyword: str,
    limit: int,
    category_only: bool,
) -> SitemapResolutionResult:
    response = await _fetch_response(client, homepage_url)
    candidates = await _extract_homepage_candidate_entries(
        homepage_url=str(response.url),
        html=response.text,
        keyword=keyword,
        limit=limit,
        category_only=category_only,
    )
    if not candidates:
        raise ValueError(f"No candidate links found on homepage {homepage_url}.")
    urls = [candidate.url for candidate in candidates]
    labels = {
        candidate.url: candidate.label
        for candidate in candidates
        if candidate.label
    }
    return SitemapResolutionResult(
        urls=urls,
        source="homepage",
        nav_tree=_build_nav_tree(urls, labels_by_url=labels),
    )


async def _fetch_xml(client: httpx.AsyncClient, url: str) -> ElementTree.Element:
    response = await _fetch_response(client, url)
    try:
        return ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        raise ValueError(f"Invalid XML in sitemap: {url} - {exc}") from exc


async def _fetch_response(client: httpx.AsyncClient, url: str) -> httpx.Response:
    await validate_public_target(url)
    attempts = max(1, int(SITEMAP_FETCH_RETRY_ATTEMPTS) + 1)
    retry_status_codes = {int(code) for code in SITEMAP_FETCH_RETRY_STATUS_CODES}
    response: httpx.Response | None = None
    for attempt in range(attempts):
        response = await client.get(url, headers={"User-Agent": SITEMAP_USER_AGENT})
        await _validate_response_redirect_chain(response)
        if response.status_code == 200:
            break
        if response.status_code not in retry_status_codes or attempt >= attempts - 1:
            raise ValueError(
                f"Sitemap fetch failed: {url} returned HTTP {response.status_code}"
            )
        logger.warning(
            "Retrying sitemap fetch for %s after HTTP %s (%s/%s)",
            url,
            response.status_code,
            attempt + 1,
            attempts,
        )
        await asyncio.sleep(max(0.0, float(SITEMAP_FETCH_RETRY_DELAY_SECONDS)))
    if response is None:
        raise ValueError(f"Sitemap fetch failed: {url} returned no response")
    return response


async def _safe_locs(xml: ElementTree.Element) -> list[str]:
    urls = _extract_locs(xml)
    for url in urls:
        await validate_public_target(url)
    return urls


async def _validate_response_redirect_chain(response: httpx.Response) -> None:
    for redirect_response in response.history:
        await validate_public_target(str(redirect_response.url))
    await validate_public_target(str(response.url))


async def _extract_homepage_candidate_urls(
    *,
    homepage_url: str,
    html: str,
    keyword: str,
    limit: int,
    category_only: bool = False,
) -> list[str]:
    candidates = await _extract_homepage_candidate_entries(
        homepage_url=homepage_url,
        html=html,
        keyword=keyword,
        limit=limit,
        category_only=category_only,
    )
    return [candidate.url for candidate in candidates]


async def _extract_homepage_candidate_entries(
    *,
    homepage_url: str,
    html: str,
    keyword: str,
    limit: int,
    category_only: bool = False,
) -> list[HomepageCandidate]:
    homepage_origin = _origin_key(homepage_url)
    homepage_normalized = _strip_fragment(homepage_url).rstrip("/")
    soup = BeautifulSoup(html or "", "html.parser")
    scored_urls: dict[str, tuple[int, str, int, str | None]] = {}
    validations = 0
    for index, anchor in enumerate(
        soup.select("a[href]")[:SITEMAP_HOMEPAGE_FALLBACK_MAX_ANCHORS]
    ):
        candidate_url = normalize_target_url(
            _strip_fragment(absolute_url(homepage_url, anchor.get("href")))
        )
        if not candidate_url:
            continue
        if candidate_url.rstrip("/") == homepage_normalized:
            continue
        if _origin_key(candidate_url) != homepage_origin:
            continue
        if _reject_homepage_candidate(candidate_url):
            continue
        classification, score = _classify_homepage_candidate(
            candidate_url=candidate_url,
            keyword=keyword,
            anchor=anchor,
        )
        category_signal = (
            category_only and _has_category_homepage_signal(candidate_url, anchor)
        )
        if not classification and not category_signal:
            continue
        if category_only and (
            classification != "listing"
            and not category_signal
        ):
            continue
        if validations >= SITEMAP_HOMEPAGE_FALLBACK_MAX_VALIDATIONS:
            break
        await validate_public_target(candidate_url)
        validations += 1
        previous = scored_urls.get(candidate_url)
        next_value = (score, classification, index, _anchor_label(anchor))
        if previous is None or score > previous[0]:
            scored_urls[candidate_url] = next_value

    ranked = sorted(
        scored_urls.items(),
        key=lambda item: (
            0 if item[1][1] == "listing" else 1,
            -item[1][0],
            item[1][2],
        ),
    )
    return [
        HomepageCandidate(url=url, label=score_data[3])
        for url, score_data in ranked[:limit]
    ]


def _build_nav_tree(
    urls: list[str],
    *,
    labels_by_url: Mapping[str, str | None] | None = None,
) -> list[dict[str, object]]:
    labels = {
        _url_key(url): label
        for url, label in (labels_by_url or {}).items()
        if label
    }
    url_by_key = {_url_key(url): url for url in urls}
    roots: list[dict[str, object]] = []
    child_maps: dict[int, dict[str, dict[str, object]]] = {}

    def children_for(node: dict[str, object]) -> list[dict[str, object]]:
        children = node.setdefault("children", [])
        if not isinstance(children, list):
            children = []
            node["children"] = children
        return children

    for raw_url in urls:
        parsed = urlsplit(raw_url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if not segments:
            continue
        parent_children = roots
        current_path: list[str] = []
        for segment in segments:
            current_path.append(segment)
            prefix_url = urlunsplit(
                (parsed.scheme, parsed.netloc, "/" + "/".join(current_path), "", "")
            )
            prefix_key = _url_key(prefix_url)
            siblings_key = id(parent_children)
            siblings = child_maps.setdefault(siblings_key, {})
            node = siblings.get(segment.lower())
            if node is None:
                node = {
                    "label": labels.get(prefix_key) or _label_from_path_segment(segment),
                    "children": [],
                }
                siblings[segment.lower()] = node
                parent_children.append(node)
            if prefix_key in url_by_key:
                node["url"] = url_by_key[prefix_key]
                if prefix_key in labels:
                    node["label"] = labels[prefix_key]
            parent_children = children_for(node)

    return roots


def _labels_by_url_from_tree(tree: list[dict[str, object]]) -> dict[str, str]:
    labels: dict[str, str] = {}
    stack = list(tree)
    while stack:
        node = stack.pop()
        url = node.get("url")
        label = node.get("label")
        if isinstance(url, str) and isinstance(label, str):
            labels[_url_key(url)] = label
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(
                child for child in children if isinstance(child, dict)
            )
    return labels


def build_category_nav_tree(
    urls: list[str],
    *,
    labels_by_url: Mapping[str, str | None] | None = None,
) -> list[dict[str, object]]:
    return _build_nav_tree(urls, labels_by_url=labels_by_url)


def category_labels_by_url_from_tree(tree: list[dict[str, object]]) -> dict[str, str]:
    return _labels_by_url_from_tree(tree)


def category_url_key(url: str) -> str:
    return _url_key(url)


def category_origin_key(value: str) -> tuple[str, str, int]:
    return _origin_key(value)


def strip_url_fragment(value: str) -> str:
    return _strip_fragment(value)


def category_link_rejected(candidate_url: str) -> bool:
    return _reject_homepage_candidate(candidate_url)


def looks_like_category_url(url: str) -> bool:
    return _looks_like_category_url(url)


def has_category_anchor_signal(url: str, anchor: Tag) -> bool:
    return _has_category_homepage_signal(url, anchor)


def _url_key(url: str) -> str:
    return _strip_fragment(url).rstrip("/").lower()


def _label_from_path_segment(segment: str) -> str:
    cleaned = segment.replace("-", " ").replace("_", " ").strip()
    if not cleaned:
        return segment
    return " ".join(word.capitalize() for word in cleaned.split())


def _anchor_label(anchor: Tag) -> str | None:
    label = " ".join(anchor.stripped_strings).strip()
    if not label:
        return None
    return " ".join(label.split())


# skipcq: PY-R1000
def _classify_homepage_candidate(
    *,
    candidate_url: str,
    keyword: str,
    anchor: Tag,
) -> tuple[str, int]:
    resolution = resolve_auto_surface(url=candidate_url)
    path = urlsplit(candidate_url).path.lower().rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    depth = _path_depth(path)
    anchor_text = " ".join(anchor.stripped_strings).strip().lower()
    anchor_words = len([word for word in anchor_text.split() if word])
    keyword_hit = bool(keyword) and (
        keyword in candidate_url.lower() or keyword in anchor_text
    )
    nav_boost = 12 if anchor.find_parent(("nav", "header")) is not None else 0
    category_path_boost = _category_path_score_boost(path)
    if resolution.surface.endswith("_listing"):
        return (
            "listing",
            300
            + int(resolution.confidence * 100)
            + nav_boost
            + category_path_boost
            + (25 if keyword_hit else 0),
        )
    if (
        resolution.surface == "content_detail"
        and resolution.confidence <= 0.4
        and _looks_like_listing_link(path, depth=depth, anchor_words=anchor_words)
    ):
        return (
            "listing",
            180 + nav_boost + category_path_boost + (25 if keyword_hit else 0),
        )
    if resolution.surface.endswith("_detail"):
        return (
            "detail",
            220 + int(resolution.confidence * 100) + (25 if keyword_hit else 0),
        )
    if _looks_like_detail_link(slug, depth=depth, anchor_words=anchor_words):
        return "detail", 120 + (25 if keyword_hit else 0)
    return "", 0


def _category_path_score_boost(path: str) -> int:
    return (
        SITEMAP_HOMEPAGE_CATEGORY_PATH_SCORE_BOOST
        if any(token in path for token in SITEMAP_CATEGORY_PATH_TOKENS)
        else 0
    )


def _looks_like_listing_link(path: str, *, depth: int, anchor_words: int) -> bool:
    if depth == 0 or depth > 2:
        return False
    if (
        anchor_words == 0
        or anchor_words > SITEMAP_HOMEPAGE_FALLBACK_MAX_LINK_TEXT_WORDS
    ):
        return False
    terminal = path.rsplit("/", 1)[-1]
    if terminal.isdigit():
        return False
    if _looks_like_locale_segment(terminal):
        return False
    return True


def _looks_like_detail_link(slug: str, *, depth: int, anchor_words: int) -> bool:
    if depth < 2:
        return False
    if anchor_words == 0 or anchor_words > 12:
        return False
    if any(char.isdigit() for char in slug):
        return True
    return slug.count("-") >= 2 or slug.count("_") >= 2


def _looks_like_category_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    if any(token in path for token in SITEMAP_CATEGORY_EXCLUDED_PATH_TOKENS):
        return False
    if any(token in path for token in SITEMAP_CATEGORY_PATH_TOKENS):
        return True
    segments = [segment for segment in path.split("/") if segment]
    if not segments or any(_looks_like_locale_segment(segment) for segment in segments):
        return False
    if any(segment.isdigit() for segment in segments):
        return False
    segment_text = " ".join(segment.replace("-", " ") for segment in segments)
    if any(token in segment_text for token in SITEMAP_CATEGORY_ANCHOR_TEXT_EXCLUDED_TOKENS):
        return False
    category_segments = {
        token
        for token in SITEMAP_CATEGORY_ANCHOR_TEXT_TOKENS
        if token and " " not in token
    }
    return (
        1 <= len(segments) <= 3
        and all(len(segment) >= 2 for segment in segments)
        and any(segment.replace("-", " ") in category_segments for segment in segments)
    )


def _has_category_homepage_signal(url: str, anchor: Tag) -> bool:
    if _looks_like_category_url(url):
        return True
    path = urlsplit(url).path.lower().strip("/")
    if not path or _looks_like_locale_path(path):
        return False
    text = " ".join(anchor.stripped_strings).strip().lower()
    if not text:
        return False
    if any(
        text_has_token(text, token)
        for token in SITEMAP_CATEGORY_ANCHOR_TEXT_EXCLUDED_TOKENS
    ):
        return False
    return any(text_has_token(text, token) for token in SITEMAP_CATEGORY_ANCHOR_TEXT_TOKENS)


def _looks_like_locale_path(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    if not parts or len(parts) > 2:
        return False
    return all(_looks_like_locale_segment(part.replace("_", "-")) for part in parts)


def _reject_homepage_candidate(candidate_url: str) -> bool:
    parsed = urlsplit(candidate_url)
    if parsed.scheme not in {"http", "https"}:
        return True
    path = parsed.path.lower()
    if not path or path == "/":
        return True
    if any(
        path.endswith(ext) for ext in SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_EXTENSIONS
    ):
        return True
    return any(
        token in path for token in SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_PATH_TOKENS
    )


def _path_depth(path: str) -> int:
    parts = [
        part for part in path.split("/") if part and not _looks_like_locale_segment(part)
    ]
    return len(parts)


def _looks_like_locale_segment(value: str) -> bool:
    cleaned = str(value or "").strip().lower()
    if len(cleaned) == 2 and cleaned.isalpha():
        return True
    if len(cleaned) == 5 and cleaned[2] == "-":
        return cleaned[:2].isalpha() and cleaned[3:].isalpha()
    return False


def _strip_fragment(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _origin_key(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    scheme = str(parsed.scheme or "").lower()
    hostname = str(parsed.hostname or "").lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, hostname, port


def _extract_locs(xml: ElementTree.Element) -> list[str]:
    return [
        loc.text.strip()
        for url_el in xml.findall(f"{{{SITEMAP_NS}}}url")
        if (loc := url_el.find(f"{{{SITEMAP_NS}}}loc")) is not None and loc.text
    ]


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
