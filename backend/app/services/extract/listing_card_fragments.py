from __future__ import annotations

__all__ = (
    "FragmentScoreFn",
    "listing_selector_group",
    "listing_capture_selectors",
    "listing_node_text",
    "listing_node_attr",
    "listing_node_html",
    "listing_node_signature",
    "listing_signature_url_shape",
    "listing_fragment_structural_signature",
    "listing_node_tag",
    "listing_node_css",
    "base_listing_fragment_score",
    "select_listing_fragment_nodes",
    "listing_card_html_fragments",
    "collect_listing_fragment_html",
    "listing_selector_is_weak",
    "heuristic_listing_card_count_from_html",
)

import logging
import re
from urllib.parse import urlsplit
from typing import Callable

from selectolax.lexbor import LexborHTMLParser, SelectolaxError

from app.services.config.extraction_rules import (
    LISTING_CATEGORY_PATH_PREFIXES,
    LISTING_CHROME_TEXT_LIMIT,
    LISTING_FALLBACK_CONTAINER_SELECTOR,
    LISTING_NON_LISTING_PATH_TOKENS,
    LISTING_PRODUCT_DETAIL_ID_RE,
    LISTING_PROMINENT_TITLE_TAGS,
    LISTING_STRUCTURE_NEGATIVE_HINTS,
    LISTING_STRUCTURE_POSITIVE_HINTS,
    LISTING_UTILITY_TITLE_TOKENS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS
from app.services.shared.field_coerce import PRICE_RE, clean_text

FragmentScoreFn = Callable[[object], int]
logger = logging.getLogger(__name__)


def listing_selector_group(surface: str) -> str:
    normalized = str(surface or "").strip().lower()
    if normalized == "article_listing":
        return "article"
    return "jobs" if normalized.startswith("job_") else "ecommerce"


def listing_capture_selectors(surface: str) -> list[str]:
    return [
        *list(CARD_SELECTORS.get(listing_selector_group(surface)) or []),
        LISTING_FALLBACK_CONTAINER_SELECTOR,
    ]


def listing_node_text(node) -> str:
    try:
        return clean_text(str(node.text(separator=" ", strip=True) or ""))
    except (AttributeError, TypeError, ValueError):
        return ""


def listing_node_attr(node, name: str) -> str:
    raw_attrs = getattr(node, "attributes", {}) or {}
    attrs = raw_attrs if isinstance(raw_attrs, dict) else {}
    return str(attrs.get(name) or "").strip()


def listing_node_html(node) -> str:
    try:
        return str(getattr(node, "html", "") or "").strip()
    except Exception:
        return ""


def listing_node_signature(node, *, include_title: bool = True) -> str:
    attrs = getattr(node, "attributes", {}) or {}
    values = [
        str(attrs.get("class") or ""),
        str(attrs.get("id") or ""),
        str(attrs.get("role") or ""),
        str(attrs.get("aria-label") or ""),
    ]
    if include_title:
        values.append(str(attrs.get("title") or ""))
    return " ".join(values).lower()


def _listing_count_bucket(count: int | None) -> str:
    """Bucket a count into ``{0, 1, 2_5, 6_plus}``.

    If *count* is None it is treated as 0.
    """
    value = int(count) if count is not None else 0
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 5:
        return "2_5"
    return "6_plus"


def _listing_positive_class_bucket(node) -> str:
    """
    Return the first :data:`LISTING_STRUCTURE_POSITIVE_HINTS` token present in
    the node's class/id/role signature, or the empty string when none hit and
    the signature does not carry a :data:`LISTING_STRUCTURE_NEGATIVE_HINTS`
    token. When only negative hints are present the bucket is ``"neg"`` so
    promo/nav chrome is not collapsed with positive product-card shapes.
    """
    signature = listing_node_signature(node, include_title=False)
    if not signature:
        return ""
    for token in LISTING_STRUCTURE_POSITIVE_HINTS:
        if token and token in signature:
            return str(token)
    for token in LISTING_STRUCTURE_NEGATIVE_HINTS:
        if token and token in signature:
            return "neg"
    return ""


def _listing_signature_price_signal(node) -> str:
    """Return ``"price"`` when the fragment text carries a price shape, else ``""``."""
    text = listing_node_text(node)
    if not text:
        return ""
    return "price" if PRICE_RE.search(text) else ""


def _listing_signature_title_tag(node) -> str:
    """
    Return the tag name of the first prominent-title descendant (see
    :data:`LISTING_PROMINENT_TITLE_TAGS`) present in the fragment, else the
    empty string. Shape-only; no text/content is captured.
    """
    descendants = listing_node_css(node, "strong, b, h1, h2, h3, h4, h5, h6")
    for descendant in descendants:
        tag = str(getattr(descendant, "tag", "") or "").strip().lower()
        if tag and tag in LISTING_PROMINENT_TITLE_TAGS:
            return tag
    return ""


def listing_signature_url_shape(url: str) -> tuple[str, str]:
    """
    Return the ``(category_prefix_bucket, has_detail_marker)`` URL-shape pair.

    ``category_prefix_bucket`` is the first matching
    :data:`LISTING_CATEGORY_PATH_PREFIXES` entry for the candidate URL path
    (empty string when none match). ``has_detail_marker`` is ``"1"`` when the
    URL carries a detail identity marker (per
    :data:`LISTING_PRODUCT_DETAIL_ID_RE`) and ``"0"`` otherwise.
    """
    raw = str(url or "")
    if not raw:
        return "", "0"
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "", "0"
    path = str(parsed.path or "").lower()
    prefix_bucket = ""
    for prefix in LISTING_CATEGORY_PATH_PREFIXES:
        prefix_text = str(prefix or "")
        if prefix_text and path.startswith(prefix_text):
            prefix_bucket = prefix_text
            break
    detail_marker = "1" if LISTING_PRODUCT_DETAIL_ID_RE.search(raw) else "0"
    return prefix_bucket, detail_marker


def listing_fragment_structural_signature(node, *, url: str) -> str:
    """
    Return a deterministic, fragment-local fingerprint used by the cohort check
    in :mod:`listing_candidate_ranking`.

    The signature is a ``"|"``-delimited string composed of shape-only inputs:

    1. lowercased tag name
    2. :data:`LISTING_STRUCTURE_POSITIVE_HINTS` bucket derived from the node's
       class/id/role/aria-label signature (``"neg"`` when only a negative hint
       is present, empty otherwise)
    3. anchor-count bucket (``{0, 1, 2_5, 6_plus}``)
    4. image-count bucket (``{0, 1, 2_5, 6_plus}``)
    5. price signal (``"price"`` or ``""``)
    6. prominent-title descendant tag (``{"h1"..."h6", "strong", "b", ""}``)
    7. first matching :data:`LISTING_CATEGORY_PATH_PREFIXES` entry for the URL
       path (empty string when none match)
    8. has-detail-marker boolean (``"1"`` / ``"0"``) from
       :data:`LISTING_PRODUCT_DETAIL_ID_RE`

    Pure function: no I/O, no node mutation, no host/domain/brand/CDN/site
    tokens. Reuses :func:`listing_node_signature` for the class/id/role
    normalization path so the two helpers stay in sync.
    """
    tag = str(getattr(node, "tag", "") or "").strip().lower()
    positive_bucket = _listing_positive_class_bucket(node)
    anchor_count = len(_node_listing_links(node))
    try:
        image_count = len(list(node.css("img")))
    except (SelectolaxError, ValueError, AttributeError, TypeError):
        image_count = 0
    anchor_bucket = _listing_count_bucket(anchor_count)
    image_bucket = _listing_count_bucket(image_count)
    price_signal = _listing_signature_price_signal(node)
    title_tag = _listing_signature_title_tag(node)
    url_prefix_bucket, has_detail_marker = listing_signature_url_shape(url)
    return (
        f"{tag}|{positive_bucket}|{anchor_bucket}|{image_bucket}|"
        f"{price_signal}|{title_tag}|{url_prefix_bucket}|{has_detail_marker}"
    )


def listing_node_tag(node) -> str:
    return str(getattr(node, "tag", "") or "").strip().lower()


def listing_node_css(node, selector: str) -> list[object]:
    if not selector:
        return []
    try:
        return list(node.css(selector))
    except (SelectolaxError, ValueError):
        logger.warning("Skipping invalid listing selector: %s", selector, exc_info=True)
        return []


def base_listing_fragment_score(node) -> int:
    tag_name = str(getattr(node, "tag", "") or "").strip().lower()
    if tag_name in {"header", "nav", "footer"}:
        return -100
    signature = _listing_node_signature(node)
    has_positive_signature = any(
        token in signature for token in LISTING_STRUCTURE_POSITIVE_HINTS
    )
    if (
        any(token in signature for token in LISTING_STRUCTURE_NEGATIVE_HINTS)
        and not has_positive_signature
    ):
        return -10
    score = 0
    if has_positive_signature:
        score += 6
    links = _node_listing_links(node)
    link_count = len(links)
    if link_count == 0:
        return -100
    if link_count == 1:
        score += 4
    elif link_count <= 6:
        score += 2
    elif link_count <= 12:
        score -= 1
    else:
        score -= 6
    text = listing_node_text(node)
    text_len = len(text)
    if text_len < 12:
        score -= 3
    elif text_len <= 2000:
        score += 3
    else:
        score -= 3
    has_price = bool(PRICE_RE.search(text))
    if has_price:
        score += 3
    if tag_name in {"article", "li", "tr", "section"}:
        score += 2
    # Strong "product card shape" bonus: a node that has a price, at least one
    # image, and one or more anchors is almost certainly a complete card and
    # should out-rank inner sibling subdivs (productInfo / productPricing)
    # that only carry one of the three signals in isolation.
    if has_price and _node_has_listing_media(node):
        score += 4
    return score


def _node_listing_links(node) -> list[object]:
    links = []
    if listing_node_attr(node, "href"):
        links.append(node)
    links.extend(listing_node_css(node, "a[href]"))
    return links


def select_listing_fragment_nodes(
    parser: LexborHTMLParser,
    *,
    surface: str,
    score_node: FragmentScoreFn | None = None,
    limit: int | None = None,
) -> list[object]:
    scored = _scored_listing_fragment_nodes(
        parser,
        surface=surface,
        score_node=score_node,
    )
    if not scored:
        return []
    rows = scored if limit is None else scored[: max(1, int(limit))]
    return [node for _score, _order, node in rows]


def listing_card_html_fragments(
    dom_parser: LexborHTMLParser,
    *,
    is_job: bool,
    fallback_fragment_limit: int,
    limit: int | None = None,
) -> list[object]:
    fragment_limit = max(int(fallback_fragment_limit), int(limit or 0))
    return select_listing_fragment_nodes(
        dom_parser,
        surface="job_listing" if is_job else "ecommerce_listing",
        limit=max(1, fragment_limit),
    )


def collect_listing_fragment_html(
    parser: LexborHTMLParser,
    *,
    surface: str,
    seen: set[str],
    byte_budget: int,
    score_node: FragmentScoreFn | None = None,
    limit: int | None = None,
) -> list[str]:
    if byte_budget <= 0:
        return []
    scored = _scored_listing_fragment_nodes(
        parser,
        surface=surface,
        score_node=score_node,
    )
    if limit is not None:
        scored = scored[: max(1, int(limit))]
    fragments: list[str] = []
    used_bytes = 0
    for _score, _order, node in scored:
        fragment = str(getattr(node, "html", "") or "").strip()
        if not fragment or fragment in seen:
            continue
        fragment_bytes = len(fragment.encode("utf-8"))
        if used_bytes + fragment_bytes > byte_budget:
            continue
        seen.add(fragment)
        fragments.append(fragment)
        used_bytes += fragment_bytes
    return fragments


def _scored_listing_fragment_nodes(
    parser: LexborHTMLParser,
    *,
    surface: str,
    score_node: FragmentScoreFn | None,
) -> list[tuple[int, int, object]]:
    scorer = score_node or base_listing_fragment_score
    seen: set[str] = set()
    scored: list[tuple[int, int, object]] = []
    order = 0
    fragment_limit = max(1, int(crawler_runtime_settings.listing_fallback_fragment_limit))
    selectors = list(CARD_SELECTORS.get(listing_selector_group(surface)) or [])
    for selector in selectors:
        matches = listing_node_css(parser, selector)
        for node in matches:
            order += 1
            score = int(scorer(node))
            if score <= 0:
                continue
            fragment = str(getattr(node, "html", "") or "").strip()
            if not fragment or fragment in seen:
                continue
            seen.add(fragment)
            scored.append((score, order, node))
    scanned = 0
    for node in listing_node_css(parser, LISTING_FALLBACK_CONTAINER_SELECTOR):
        scanned += 1
        if scanned > fragment_limit * 40:
            break
        order += 1
        score = int(scorer(node))
        if score <= 0:
            continue
        fragment = str(getattr(node, "html", "") or "").strip()
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        scored.append((score, order, node))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return scored


_PRICE_HINT_RE = re.compile(
    r"(?:rs\.?|inr|\$|£|€)\s*\d|\b\d[\d,]{2,}\b",
    re.I,
)

def listing_selector_is_weak(selector: str) -> bool:
    normalized = " ".join(str(selector or "").strip().lower().split())
    return normalized == ".product" or any(
        token in normalized
        for token in (
            "[class*='product' i]",
            '[class*="product" i]',
            "[class*='productcard' i]",
            '[class*="productcard" i]',
            "[data-testid*='product' i]",
            '[data-testid*="product" i]',
            "[data-test*='product' i]",
            '[data-test*="product" i]',
            "[data-component*='product' i]",
            '[data-component*="product" i]',
            "[data-automation*='product' i]",
            '[data-automation*="product" i]',
        )
    )


def heuristic_listing_card_count_from_html(html: str, *, surface: str) -> int:
    if not html:
        return 0
    parser = LexborHTMLParser(html)
    seen: set[str] = set()
    count = 0
    nodes = listing_node_css(parser, LISTING_FALLBACK_CONTAINER_SELECTOR)
    for node in nodes:
        fragment = str(getattr(node, "html", "") or "").strip()
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        if base_listing_fragment_score(node) <= 0:
            continue
        if _node_supports_listing_heuristic(node, surface=surface):
            if _node_contains_nested_listing_candidates(node, surface=surface):
                continue
            count += 1
    return count


def _node_supports_listing_heuristic(node, *, surface: str) -> bool:
    if _node_looks_like_listing_chrome(node):
        return False
    signature = _listing_node_signature(node)
    has_positive_signature = any(
        token in signature for token in LISTING_STRUCTURE_POSITIVE_HINTS
    )
    has_price = _node_text_has_price(node)
    has_detail_link = _node_has_detail_like_link(node, surface=surface)
    has_media = _node_has_listing_media(node)
    if has_detail_link:
        return True
    if has_price and (has_positive_signature or has_media):
        return True
    return has_positive_signature and has_media


def _node_looks_like_listing_chrome(node) -> bool:
    signature = _listing_node_signature(node)
    if any(token in signature for token in LISTING_NON_LISTING_PATH_TOKENS):
        return True
    text = listing_node_text(node)[: int(LISTING_CHROME_TEXT_LIMIT)]
    return any(
        token in text
        for token in (
            *LISTING_UTILITY_TITLE_TOKENS,
            "newsletter",
            "whatsapp",
        )
    )


def _node_contains_nested_listing_candidates(node, *, surface: str) -> bool:
    node_fragment = str(getattr(node, "html", "") or "").strip()
    descendants = listing_node_css(node, LISTING_FALLBACK_CONTAINER_SELECTOR)
    for descendant in descendants:
        if str(getattr(descendant, "html", "") or "").strip() == node_fragment:
            continue
        if base_listing_fragment_score(descendant) <= 0:
            continue
        if _node_supports_listing_heuristic(descendant, surface=surface):
            return True
    return False


def _listing_node_signature(node) -> str:
    return listing_node_signature(node, include_title=False)


def _node_text_has_price(node) -> bool:
    return bool(_PRICE_HINT_RE.search(listing_node_text(node)))


def _node_has_listing_media(node) -> bool:
    return bool(listing_node_css(node, "img, picture img, picture source"))


def _node_has_detail_like_link(node, *, surface: str) -> bool:
    href_tokens = (
        ("/job/", "/jobs/", "/viewjob", "showjob=", "/careers/")
        if str(surface or "").strip().lower().startswith("job_")
        else ("/products/", "/product/", "/p/", "/dp/", "/item/")
    )
    anchors = listing_node_css(node, "a[href]")
    for anchor in anchors[:6]:
        attrs = getattr(anchor, "attributes", {}) or {}
        href = str(attrs.get("href") or "").strip().lower()
        if not href or href.startswith(("#", "javascript:")):
            continue
        if _listing_href_is_structural(href):
            continue
        if any(token in href for token in href_tokens):
            return True
    return False


def _listing_href_is_structural(href: str) -> bool:
    try:
        parsed = urlsplit(href)
    except Exception:
        return False
    segments = [
        segment.strip().lower()
        for segment in str(parsed.path or "").split("/")
        if segment.strip()
    ]
    if not segments:
        return False
    tokenized = [
        {
            token
            for token in re.split(r"[\-\.]+", segment)
            if token
        }
        for segment in segments
    ]
    if tokenized[-1] & set(LISTING_NON_LISTING_PATH_TOKENS):
        return True
    leading = tokenized[:-1] if len(tokenized) <= 2 else []
    return any(tokens & set(LISTING_NON_LISTING_PATH_TOKENS) for tokens in leading)
