"""Structural, site-independent listing record-boundary discovery.

Slice 4.2 of the extraction-v3 plan. This module answers the single question
"where are the N product records on this listing page?" **without any hardcoded
selectors, per-platform branches, or per-markup-shape recognizers.** It is the
generic record spine that Tier 0 (structured floor) and Tier 2 (generalized
exemplar LLM) resolve fields against.

The algorithm rests on two invariants that hold across markup shapes (cards,
``ItemList``, bare anchor grids) and are independent of any site's class names:

1. **Detail-URL identity is the anchor.** A product reference is, at minimum, a
   same-site link whose URL looks like a product detail page (not a category /
   nav / utility URL). ``detail_url_looks_like_product`` + ``listing_url_is_structural``
   are the generic filter; class names are never consulted.

2. **Records are the repeated, homogeneous sibling subtree.** A listing is N
   near-identical containers. For each product link we walk up to the *largest*
   ancestor that still encloses exactly one product identity — that ancestor is
   the record container. The containers that share a parent and a structural
   shape (tag-path signature) and appear >= a small threshold number of times
   are the real records; one-off subtrees (a single promo tile, a nav block)
   fall out because they don't repeat.

Output is an ordered tuple of ``RecordBoundary`` — the record subtree plus its
detail URL and a stable index — consumed by deterministic listing mapping.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlparse

from app.core.config.cascade import (
    CASCADE_LISTING_MIN_REPEATED_RECORDS,
    CASCADE_LISTING_ONCLICK_URL_PATTERN,
    CASCADE_LISTING_PRICE_SIGNAL_PATTERN,
    CASCADE_LISTING_RECORD_KEY_ATTRIBUTES,
    CASCADE_LISTING_RECORD_MIN_TEXT_TOKENS,
    CASCADE_LISTING_RECORD_ONCLICK_ATTRIBUTES,
    CASCADE_LISTING_RECORD_URL_ATTRIBUTES,
    CASCADE_LISTING_VISUAL_RECORD_SIGNAL_SUFFIXES,
)
from app.core.records.field_url_normalization import same_site
from app.core.records.url_identity import listing_url_is_structural
from app.extraction.documents import HtmlDocument, HtmlNode
from app.extraction.surfaces import ListingSchema

# The default (commerce) price signal: a currency symbol or code in the
# container's text marks a product record apart from a bare nav link. The
# pattern lives in ``app.core.config.cascade`` (config owns tunable patterns).
_PRICE_SIGNAL = re.compile(CASCADE_LISTING_PRICE_SIGNAL_PATTERN, re.I)
_ONCLICK_URL = re.compile(CASCADE_LISTING_ONCLICK_URL_PATTERN)


def _has_min_text_tokens(node: HtmlNode) -> bool:
    """True when a node's text carries at least the configured word floor.

    Shared token-count floor used by both the non-visual (job) record signal
    and the anchor-less richness check, so the threshold is applied once.
    """
    return (
        len(re.findall(r"\w+", node.content_text()))
        >= CASCADE_LISTING_RECORD_MIN_TEXT_TOKENS
    )


def _is_visually_hidden(node: HtmlNode) -> bool:
    """True only for genuinely non-rendered nodes (hidden attr / display:none).

    Unlike ``HtmlNode.is_hidden()``, this ignores ``aria-hidden`` — that marks
    accessibility-tree exclusion, not visual hiding, and is routinely set on
    real product links inside role="button" cards.
    """
    if node.attribute("hidden") is not None:
        return True
    style = (node.attribute("style") or "").replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style


def _is_content_rich(node: HtmlNode) -> bool:
    """A record has media/price, or a text-bearing detail link.

    Site-independent: checks for the *presence* of an ``<img>`` (or lazy-image
    ``<source>``) or a currency signal in the subtree text — never class names.

    This is the default (commerce) record-signal: image-or-price. It is passed
    as the ``record_signal`` default so a later, schema-driven slice (jobs) can
    supply a signal that does not require image/price without editing discovery.
    """
    if node.css_first("img") is not None or node.css_first("source") is not None:
        return True
    text = node.content_text()
    if _PRICE_SIGNAL.search(text):
        return True
    return bool(len(node.css("a[href]")) == 1 and len(re.findall(r"\w+", text)) >= 3)


def _is_text_record(node: HtmlNode) -> bool:
    """A non-visual (job) record signal: a text-bearing detail link, no price/image.

    De-commerces discovery: a job card has no ``<img>``/price but does carry a
    detail link (already filtered to a real posting URL by ``_product_anchors``)
    and enough descriptive text (title + location/company) to be a real posting
    rather than a bare nav chip. Site-independent — never consults class names.
    """
    if not node.css("a[href]"):
        return False
    return _has_min_text_tokens(node)


def _schema_wants_visual_signal(schema: ListingSchema) -> bool:
    """True when a schema's record signals are visual (image/price) — commerce.

    Declarative: reads ``ListingSchema.record_signal_facts`` and asks whether any
    is an image/price fact (suffix table in config). Commerce
    (``asset.image_url`` / ``offer.price``) is visual; jobs
    (``job.location`` / ``job.company`` / ``job.apply_url``) are not.
    """
    return any(
        fact.endswith(CASCADE_LISTING_VISUAL_RECORD_SIGNAL_SUFFIXES)
        for fact in schema.record_signal_facts
    )


def record_signal_for_schema(schema: ListingSchema | None) -> RecordSignal | None:
    """Build the record-signal callable a schema implies, or ``None`` for default.

    Returns ``None`` for the commerce (visual) schema so discovery keeps its
    default image-or-price ``_is_content_rich`` signal; returns the non-visual
    text-and-detail-link signal for job listings. This is the single schema →
    signal seam so no caller re-forks on ``surface ==``.
    """
    if schema is None or _schema_wants_visual_signal(schema):
        return None
    return _is_text_record


def record_key_attributes_for_schema(schema: ListingSchema | None) -> tuple[str, ...]:
    """Record-local identity attributes for anchor-less discovery, by schema.

    Only non-visual (job) schemas admit anchor-less JS-onclick cards, so commerce
    gets an empty tuple and its anchor-gated behaviour is unchanged.
    """
    if schema is None or _schema_wants_visual_signal(schema):
        return ()
    return CASCADE_LISTING_RECORD_KEY_ATTRIBUTES


def _link_identity(url: str) -> str:
    """Generic same-document identity for a link: casefolded ``host+path``.

    Deliberately does NOT require a product-URL marker (``/product/`` etc.).
    Requiring positive markers is per-site URL enumeration — the exact
    brittleness this module removes; firstcry products live at
    ``/<brand>/<slug>-detail`` with no marker. Instead we compute a neutral
    identity for every non-structural link and let structural repetition +
    homogeneity discriminate products from noise. Returns "" for links with no
    meaningful path (site root) so they can't seed a record.
    """
    parsed = urlparse(str(url or "").strip())
    host = str(parsed.hostname or "").casefold().strip(".")
    path = unquote(parsed.path).casefold().rstrip("/")
    if not host or not path or path == "":
        return ""
    return f"{host}{path}"


# A group of structurally-identical sibling subtrees must appear at least this
# many times to be treated as the page's record set. The threshold lives in
# ``app.core.config.cascade`` (repo invariant: thresholds are config, not code)
# and is currently 2 — enough to establish repetition while still rejecting a
# lone promo/nav subtree; a real listing has far more. Kept low so short result
# pages (a 2-item search result) still work.
_MIN_REPEATED_RECORDS = CASCADE_LISTING_MIN_REPEATED_RECORDS

# Type of the pluggable record-signal predicate. Discovery defaults to the
# commerce image-or-price signal (``_is_content_rich``); a later job-listing
# slice supplies a schema-driven signal here without touching this module.
RecordSignal = Callable[[HtmlNode], bool]


@dataclass(frozen=True)
class _Container:
    """Internal: a discovered record container with its document-order rank."""

    node: HtmlNode
    url: str
    identity: str
    order: int


@dataclass(frozen=True)
class RecordBoundary:
    """One discovered product record on the listing page.

    ``node`` is the record container subtree (fields are resolved within it).
    ``url`` is the absolute detail URL that anchors the record's identity.
    ``identity`` is ``_link_identity(url)`` (casefolded host+path) — the
    cross-source join key. ``index`` is the record's document-order position.
    """

    node: HtmlNode
    url: str
    identity: str
    index: int


def discover_listing_records(
    doc: HtmlDocument,
    *,
    page_url: str,
    allow_singleton: bool = False,
    record_signal: RecordSignal | None = None,
    off_host_allowed: bool = False,
    record_key_attributes: tuple[str, ...] = (),
) -> tuple[RecordBoundary, ...]:
    """Return the page's product records by structural repetition.

    Site-independent: consults URL shape and DOM structure only, never class
    names or per-platform selectors. Returns records in document order.

    ``record_signal`` decides whether a candidate container is content-rich
    enough to be a record. It defaults to the commerce image-or-price signal;
    a later schema-driven slice supplies a different one for job listings.

    ``off_host_allowed`` (job listings) lets the singleton path accept a
    consistent foreign host (an off-host ATS apply link); commerce leaves it
    False so a singleton must be same-site. ``record_key_attributes`` (job
    listings) admits anchor-less JS-onclick cards keyed on a stable data-*/id
    token; empty for commerce so anchor-gated behaviour is unchanged.
    """
    signal = record_signal or _is_content_rich
    # The word-count text-card fallback below is a commerce-era relaxation that
    # can admit cards the signal rejected; honoured ONLY for the default signal,
    # so a stricter caller-supplied signal (a future job slice) is never bypassed.
    allow_text_card_fallback = record_signal is None
    anchors = _product_anchors(doc, page_url=page_url)
    if not anchors:
        return _anchorless_records(
            doc,
            page_url=page_url,
            record_key_attributes=record_key_attributes,
        )

    # Top-down grid detection. For every product anchor, register the pair
    # (parent, the parent's direct child on the path to the anchor). The record
    # "grid" is the parent that has the most distinct record-children; each such
    # child is one product record. This is robust to variant-rich cards (a card
    # holding 6 colour-swatch links to 6 URLs still registers as ONE child of
    # the grid) — bottom-up climbing shattered those cards, top-down does not.
    grids: dict[int, _GridParent] = {}
    for order, (anchor, url, identity) in enumerate(anchors):
        chain = (anchor,) + anchor.ancestors()
        for depth in range(len(chain) - 1):
            child = chain[depth]
            parent = chain[depth + 1]
            parent_tag = parent.tag()
            if parent_tag in {"html", "head"}:
                break
            parent_key = parent.identity()
            grid = grids.get(parent_key)
            if grid is None:
                grid = _GridParent(node=parent)
                grids[parent_key] = grid
            grid.add_child(child, url=url, identity=identity, order=order)

    kept = _best_grid_children(
        grids,
        page_url=page_url,
        allow_singleton=allow_singleton,
        record_signal=signal,
        allow_text_card_fallback=allow_text_card_fallback,
        off_host_allowed=off_host_allowed,
    )
    if not kept:
        return ()

    boundaries: list[RecordBoundary] = []
    for index, item in enumerate(kept):
        boundaries.append(
            RecordBoundary(
                node=item.node, url=item.url, identity=item.identity, index=index
            )
        )
    return tuple(boundaries)


def accepted_network_listing_subject_count(evidence) -> int:
    return len(
        {
            row.subject_id
            for row in evidence
            if row.collector_id == "network_listing_floor"
            and row.fact_type.endswith((".title", ".url"))
        }
    )


def _product_anchors(
    doc: HtmlDocument, *, page_url: str
) -> tuple[tuple[HtmlNode, str, str], ...]:
    """Every same-site anchor whose URL is a product detail identity.

    This is the generic noise filter: category/nav/utility URLs return an empty
    identity and are skipped, so a nav menu of links never enters discovery.
    Deduplicated by identity, keeping the first (document-order) anchor.
    """
    found: list[tuple[HtmlNode, str, str]] = []
    seen_identities: set[str] = set()
    for anchor in doc.css("a[href]"):
        # Only skip *visually* hidden anchors (display:none / hidden attr). NOT
        # aria-hidden: a common card pattern wraps the product in a
        # role="button" element and marks the inner <a aria-hidden="true">, which
        # is still the real, visible product link. ``is_hidden()`` treats
        # aria-hidden as hidden, so we use a narrower visual check here.
        if _is_visually_hidden(anchor):
            continue
        if any(
            node.tag() in {"header", "footer", "nav"} for node in anchor.ancestors()
        ):
            continue
        href = (anchor.attribute("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(page_url, href)
        # Reject only clearly-structural URLs (category/nav/utility). We do NOT
        # require a positive product marker — that would be per-site URL
        # enumeration. Structural repetition below is the real discriminator.
        if listing_url_is_structural(url):
            continue
        identity = _link_identity(url)
        if not identity or identity in seen_identities:
            continue
        seen_identities.add(identity)
        found.append((anchor, url, identity))
    return tuple(found)


class _GridParent:
    """A candidate record grid: a parent DOM node and its record-children.

    Each *child* is one direct child of the parent that lies on the path to at
    least one product anchor. A child holds its first-seen product url/identity
    and document order. A grid's strength is how many distinct record-children
    it has — the true product grid maximises this.
    """

    __slots__ = ("node", "_children", "_child_order")

    def __init__(self, node: HtmlNode) -> None:
        self.node = node
        self._children: dict[int, _Container] = {}
        self._child_order: int = 0

    def add_child(
        self, child: HtmlNode, *, url: str, identity: str, order: int
    ) -> None:
        key = child.identity()
        if key in self._children:
            return
        self._children[key] = _Container(
            node=child, url=url, identity=identity, order=order
        )

    def children(self) -> list[_Container]:
        return sorted(self._children.values(), key=lambda item: item.order)


def _best_grid_children(
    grids: dict[int, _GridParent],
    *,
    page_url: str,
    allow_singleton: bool = False,
    record_signal: RecordSignal,
    allow_text_card_fallback: bool = True,
    off_host_allowed: bool = False,
) -> list[_Container]:
    """Pick the grid whose direct children are the product record set.

    Selection is by (a) number of distinct content-rich record children, then
    (b) structural homogeneity of those children. The winning grid's children,
    filtered to the content-rich ones, are the records. Content-richness
    (image or price in the child subtree) rejects a nav container whose children
    are bare links even when it has many of them.
    """
    scored: list[tuple[int, int, list[_Container]]] = []
    for grid in grids.values():
        rich = [c for c in grid.children() if record_signal(c.node)]
        if allow_text_card_fallback and len(rich) < _MIN_REPEATED_RECORDS:
            text_cards = [
                child
                for child in grid.children()
                if len(re.findall(r"\w+", child.node.content_text())) >= 3
            ]
            if _homogeneity_score(text_cards) >= _MIN_REPEATED_RECORDS:
                rich = text_cards
        if len(rich) < _MIN_REPEATED_RECORDS:
            continue
        if not _consistent_record_host(rich, page_url=page_url):
            continue
        homogeneity = _homogeneity_score(rich)
        scored.append((len(rich), homogeneity, rich))

    if not scored and allow_singleton:
        # A structured-corroborated singleton must still anchor to a consistent
        # host. Commerce (off_host_allowed=False) keeps the strict same-site
        # requirement; job listings (off_host_allowed=True) accept a foreign ATS
        # host (Greenhouse/Lever/Bullhorn apply link) because a real posting
        # often links off-site. Threaded from the schema's off_host flag — not a
        # ``surface ==`` branch.
        singletons = [
            child
            for grid in grids.values()
            for child in grid.children()
            if record_signal(child.node)
            and (off_host_allowed or same_site(page_url, child.url))
        ]
        singletons.sort(key=lambda item: item.order)
        return singletons[:1]
    if not scored:
        # A lone content-rich link is more often navigation, a promotion, or a
        # footer card than a listing record.  A one-item listing can still be
        # admitted by a structured source, but DOM-only discovery needs the
        # structural repetition proof.
        return []

    # Prefer most record-children; break ties toward the more homogeneous grid.
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return scored[0][2]


def _consistent_record_host(children: list[_Container], *, page_url: str) -> bool:
    page_host = (urlparse(page_url).hostname or "").casefold()
    hosts = {(urlparse(child.url).hostname or "").casefold() for child in children}
    return bool(hosts) and (hosts == {page_host} or len(hosts) == 1)


def _record_local_key(node: HtmlNode, key_attributes: tuple[str, ...]) -> str:
    """Stable per-record identity from a data-*/id token, or "" when absent.

    Used only for anchor-less discovery (JS-onclick cards with no ``<a href>``).
    The attribute list is schema/config-supplied so this never hardcodes a
    site-specific attribute.
    """
    for attribute in key_attributes:
        value = (node.attribute(attribute) or "").strip()
        if value:
            return f"{attribute}={value.casefold()}"
    return ""


def _recover_record_url(node: HtmlNode, *, page_url: str) -> str:
    """Recover an anchor-less card's detail URL from its navigation affordance.

    An anchor-less JS card navigates via a handler or a data-* URL payload
    rather than an ``<a href>``. This recovers that target so the card can
    publish a real detail URL: a direct URL attribute (``data-href`` etc.) or a
    quoted path/URL embedded in an ``onclick`` handler, on the card itself or on
    a descendant. Returns an absolute URL, or "" when no navigation target
    exists — in which case the card is NOT a record (it is a bare tile). Never
    consults class names or per-site routes.
    """
    candidates = (node, *node.css("*"))
    for candidate in candidates:
        for attribute in CASCADE_LISTING_RECORD_URL_ATTRIBUTES:
            value = (candidate.attribute(attribute) or "").strip()
            if value:
                return urljoin(page_url, value)
    for candidate in candidates:
        for attribute in CASCADE_LISTING_RECORD_ONCLICK_ATTRIBUTES:
            handler = candidate.attribute(attribute) or ""
            match = _ONCLICK_URL.search(handler)
            if match:
                return urljoin(page_url, match.group(1))
    return ""


def _anchorless_records(
    doc: HtmlDocument,
    *,
    page_url: str,
    record_key_attributes: tuple[str, ...],
) -> tuple[RecordBoundary, ...]:
    """Admit repeated anchor-less JS-onclick cards keyed on a record-local token.

    Only runs when no ``<a href>`` product anchor was found AND the schema
    supplies ``record_key_attributes`` (jobs). A card qualifies only when a real
    detail URL can be recovered from its navigation affordance (a data-* URL
    payload or an ``onclick`` handler target) AND that URL is not a structural
    hub/category link — a bare id/data-testid tile with no navigation target (a
    department/category tile) is NOT a record and is dropped. The surviving
    cards must share a parent, carry a distinct record-local key, repeat at
    least ``_MIN_REPEATED_RECORDS`` times, be text-rich, and be structurally
    homogeneous. Commerce passes an empty attribute tuple, so this path is inert
    for commerce and cannot destabilise its anchor grids.
    """
    if not record_key_attributes:
        return ()
    grids: dict[int, list[_Container]] = defaultdict(list)
    seen_keys: set[str] = set()
    order = 0
    for node in doc.css("*"):
        key = _record_local_key(node, record_key_attributes)
        if not key or key in seen_keys or _is_visually_hidden(node):
            continue
        parent = node.parent()
        if parent is None or parent.tag() in {"html", "head", "body"}:
            continue
        if any(
            ancestor.tag() in {"header", "footer", "nav"}
            for ancestor in node.ancestors()
        ):
            continue
        # A record must expose a recoverable, non-structural detail URL. A tile
        # with only a generic id and no navigation affordance is not a posting.
        url = _recover_record_url(node, page_url=page_url)
        if not url or listing_url_is_structural(url):
            continue
        seen_keys.add(key)
        grids[parent.identity()].append(
            _Container(node=node, url=url, identity=_link_identity(url), order=order)
        )
        order += 1

    best: list[_Container] = []
    for members in grids.values():
        rich = [item for item in members if _has_min_text_tokens(item.node)]
        if len(rich) < _MIN_REPEATED_RECORDS:
            continue
        if _homogeneity_score(rich) < _MIN_REPEATED_RECORDS:
            continue
        if len(rich) > len(best):
            best = rich
    if not best:
        return ()
    best.sort(key=lambda item: item.order)
    return tuple(
        RecordBoundary(
            node=item.node, url=item.url, identity=item.identity, index=index
        )
        for index, item in enumerate(best)
    )


def _homogeneity_score(children: list[_Container]) -> int:
    """Size of the largest structurally-identical subset of ``children``.

    A real product grid's children share a structural signature; a container
    that merely happens to hold several product links (e.g. a mixed sidebar)
    scores low. Used only as a tie-breaker between grids of equal child count.
    """
    counts: dict[str, int] = defaultdict(int)
    for child in children:
        counts[_structural_signature(child.node)] += 1
    return max(counts.values()) if counts else 0


def _structural_signature(node: HtmlNode) -> str:
    """A shape fingerprint independent of class names / text / ids.

    Two record containers of the same listing share this signature even when
    their per-item classes differ (e.g. a "sponsored" variant tile). Built from
    the tag topology of the subtree (bounded depth) so it is cheap and stable.
    """
    parts: list[str] = []

    def walk(current: HtmlNode, depth: int) -> None:
        if depth > 3:
            return
        children = current.child_elements()
        tags = ",".join(sorted(child.tag() for child in children if child.tag()))
        parts.append(f"{depth}:{current.tag()}[{tags}]")
        for child in children:
            walk(child, depth + 1)

    walk(node, 0)
    return "|".join(parts)
