from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
import re
from typing import Any
from urllib.parse import urlsplit

from app.extraction.documents import HtmlDocument, HtmlNode

from app.core.config.data_enrichment import ECOMMERCE_LISTING_SURFACE
from app.core.config.sitemap import (
    SITE_LINK_DISCOVERY_FETCH_TIMEOUT_SECONDS,
    SITE_LINK_DISCOVERY_CARD_SELECTOR_HINTS,
    SITE_LINK_DISCOVERY_MAX_DEPTH,
    SITE_LINK_DISCOVERY_MAX_LINKS_PER_PAGE,
    SITE_LINK_DISCOVERY_MAX_PAGES,
    SITE_LINK_DISCOVERY_VALIDATE_MAX_URLS,
    SITEMAP_CATEGORY_ANCHOR_TEXT_EXCLUDED_TOKENS,
    SITEMAP_CATEGORY_ANCHOR_TEXT_TOKENS,
)
from app.core.config.url_path_markers import detail_path_markers
from app.crawl.sitemap_nav import (
    build_category_nav_tree,
    category_link_rejected,
    category_origin_key,
    category_url_key,
    has_category_anchor_signal,
    looks_like_category_url,
    strip_url_fragment,
)
from app.crawl.sitemap_resolver import SitemapResolutionResult
from app.crawl.utils import normalize_target_url, text_has_token
from app.acquisition.fetch.fetch_context import fetch_page
from app.core.shared.url_utils import absolute_url
from app.core.shared.url_utils import (
    looks_like_locale_segment as _looks_like_locale_segment,
)
from app.core.url_safety import validate_public_target

FetchPage = Callable[..., Awaitable[Any]]

_PRICE_RE = re.compile(r"(?:[$€£¥₹]\s?\d|\d[\d,.]*\s?(?:usd|eur|gbp|inr))", re.I)
_listing_detail_path_hints = tuple(
    str(marker or "").strip().lower()
    for marker in detail_path_markers(ECOMMERCE_LISTING_SURFACE)
    if str(marker or "").strip()
)


@dataclass(frozen=True, slots=True)
class SiteLinkCandidate:
    url: str
    label: str | None
    source_url: str
    depth: int
    score: int
    reason: str
    validated: bool = False


@dataclass(slots=True)
class SiteLinkDiscoveryDiagnostics:
    fetched: list[dict[str, object]] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)
    candidates_seen: int = 0
    validation_checked: int = 0
    validation_kept: int = 0

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1

    def as_dict(self) -> dict[str, object]:
        return {
            "fetched": self.fetched,
            "rejected": self.rejected,
            "candidates_seen": self.candidates_seen,
            "validation_checked": self.validation_checked,
            "validation_kept": self.validation_kept,
        }


# skipcq: PY-R1000
async def discover_rendered_category_links(
    seed_url: str,
    *,
    limit: int,
    max_depth: int = SITE_LINK_DISCOVERY_MAX_DEPTH,
    max_pages: int = SITE_LINK_DISCOVERY_MAX_PAGES,
    validate_candidates: bool = False,
    fetch_page_impl: FetchPage = fetch_page,
) -> SitemapResolutionResult:
    """Discover category/listing URLs from rendered same-origin site links."""

    normalized_seed = normalize_target_url(seed_url)
    if not normalized_seed:
        raise ValueError("empty domain")
    await validate_public_target(normalized_seed)

    origin = category_origin_key(normalized_seed)
    bounded_limit = max(1, int(limit))
    bounded_depth = max(0, int(max_depth))
    bounded_pages = max(1, int(max_pages))
    diagnostics = SiteLinkDiscoveryDiagnostics()
    queue: deque[tuple[str, int]] = deque([(normalized_seed, 0)])
    fetched_keys: set[str] = set()
    queued_keys: set[str] = {category_url_key(normalized_seed)}
    candidates: dict[str, SiteLinkCandidate] = {}
    requested_branch = _category_branch(normalized_seed)

    while queue and len(fetched_keys) < bounded_pages:
        page_url, depth = queue.popleft()
        queued_keys.discard(category_url_key(page_url))
        page_key = category_url_key(page_url)
        if page_key in fetched_keys:
            continue
        fetched_keys.add(page_key)
        page_candidates = await _discover_page_candidates(
            page_url,
            depth=depth,
            origin=origin,
            diagnostics=diagnostics,
            requested_branch=requested_branch,
            fetch_page_impl=fetch_page_impl,
        )
        if page_candidates is None:
            continue
        _merge_page_candidates(candidates, page_candidates)
        if depth >= bounded_depth:
            continue
        _enqueue_page_candidates(
            queue,
            page_candidates,
            depth=depth,
            bounded_pages=bounded_pages,
            fetched_keys=fetched_keys,
            queued_keys=queued_keys,
        )

    ranked = _rank_candidates(candidates.values())
    if validate_candidates:
        ranked = await _validate_ranked_candidates(
            ranked,
            limit=bounded_limit,
            diagnostics=diagnostics,
            fetch_page_impl=fetch_page_impl,
        )
    selected = ranked[:bounded_limit]
    urls = [candidate.url for candidate in selected]
    labels = {
        candidate.url: candidate.label for candidate in selected if candidate.label
    }
    return SitemapResolutionResult(
        urls=urls,
        source="rendered_site_links",
        nav_tree=build_category_nav_tree(urls, labels_by_url=labels),
        diagnostics=diagnostics.as_dict(),
    )


async def _discover_page_candidates(
    page_url: str,
    *,
    depth: int,
    origin: tuple[str, str, int],
    diagnostics: SiteLinkDiscoveryDiagnostics,
    requested_branch: tuple[str, ...],
    fetch_page_impl: FetchPage,
) -> list[SiteLinkCandidate] | None:
    result = await fetch_page_impl(
        page_url,
        timeout_seconds=SITE_LINK_DISCOVERY_FETCH_TIMEOUT_SECONDS,
        fetch_mode="auto",
        prefer_browser=True,
        browser_reason="site-link-discovery",
        surface=ECOMMERCE_LISTING_SURFACE,
        max_pages=1,
        max_scrolls=1,
    )
    final_url = str(getattr(result, "final_url", "") or page_url)
    html = str(getattr(result, "html", "") or "")
    blocked = bool(getattr(result, "blocked", False))
    diagnostics.fetched.append(
        {
            "url": page_url,
            "final_url": final_url,
            "status_code": int(getattr(result, "status_code", 0) or 0),
            "method": str(getattr(result, "method", "") or ""),
            "blocked": blocked,
            "html_length": len(html),
            "depth": depth,
        }
    )
    if not html or blocked:
        diagnostics.reject("empty_or_blocked_page")
        return None
    return _extract_rendered_candidates(
        html=html,
        page_url=final_url,
        origin=origin,
        depth=depth,
        diagnostics=diagnostics,
        requested_branch=requested_branch,
    )


def _merge_page_candidates(
    candidates: dict[str, SiteLinkCandidate], page_candidates: list[SiteLinkCandidate]
) -> None:
    for candidate in page_candidates:
        existing = candidates.get(candidate.url)
        if existing is None or candidate.score > existing.score:
            candidates[candidate.url] = candidate


def _enqueue_page_candidates(
    queue: deque[tuple[str, int]],
    page_candidates: list[SiteLinkCandidate],
    *,
    depth: int,
    bounded_pages: int,
    fetched_keys: set[str],
    queued_keys: set[str],
) -> None:
    for candidate in page_candidates:
        key = category_url_key(candidate.url)
        if key in fetched_keys or key in queued_keys:
            continue
        if len(fetched_keys) + len(queue) >= bounded_pages:
            break
        queue.append((candidate.url, depth + 1))
        queued_keys.add(key)


def _extract_rendered_candidates(
    *,
    html: str,
    page_url: str,
    origin: tuple[str, str, int],
    depth: int,
    diagnostics: SiteLinkDiscoveryDiagnostics,
    requested_branch: tuple[str, ...] = (),
) -> list[SiteLinkCandidate]:
    document = HtmlDocument("site_link_discovery", html or "")
    candidates: list[SiteLinkCandidate] = []
    anchors = document.safe_css("a[href]")[:SITE_LINK_DISCOVERY_MAX_LINKS_PER_PAGE]
    page_key = category_url_key(page_url)
    for anchor in anchors:
        raw_href = anchor.attribute("href")
        candidate_url = normalize_target_url(
            strip_url_fragment(absolute_url(page_url, raw_href))
        )
        if not candidate_url:
            diagnostics.reject("invalid_url")
            continue
        if category_url_key(candidate_url) == page_key:
            diagnostics.reject("self_url")
            continue
        if category_origin_key(candidate_url) != origin:
            diagnostics.reject("off_origin")
            continue
        if category_link_rejected(candidate_url):
            diagnostics.reject("utility_or_asset")
            continue
        if requested_branch and not _matches_requested_branch(
            candidate_url,
            requested_branch,
        ):
            diagnostics.reject("unrelated_branch")
            continue
        label = _anchor_label(anchor)
        score, reason = _score_candidate(candidate_url, anchor, label)
        if score <= 0:
            diagnostics.reject(reason or "weak_signal")
            continue
        diagnostics.candidates_seen += 1
        candidates.append(
            SiteLinkCandidate(
                url=candidate_url,
                label=label,
                source_url=page_url,
                depth=depth,
                score=score,
                reason=reason,
            )
        )
    return candidates


def _score_candidate(url: str, anchor: HtmlNode, label: str | None) -> tuple[int, str]:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    text = str(label or "").strip().lower()
    if _anchor_text_rejected(text):
        return 0, "excluded_anchor_text"
    score = 0
    reasons: list[str] = []
    if looks_like_category_url(url):
        score += 180
        reasons.append("category_path")
    if has_category_anchor_signal(url, anchor):
        score += 130
        reasons.append("category_anchor")
    if any(node.tag() in {"nav", "header", "menu"} for node in anchor.ancestors()):
        score += 25
        reasons.append("nav")
    if any(
        text_has_token(text, token) for token in SITEMAP_CATEGORY_ANCHOR_TEXT_TOKENS
    ):
        score += 40
        reasons.append("category_text")
    if path.count("/") > 4:
        score -= 30
    if any(token in path for token in _listing_detail_path_hints):
        score -= 180
        reasons.append("detail_penalty")
    if not reasons:
        return 0, "no_category_signal"
    return score, "+".join(reasons)


def _rank_candidates(
    candidates: Iterable[SiteLinkCandidate],
) -> list[SiteLinkCandidate]:
    best: dict[str, SiteLinkCandidate] = {}
    for candidate in candidates:
        if not isinstance(candidate, SiteLinkCandidate):
            continue
        key = category_url_key(candidate.url)
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return sorted(
        best.values(),
        key=lambda item: (
            -item.score,
            item.depth,
            item.url,
        ),
    )


async def _validate_ranked_candidates(
    ranked: list[SiteLinkCandidate],
    *,
    limit: int,
    diagnostics: SiteLinkDiscoveryDiagnostics,
    fetch_page_impl: FetchPage,
) -> list[SiteLinkCandidate]:
    kept: list[SiteLinkCandidate] = []
    max_checks = max(limit, int(SITE_LINK_DISCOVERY_VALIDATE_MAX_URLS))
    for candidate in ranked:
        if len(kept) >= limit or diagnostics.validation_checked >= max_checks:
            break
        diagnostics.validation_checked += 1
        result = await fetch_page_impl(
            candidate.url,
            timeout_seconds=SITE_LINK_DISCOVERY_FETCH_TIMEOUT_SECONDS,
            fetch_mode="auto",
            prefer_browser=True,
            browser_reason="site-link-validation",
            surface=ECOMMERCE_LISTING_SURFACE,
            max_pages=1,
            max_scrolls=1,
        )
        html = str(getattr(result, "html", "") or "")
        if _html_has_listing_signals(html):
            diagnostics.validation_kept += 1
            kept.append(
                SiteLinkCandidate(
                    url=candidate.url,
                    label=candidate.label,
                    source_url=candidate.source_url,
                    depth=candidate.depth,
                    score=candidate.score,
                    reason=f"{candidate.reason}+validated",
                    validated=True,
                )
            )
        else:
            diagnostics.reject("validation_no_listing_signal")
    return kept


def _category_branch(url: str) -> tuple[str, ...]:
    segments = tuple(
        segment.casefold()
        for segment in urlsplit(url).path.split("/")
        # Underscores normalize to dashes before the locale check so segments
        # like "en_US" still classify as locale branches (pre-hoist behavior).
        if segment and not _looks_like_locale_segment(segment.replace("_", "-"))
    )
    return segments


def _matches_requested_branch(url: str, requested_branch: tuple[str, ...]) -> bool:
    candidate = _category_branch(url)
    return bool(candidate) and (
        candidate[: len(requested_branch)] == requested_branch
        or requested_branch[-1] in candidate
    )


def _html_has_listing_signals(html: str) -> bool:
    document = HtmlDocument("site_link_validation", html or "")
    productish_nodes = sum(
        len(document.safe_css(selector))
        for selector in SITE_LINK_DISCOVERY_CARD_SELECTOR_HINTS
    )
    product_links = [
        anchor
        for anchor in document.safe_css("a[href]")
        if any(
            token in str(anchor.attribute("href") or "").lower()
            for token in _listing_detail_path_hints
        )
    ]
    price_hits = len(_PRICE_RE.findall(document.visible_text()[:20_000]))
    return productish_nodes >= 4 or (len(product_links) >= 3 and price_hits >= 2)


def _anchor_text_rejected(text: str) -> bool:
    if not text:
        return False
    return any(
        text_has_token(text, token)
        for token in SITEMAP_CATEGORY_ANCHOR_TEXT_EXCLUDED_TOKENS
    )


def _anchor_label(anchor: HtmlNode) -> str | None:
    label = " ".join(anchor.text().split()).strip()
    if not label:
        label = str(
            anchor.attribute("aria-label") or anchor.attribute("title") or ""
        ).strip()
    if not label:
        return None
    return " ".join(label.split())
