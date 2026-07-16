"""Pure, surface-aware listing-card selection primitives.

This module has no acquisition or extraction runtime dependencies. Both sides
pass the canonical ``SurfaceSpec``/``ListingSchema`` lens and DOM-like nodes
implementing the small HtmlDocument/HtmlNode interface used below.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from app.core.config.cascade import (
    CASCADE_LISTING_ONCLICK_URL_PATTERN,
    CASCADE_LISTING_PRICE_SIGNAL_PATTERN,
    CASCADE_LISTING_RECORD_KEY_ATTRIBUTES,
    CASCADE_LISTING_RECORD_ONCLICK_ATTRIBUTES,
    CASCADE_LISTING_RECORD_URL_ATTRIBUTES,
)
from app.core.config.extraction_recipes import (
    ECOMMERCE_LISTING_CARD_SELECTORS,
    ECOMMERCE_LISTING_GENERIC_CARD_SELECTORS,
    JOB_LISTING_CARD_SELECTORS,
)
from app.core.config.extraction_rules import LISTING_CARD_URL_ATTRS
from app.core.config.selectors import CARD_SELECTORS
from app.core.records.field_url_normalization import same_site
from app.core.records.url_identity import listing_url_is_structural

_PRICE_SIGNAL = re.compile(CASCADE_LISTING_PRICE_SIGNAL_PATTERN, re.I)
_ONCLICK_URL = re.compile(CASCADE_LISTING_ONCLICK_URL_PATTERN)
_GENERIC_SELECTORS = frozenset(
    {
        *ECOMMERCE_LISTING_GENERIC_CARD_SELECTORS,
        "section",
        "div",
        *(selector for selector in CARD_SELECTORS.get("ecommerce", ()) if selector.startswith("a[")),
    }
)


@dataclass(frozen=True, slots=True)
class ListingCard:
    """One admitted card and the shared facts used by every consumer."""

    node: Any
    selector: str
    selector_index: int
    identity: str
    url: str
    quality_score: int


def _domain(surface: object) -> str:
    domain = str(getattr(surface, "domain", "") or "").strip().lower()
    if domain:
        return domain
    value = getattr(surface, "surface", surface)
    text = str(getattr(value, "value", value) or "").strip().lower()
    return "jobs" if text.startswith("job_") else "commerce"


def derive_card_selectors(surface: object) -> tuple[str, ...]:
    """Return de-duplicated config-owned selectors for a surface lens."""

    domain = _domain(surface)
    extraction_selectors = (
        JOB_LISTING_CARD_SELECTORS if domain == "jobs" else ECOMMERCE_LISTING_CARD_SELECTORS
    )
    runtime_group = "jobs" if domain == "jobs" else "ecommerce"
    runtime_selectors = (
        CARD_SELECTORS.get(runtime_group, ()) if isinstance(CARD_SELECTORS, dict) else ()
    )
    return tuple(
        dict.fromkeys(
            value
            for selector in (*extraction_selectors, *runtime_selectors)
            if (value := str(selector or "").strip())
        )
    )


def _css(node: Any, selector: str) -> tuple[Any, ...]:
    try:
        method = getattr(node, "safe_css", None) or getattr(node, "css")
        return tuple(method(selector))
    except Exception:
        return ()


def _attribute(node: Any, name: str) -> str:
    try:
        method = getattr(node, "attribute", None)
        if callable(method):
            return str(method(name) or "").strip()
        return str((getattr(node, "attributes", {}) or {}).get(name) or "").strip()
    except Exception:
        return ""


def _has_attribute(node: Any, name: str) -> bool:
    try:
        method = getattr(node, "attributes", None)
        values = method() if callable(method) else method
        return name in (values or {})
    except Exception:
        return False


def _text(node: Any) -> str:
    try:
        method = getattr(node, "content_text", None)
        value = method() if callable(method) else node.text(separator=" ", strip=True)
        return " ".join(str(value or "").split())
    except Exception:
        return ""


def _html(node: Any) -> str:
    try:
        value = getattr(node, "html", "")
        return str(value() if callable(value) else value or "")
    except Exception:
        return ""


def _node_key(node: Any) -> str:
    try:
        identity = getattr(node, "identity", None)
        if callable(identity):
            return f"node:{identity()}"
        mem_id = getattr(node, "mem_id", None)
        if mem_id is not None:
            return f"node:{int(mem_id)}"
    except Exception:
        pass
    return "html:" + hashlib.sha1(
        _html(node).encode("utf-8"), usedforsecurity=False
    ).hexdigest()


def _is_hidden_self(node: Any) -> bool:
    try:
        method = getattr(node, "is_hidden", None)
        if callable(method) and method():
            return True
    except Exception:
        pass
    if _has_attribute(node, "hidden"):
        return True
    style = _attribute(node, "style").replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style


def _is_hidden(node: Any) -> bool:
    if _is_hidden_self(node):
        return True
    try:
        ancestors = getattr(node, "ancestors", None)
        if callable(ancestors):
            return any(_is_hidden_self(ancestor) for ancestor in ancestors())
        parent = getattr(node, "parent", None)
        current = parent() if callable(parent) else parent
        while current is not None:
            if _is_hidden_self(current):
                return True
            current = getattr(current, "parent", None)
    except Exception:
        return False
    return False


def _candidate_nodes(node: Any) -> tuple[Any, ...]:
    return (node, *_css(node, "a[href], [data-href], [data-url]"))


def _candidate_url(node: Any, *, page_url: str) -> str:
    for candidate in _candidate_nodes(node):
        for attribute in (*LISTING_CARD_URL_ATTRS, *CASCADE_LISTING_RECORD_URL_ATTRIBUTES):
            value = _attribute(candidate, attribute)
            if value and not value.lower().startswith(("#", "javascript:", "mailto:", "tel:")):
                return urljoin(page_url, value)
    for candidate in (node, *_css(node, "*")):
        for attribute in CASCADE_LISTING_RECORD_ONCLICK_ATTRIBUTES:
            if match := _ONCLICK_URL.search(_attribute(candidate, attribute)):
                return urljoin(page_url, match.group(1))
    return ""


def stable_card_identity(node: Any, *, page_url: str) -> str:
    """Return stable URL identity, then configured record key, then no identity."""

    url = _candidate_url(node, page_url=page_url)
    identity = stable_url_identity(url)
    if identity:
        return identity
    for candidate in (node, *_css(node, "*")):
        for attribute in CASCADE_LISTING_RECORD_KEY_ATTRIBUTES:
            if value := _attribute(candidate, attribute):
                return f"key:{attribute}={value.casefold()}"
    return ""


def stable_url_identity(url: str) -> str:
    """Canonical case-folded URL identity used across card sources."""

    parsed = urlparse(str(url or "").strip())
    host = str(parsed.hostname or "").casefold().strip(".")
    path = unquote(str(parsed.path or "")).casefold().rstrip("/")
    query = str(parsed.query or "").strip()
    if host and path:
        return f"url:{host}{path}" + (f"?{query}" if query else "")
    return ""


def card_quality_score(
    node: Any,
    *,
    surface: object,
    page_url: str,
    selector: str,
) -> int:
    """Score only generic, surface-relevant evidence; selectors add no data."""

    text = _text(node)
    url = _candidate_url(node, page_url=page_url)
    score = int(bool(url)) + int(len(re.findall(r"\w+", text)) >= 2)
    has_media = bool(_css(node, "img, picture, source"))
    has_price = bool(_PRICE_SIGNAL.search(text))
    if _domain(surface) == "jobs":
        score += int(len(re.findall(r"\w+", text)) >= 3)
        score += int(bool(stable_card_identity(node, page_url=page_url)))
    else:
        score += int(has_media) + int(has_price)
        score += int(selector not in _GENERIC_SELECTORS)
    return score


def card_rejection_reason(
    node: Any,
    *,
    surface: object,
    page_url: str,
    selector: str,
) -> str | None:
    """Return the canonical rejection code, or ``None`` when admitted."""

    if _is_hidden(node):
        return "hidden"
    text = _text(node)
    if len(text) < 4:
        return "insufficient_text"
    url = _candidate_url(node, page_url=page_url)
    identity = stable_card_identity(node, page_url=page_url)
    if not identity:
        return "missing_identity"
    if url and listing_url_is_structural(url):
        return "structural_url"
    off_host_allowed = bool(getattr(surface, "off_host_records_allowed", False))
    if url and not off_host_allowed and not same_site(page_url, url):
        return "off_host_url"
    if _domain(surface) == "commerce" and selector in _GENERIC_SELECTORS:
        if not _css(node, "img, picture, source") and not _PRICE_SIGNAL.search(text):
            return "weak_generic_card"
    if card_quality_score(node, surface=surface, page_url=page_url, selector=selector) < 2:
        return "insufficient_quality"
    return None


def card_is_admitted(
    node: Any,
    *,
    surface: object,
    page_url: str,
    selector: str,
) -> bool:
    return card_rejection_reason(
        node, surface=surface, page_url=page_url, selector=selector
    ) is None


def select_listing_cards(
    document: Any,
    *,
    surface: object,
    page_url: str,
    limit: int | None = None,
) -> tuple[ListingCard, ...]:
    """Select admitted, identity-unique cards in selector/document order."""

    selected: list[ListingCard] = []
    seen_nodes: set[str] = set()
    seen_identities: set[str] = set()
    for selector in derive_card_selectors(surface):
        for index, node in enumerate(_css(document, selector)):
            node_key = _node_key(node)
            if node_key in seen_nodes:
                continue
            seen_nodes.add(node_key)
            reason = card_rejection_reason(
                node, surface=surface, page_url=page_url, selector=selector
            )
            if reason is not None:
                continue
            identity = stable_card_identity(node, page_url=page_url)
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
            selected.append(
                ListingCard(
                    node=node,
                    selector=selector,
                    selector_index=index,
                    identity=identity,
                    url=_candidate_url(node, page_url=page_url),
                    quality_score=card_quality_score(
                        node, surface=surface, page_url=page_url, selector=selector
                    ),
                )
            )
            if limit is not None and len(selected) >= max(0, int(limit)):
                return tuple(selected)
    return tuple(selected)


def unique_card_count(cards: Any) -> int:
    """Count stable unique identities from selected cards or identity strings."""

    return len(
        {
            str(getattr(card, "identity", card) or "").strip()
            for card in cards
            if str(getattr(card, "identity", card) or "").strip()
        }
    )


__all__ = [
    "ListingCard",
    "card_is_admitted",
    "card_quality_score",
    "card_rejection_reason",
    "derive_card_selectors",
    "select_listing_cards",
    "stable_card_identity",
    "stable_url_identity",
    "unique_card_count",
]
