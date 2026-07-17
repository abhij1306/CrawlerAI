"""Pure, surface-aware listing-card selection primitives.

This module has no acquisition or extraction runtime dependencies. Both sides
pass the canonical ``SurfaceSpec``/``ListingSchema`` lens and DOM-like nodes
implementing the small HtmlDocument/HtmlNode interface used below.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

from app.core.config.cascade import (
    CASCADE_LISTING_ONCLICK_URL_PATTERN,
    CASCADE_LISTING_PRICE_SIGNAL_PATTERN,
    CASCADE_LISTING_RECORD_KEY_ATTRIBUTES,
    CASCADE_LISTING_RECORD_ONCLICK_ATTRIBUTES,
    CASCADE_LISTING_RECORD_URL_ATTRIBUTES,
    CASCADE_LISTING_VISUAL_RECORD_SIGNAL_SUFFIXES,
    CASCADE_READINESS_REJECTION_REASON_LIMIT,
    CASCADE_READINESS_REJECTION_SAMPLE_LIMIT,
)
from app.core.config.extraction_recipes import (
    LISTING_CARD_SELECTORS_BY_ROOT_ENTITY,
    LISTING_GENERIC_CARD_SELECTORS_BY_ROOT_ENTITY,
)
from app.core.config.extraction_rules import (
    LISTING_CARD_URL_ATTRS,
    LISTING_MARKET_LOCALE_GENDER_SEGMENTS,
    LISTING_MARKET_LOCALE_PRODUCT_PREFIX,
    LISTING_STRUCTURAL_CATEGORY_PATH_SEGMENTS,
    LISTING_UTILITY_URL_TOKENS,
)
from app.core.config.selectors import CARD_SELECTORS_BY_ROOT_ENTITY
from app.core.records.field_url_normalization import (
    same_site,
    strip_tracking_query_params,
)
from app.core.records.url_identity import (
    listing_detail_like_path,
    listing_url_is_structural,
)

_PRICE_SIGNAL = re.compile(CASCADE_LISTING_PRICE_SIGNAL_PATTERN, re.I)
_ONCLICK_URL = re.compile(CASCADE_LISTING_ONCLICK_URL_PATTERN)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ListingCard:
    """One admitted card and the shared facts used by every consumer."""

    node: Any
    selector: str
    selector_index: int
    identity: str
    url: str
    url_node: Any
    quality_score: int


@dataclass(frozen=True, slots=True)
class ListingCardRejectionSample:
    reason: str
    selector: str

    def as_dict(self) -> dict[str, str]:
        return {"reason": self.reason, "selector": self.selector}


@dataclass(frozen=True, slots=True)
class ListingCardDiagnostics:
    """Bounded discovery accounting shared by readiness and diagnose.v3."""

    card_count: int = 0
    admitted_count: int = 0
    rejected_count: int = 0
    rejection_reasons: tuple[tuple[str, int], ...] = ()
    rejection_samples: tuple[ListingCardRejectionSample, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "card_count": self.card_count,
            "admitted_count": self.admitted_count,
            "rejected_count": self.rejected_count,
            "rejection_reasons": dict(self.rejection_reasons),
            "rejection_samples": [row.as_dict() for row in self.rejection_samples],
        }

    @classmethod
    def from_mapping(cls, value: object) -> "ListingCardDiagnostics":
        if not isinstance(value, dict):
            return cls()

        def _count(raw: object) -> int:
            # Persisted diagnostics may carry legacy/malformed values ("unknown");
            # coerce defensively rather than crash the readiness read path.
            if raw is None or not isinstance(raw, (int, float, str)):
                return 0
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                return 0

        raw_reasons = value.get("rejection_reasons")
        reasons = (
            tuple(
                (str(reason), _count(count))
                for reason, count in list(raw_reasons.items())[
                    :CASCADE_READINESS_REJECTION_REASON_LIMIT
                ]
                if str(reason).strip()
            )
            if isinstance(raw_reasons, dict)
            else ()
        )
        raw_samples = value.get("rejection_samples")
        samples = tuple(
            ListingCardRejectionSample(
                reason=str(row.get("reason") or "")[:64],
                selector=str(row.get("selector") or "")[:120],
            )
            for row in (
                list(raw_samples)[:CASCADE_READINESS_REJECTION_SAMPLE_LIMIT]
                if isinstance(raw_samples, list)
                else []
            )
            if isinstance(row, dict) and str(row.get("reason") or "").strip()
        )
        return cls(
            card_count=_count(value.get("card_count")),
            admitted_count=_count(value.get("admitted_count")),
            rejected_count=_count(value.get("rejected_count")),
            rejection_reasons=reasons,
            rejection_samples=samples,
        )


@dataclass(frozen=True, slots=True)
class ListingCardSelection:
    cards: tuple[ListingCard, ...]
    diagnostics: ListingCardDiagnostics


def _root_entity(surface: object) -> str:
    return str(getattr(surface, "root_entity", "") or "").strip().lower()


def _uses_visual_evidence(surface: object) -> bool:
    return any(
        str(fact).endswith(CASCADE_LISTING_VISUAL_RECORD_SIGNAL_SUFFIXES)
        for fact in getattr(surface, "record_signal_facts", ()) or ()
    )


def derive_card_selectors(surface: object) -> tuple[str, ...]:
    """Return de-duplicated config-owned selectors for a surface lens."""

    root_entity = _root_entity(surface)
    extraction_selectors = LISTING_CARD_SELECTORS_BY_ROOT_ENTITY.get(root_entity, ())
    runtime_selectors = CARD_SELECTORS_BY_ROOT_ENTITY.get(root_entity, ())
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
        # Duck-typed nodes without identity/mem_id fall back to a content hash.
        logger.debug("listing card node identity unavailable; hashing html")
    return (
        "html:"
        + hashlib.sha1(_html(node).encode("utf-8"), usedforsecurity=False).hexdigest()
    )


def _is_hidden_self(node: Any) -> bool:
    try:
        method = getattr(node, "is_hidden", None)
        if callable(method) and method():
            return True
    except Exception:
        # Nodes without a working is_hidden() are judged by attributes below.
        logger.debug("listing card is_hidden probe failed; using attribute check")
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


def _raw_url_candidates(node: Any, *, page_url: str) -> tuple[tuple[Any, str], ...]:
    candidates: list[tuple[Any, str]] = []
    for candidate in _candidate_nodes(node):
        for attribute in (
            *LISTING_CARD_URL_ATTRS,
            *CASCADE_LISTING_RECORD_URL_ATTRIBUTES,
        ):
            value = _attribute(candidate, attribute)
            if value and not value.lower().startswith(
                ("#", "javascript:", "mailto:", "tel:")
            ):
                candidates.append((candidate, _resolve_listing_url(page_url, value)))
    for candidate in (node, *_css(node, "*")):
        for attribute in CASCADE_LISTING_RECORD_ONCLICK_ATTRIBUTES:
            if match := _ONCLICK_URL.search(_attribute(candidate, attribute)):
                candidates.append(
                    (candidate, _resolve_listing_url(page_url, match.group(1)))
                )
    return tuple(candidates)


def canonical_record_url(
    node: Any,
    *,
    surface: object,
    page_url: str,
) -> tuple[Any | None, str]:
    """Select the one admissible record URL shared by all card consumers."""

    ranked: list[tuple[int, int, Any, str]] = []
    for index, (candidate, url) in enumerate(
        _raw_url_candidates(node, page_url=page_url)
    ):
        if not _record_url_is_admissible(url, surface=surface, page_url=page_url):
            continue
        rank = int(listing_detail_like_path(url)) * 2 + int(
            bool(_css(candidate, "img, picture, source"))
        )
        ranked.append((rank, -index, candidate, canonicalize_identity_url(url)))
    if not ranked:
        return None, ""
    _, _, candidate, url = max(ranked, key=lambda item: item[:2])
    return candidate, url


def _resolve_listing_url(page_url: str, raw_url: str) -> str:
    resolved = urljoin(page_url, raw_url)
    page = urlparse(page_url)
    candidate = urlparse(resolved)
    if not raw_url.strip() or not same_site(page_url, resolved):
        return resolved
    page_parts = _path_parts(page.path)
    candidate_parts = _path_parts(candidate.path)
    category_index = next(
        (
            index
            for index, part in enumerate(page_parts)
            if part.casefold() in LISTING_STRUCTURAL_CATEGORY_PATH_SEGMENTS
        ),
        None,
    )
    if category_index is None:
        return resolved
    market_prefix = page_parts[:category_index]
    if not market_prefix or candidate_parts[: len(market_prefix)] == market_prefix:
        return resolved
    first = candidate_parts[0].casefold() if candidate_parts else ""
    if first == LISTING_MARKET_LOCALE_PRODUCT_PREFIX:
        restored = (*market_prefix, *candidate_parts)
    elif first in LISTING_MARKET_LOCALE_GENDER_SEGMENTS and _probable_product_slug(
        candidate_parts[-1] if candidate_parts else ""
    ):
        restored = (
            *market_prefix,
            LISTING_MARKET_LOCALE_PRODUCT_PREFIX,
            *candidate_parts,
        )
    else:
        return resolved
    return urlunparse(candidate._replace(path="/" + "/".join(restored)))


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in path.split("/") if part)


def _probable_product_slug(value: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    return bool(tokens and any(char.isdigit() for char in value) and len(tokens) >= 3)


def _listing_url_has_category_segment(url: str) -> bool:
    return any(
        part.casefold() in LISTING_STRUCTURAL_CATEGORY_PATH_SEGMENTS
        for part in _path_parts(urlparse(url).path)
    )


def _record_url_is_admissible(
    url: str,
    *,
    surface: object,
    page_url: str,
) -> bool:
    parsed = urlparse(url)
    page = urlparse(page_url)
    if parsed.scheme not in {"http", "https"} or parsed.path in {"", "/"}:
        return False
    if parsed.path.rstrip("/") == page.path.rstrip("/") and parsed.query == page.query:
        return False
    if not bool(getattr(surface, "off_host_records_allowed", False)) and not same_site(
        page_url, url
    ):
        return False
    if listing_url_is_structural(url):
        return False
    if _uses_visual_evidence(surface):
        if any(token in parsed.path.casefold() for token in LISTING_UTILITY_URL_TOKENS):
            return False
        if _listing_url_has_category_segment(url) and not listing_detail_like_path(url):
            return False
    return True


def stable_card_identity(node: Any, *, surface: object, page_url: str) -> str:
    """Return stable URL identity, then configured record key, then no identity."""

    _, url = canonical_record_url(node, surface=surface, page_url=page_url)
    identity = stable_url_identity(url)
    if identity:
        return identity
    for candidate in (node, *_css(node, "*")):
        for attribute in CASCADE_LISTING_RECORD_KEY_ATTRIBUTES:
            if value := _attribute(candidate, attribute):
                return f"key:{attribute}={value.casefold()}"
    return ""


def canonicalize_identity_url(url: str) -> str:
    """Strip configured tracking parameters and deterministically order the rest."""

    cleaned = strip_tracking_query_params(url) or str(url or "").strip()
    parsed = urlparse(cleaned)
    query = urlencode(
        sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True
    )
    return urlunparse(parsed._replace(query=query, fragment=""))


def stable_url_identity(url: str) -> str:
    """Canonical case-folded URL identity used across card sources."""

    parsed = urlparse(canonicalize_identity_url(url))
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
    _, url = canonical_record_url(node, surface=surface, page_url=page_url)
    score = int(bool(url)) + int(len(re.findall(r"\w+", text)) >= 2)
    has_media = bool(_css(node, "img, picture, source"))
    has_price = bool(_PRICE_SIGNAL.search(text))
    if not _uses_visual_evidence(surface):
        score += int(len(re.findall(r"\w+", text)) >= 3)
        score += int(
            bool(stable_card_identity(node, surface=surface, page_url=page_url))
        )
    else:
        score += int(has_media) + int(has_price)
        generic_selectors = LISTING_GENERIC_CARD_SELECTORS_BY_ROOT_ENTITY.get(
            _root_entity(surface), frozenset()
        )
        score += int(selector not in generic_selectors)
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
    _, url = canonical_record_url(node, surface=surface, page_url=page_url)
    identity = stable_card_identity(node, surface=surface, page_url=page_url)
    if not identity:
        return "missing_identity"
    generic_selectors = LISTING_GENERIC_CARD_SELECTORS_BY_ROOT_ENTITY.get(
        _root_entity(surface), frozenset()
    )
    if _uses_visual_evidence(surface) and selector in generic_selectors:
        if not _css(node, "img, picture, source") and not _PRICE_SIGNAL.search(text):
            return "weak_generic_card"
    if (
        card_quality_score(node, surface=surface, page_url=page_url, selector=selector)
        < 2
    ):
        return "insufficient_quality"
    return None


def card_is_admitted(
    node: Any,
    *,
    surface: object,
    page_url: str,
    selector: str,
) -> bool:
    return (
        card_rejection_reason(
            node, surface=surface, page_url=page_url, selector=selector
        )
        is None
    )


def select_listing_cards(
    document: Any,
    *,
    surface: object,
    page_url: str,
    limit: int | None = None,
) -> tuple[ListingCard, ...]:
    """Select admitted, identity-unique cards in selector/document order."""

    return select_listing_cards_with_diagnostics(
        document,
        surface=surface,
        page_url=page_url,
        limit=limit,
    ).cards


def select_listing_cards_with_diagnostics(
    document: Any,
    *,
    surface: object,
    page_url: str,
    limit: int | None = None,
) -> ListingCardSelection:
    """Select cards and account for every unique candidate exactly once."""

    selected: list[ListingCard] = []
    seen_nodes: set[str] = set()
    seen_identities: set[str] = set()
    rejected = Counter[str]()
    samples: list[ListingCardRejectionSample] = []

    def reject(reason: str, selector: str) -> None:
        rejected[reason] += 1
        if len(samples) < CASCADE_READINESS_REJECTION_SAMPLE_LIMIT:
            samples.append(
                ListingCardRejectionSample(reason=reason, selector=selector[:120])
            )

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
                reject(reason, selector)
                continue
            url_node, url = canonical_record_url(
                node, surface=surface, page_url=page_url
            )
            identity = stable_url_identity(url) or stable_card_identity(
                node, surface=surface, page_url=page_url
            )
            if identity in seen_identities:
                reject("duplicate_identity", selector)
                continue
            seen_identities.add(identity)
            selected.append(
                ListingCard(
                    node=node,
                    selector=selector,
                    selector_index=index,
                    identity=identity,
                    url=url,
                    url_node=url_node,
                    quality_score=card_quality_score(
                        node, surface=surface, page_url=page_url, selector=selector
                    ),
                )
            )
            if limit is not None and len(selected) >= max(0, int(limit)):
                return _card_selection(selected, rejected, samples)
    return _card_selection(selected, rejected, samples)


def _card_selection(
    selected: list[ListingCard],
    rejected: Counter[str],
    samples: list[ListingCardRejectionSample],
) -> ListingCardSelection:
    reasons = tuple(
        sorted(rejected.items(), key=lambda item: (-item[1], item[0]))[
            :CASCADE_READINESS_REJECTION_REASON_LIMIT
        ]
    )
    return ListingCardSelection(
        cards=tuple(selected),
        diagnostics=ListingCardDiagnostics(
            card_count=len(selected),
            admitted_count=len(selected),
            rejected_count=sum(rejected.values()),
            rejection_reasons=reasons,
            rejection_samples=tuple(samples),
        ),
    )


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
    "ListingCardDiagnostics",
    "ListingCardRejectionSample",
    "ListingCardSelection",
    "card_is_admitted",
    "card_quality_score",
    "card_rejection_reason",
    "canonical_record_url",
    "canonicalize_identity_url",
    "derive_card_selectors",
    "select_listing_cards",
    "select_listing_cards_with_diagnostics",
    "stable_card_identity",
    "stable_url_identity",
    "unique_card_count",
]
