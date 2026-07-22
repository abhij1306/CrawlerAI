from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urljoin

from app.core.config.extraction_recipes import (
    ECOMMERCE_LISTING_IMAGE_SELECTORS,
    ECOMMERCE_LISTING_PRICE_SELECTORS,
    ECOMMERCE_LISTING_TITLE_ATTRIBUTES,
    ECOMMERCE_LISTING_TITLE_SELECTORS,
    LISTING_HTML_ARTIFACT_IDS,
)
from app.core.listing_cards import select_listing_cards
from app.core.config.extraction_rules import (
    CURRENCY_SYMBOL_MAP,
    LISTING_VISUAL_PRICE_REGEX_PATTERN,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_TITLE_CONTROL_ATTRIBUTES,
    LISTING_TITLE_CONTROL_MARKERS,
    LISTING_TITLE_CTA_TITLES,
    LISTING_UTILITY_TITLE_PATTERNS,
    LISTING_WEAK_TITLES,
)
from app.extraction.collectors._helpers import evidence
from app.extraction.contracts import (
    ArtifactReader,
    CaptureBundle,
    Decision,
    EntityHint,
    Evidence,
    RejectedEvidence,
    SourceLocator,
)
from app.extraction.documents import HtmlDocument, HtmlNode
from app.core.shared.ids import stable_id
from app.extraction.surfaces import Surface, listing_schema

_LISTING_PRICE_SYMBOL_PATTERN = "|".join(
    re.escape(symbol) for symbol in sorted(CURRENCY_SYMBOL_MAP, key=len, reverse=True)
)


def collect_ecommerce_listing(
    bundle: CaptureBundle, reader: ArtifactReader
) -> list[Evidence]:
    rows: list[Evidence] = []
    for artifact_id in LISTING_HTML_ARTIFACT_IDS:
        if reader.exists(artifact_id):
            doc = reader.document_store.html(artifact_id)
            rows.extend(
                _collect_listing_evidence(bundle, doc, page_url=bundle.final_url)
            )
    return rows


def resolve_ecommerce_listing(evidence_rows: list[Evidence]) -> list[Decision]:
    return _resolve_listing_decisions(evidence_rows)


def _collect_listing_evidence(
    bundle: CaptureBundle, doc: HtmlDocument, *, page_url: str
) -> list[Evidence]:
    rows: list[Evidence] = []
    schema = listing_schema(Surface.ECOMMERCE_LISTING)
    if schema is None:
        return rows
    for position, candidate in enumerate(
        select_listing_cards(doc, surface=schema, page_url=page_url), start=1
    ):
        subject_id = stable_id(
            "subject", bundle.bundle_id, doc.artifact_id, "product", position
        )
        rows.extend(
            _card_evidence(
                bundle,
                candidate.node,
                page_url=page_url,
                subject_id=subject_id,
                card_selector=candidate.selector,
                card_index=candidate.selector_index,
                strong_card=candidate.quality_score >= 3,
                product_link=candidate.url_node,
                product_url=candidate.url,
            )
        )
    return rows


def _card_evidence(
    bundle: CaptureBundle,
    card: HtmlNode,
    *,
    page_url: str,
    subject_id: str,
    card_selector: str,
    card_index: int,
    strong_card: bool,
    product_link: HtmlNode | None,
    product_url: str,
) -> list[Evidence]:
    rows: list[Evidence] = []
    selector_price = _first_price(card)
    price = selector_price or _first_price(card, allow_text_scan=strong_card)
    image_url = _first_image(card)
    title = _listing_product_title(card, product_link) if product_url else None
    absolute_image_url = urljoin(page_url, image_url) if image_url else None
    for fact_type, value, selector, confidence in (
        ("product.title", title, "title", 0.72),
        ("product.url", product_url, "url", 0.74),
        ("offer.price", price, "price", 0.62),
        ("asset.image_url", absolute_image_url, "image", 0.58),
    ):
        if not value:
            continue
        locator = SourceLocator(
            kind="css_selector",
            value=f"{card_selector}:nth-match({card_index + 1}) {selector}",
            preview=str(value)[:120],
        )
        rows.append(
            _listing_evidence(
                bundle,
                artifact_id=card.artifact_id,
                fact_type=fact_type,
                value=value,
                subject_id=subject_id,
                locator=locator,
                confidence=confidence,
            )
        )
    return rows


def _listing_evidence(
    bundle: CaptureBundle,
    *,
    artifact_id: str,
    fact_type: str,
    value: object,
    subject_id: str,
    locator: SourceLocator,
    confidence: float,
) -> Evidence:
    entity_type: Literal["offer", "asset", "product"] = (
        "offer"
        if fact_type.startswith("offer.")
        else "asset"
        if fact_type.startswith("asset.")
        else "product"
    )
    row = evidence(
        bundle,
        artifact_id,
        "ecommerce_listing_css",
        fact_type,
        value,
        locator,
        group_id=subject_id,
        hint=EntityHint(entity_type=entity_type),
        confidence=confidence,
    )
    return row.model_copy(
        update={
            "surface": Surface.ECOMMERCE_LISTING,
            "subject_id": subject_id,
            "parent_subject_id": None,
            "directness": "direct",
        }
    )


def _resolve_listing_decisions(evidence_rows: list[Evidence]) -> list[Decision]:
    decisions: list[Decision] = []
    by_subject: dict[str, list[Evidence]] = {}
    for row in evidence_rows:
        if row.subject_id:
            by_subject.setdefault(row.subject_id, []).append(row)
    for subject_id, rows in by_subject.items():
        for fact_type in sorted({row.fact_type for row in rows}):
            candidates = sorted(
                [row for row in rows if row.fact_type == fact_type],
                key=lambda row: (-row.confidence, row.evidence_id),
            )
            if not candidates:
                continue
            accepted = candidates[0]
            rejected = tuple(
                RejectedEvidence(evidence_id=row.evidence_id, reason="lower_confidence")
                for row in candidates[1:]
            )
            decisions.append(
                Decision(
                    decision_id=stable_id(
                        "decision", subject_id, fact_type, accepted.evidence_id
                    ),
                    entity_id=subject_id,
                    fact_type=fact_type,
                    accepted_evidence_ids=(accepted.evidence_id,),
                    rejected=rejected,
                    finding_ids=(),
                    rule_id="css_listing_highest_confidence_v1",
                    status="resolved",
                )
            )
    return decisions


def _listing_product_title(card: HtmlNode, product_link: HtmlNode | None) -> str | None:
    if product_link is not None:
        link_title = _first_admissible_attribute(product_link)
        if _admissible_listing_title(link_title, product_link):
            return link_title
        nested = _first_admissible_text(product_link, ECOMMERCE_LISTING_TITLE_SELECTORS)
        if nested:
            return nested
        link_text = _clean_text(product_link.text(separator=" ", strip=True))
        if _admissible_listing_title(link_text, product_link):
            return link_text
    card_title = _first_admissible_attribute(card)
    if _admissible_listing_title(card_title, card):
        return card_title
    return _first_admissible_text(card, ECOMMERCE_LISTING_TITLE_SELECTORS)


def _first_admissible_attribute(node: HtmlNode) -> str | None:
    for attribute in ECOMMERCE_LISTING_TITLE_ATTRIBUTES:
        text = _clean_text(node.attribute(attribute))
        if _admissible_listing_title(text, node):
            return text
    return None


def _first_admissible_text(scope: HtmlNode, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        for node in scope.css(selector):
            if node.is_hidden():
                continue
            text = _clean_text(
                node.attribute("title") or node.text(separator=" ", strip=True)
            )
            if _admissible_listing_title(text, node):
                return text
    return None


def _admissible_listing_title(value: str | None, node: HtmlNode) -> bool:
    return not _title_node_is_control(node) and _admissible_listing_text(value)


def _admissible_listing_text(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.casefold().strip()
    if re.fullmatch(LISTING_VISUAL_PRICE_REGEX_PATTERN, value.strip(), re.IGNORECASE):
        return False
    rejected = (
        LISTING_TITLE_CTA_TITLES | LISTING_NAVIGATION_TITLE_HINTS | LISTING_WEAK_TITLES
    )
    return normalized not in rejected and not any(
        re.search(pattern, normalized) for pattern in LISTING_UTILITY_TITLE_PATTERNS
    )


def _title_node_is_control(node: HtmlNode) -> bool:
    if any(
        node.attribute(name) is not None for name in LISTING_TITLE_CONTROL_ATTRIBUTES
    ):
        return True
    attributes = " ".join(
        str(node.attribute(name) or "").casefold()
        for name in ("class", "data-testid", "id", "role")
    )
    return any(marker in attributes for marker in LISTING_TITLE_CONTROL_MARKERS)


def _first_image(card: HtmlNode) -> str | None:
    for selector in ECOMMERCE_LISTING_IMAGE_SELECTORS:
        node = card.css_first(selector)
        if node is None or node.is_hidden():
            continue
        value = (
            node.attribute("src")
            or node.attribute("data-src")
            or node.attribute("srcset")
        )
        if value:
            return str(value).split(",", 1)[0].strip().split(" ", 1)[0]
    return None


def _node_has_image(node: HtmlNode) -> bool:
    return any(
        node.css_first(selector) is not None
        for selector in ECOMMERCE_LISTING_IMAGE_SELECTORS
    )


def _link_has_title_signal(link: HtmlNode) -> bool:
    return bool(
        _first_admissible_attribute(link)
        or _first_admissible_text(link, ECOMMERCE_LISTING_TITLE_SELECTORS)
        or _admissible_listing_title(
            _clean_text(link.text(separator=" ", strip=True)),
            link,
        )
    )


def _first_price(card: HtmlNode, *, allow_text_scan: bool = False) -> str | None:
    for selector in ECOMMERCE_LISTING_PRICE_SELECTORS:
        node = card.css_first(selector)
        if node is None or node.is_hidden():
            continue
        value = node.attribute("data-price") or node.text(separator=" ", strip=True)
        price = _clean_price(value)
        if price:
            return price
    if allow_text_scan:
        return _clean_visual_price(card.text(separator=" ", strip=True))
    return None


def _clean_text(value: object) -> str | None:
    return re.sub(r"\s+", " ", str(value or "")).strip() or None


def _clean_price(value: object) -> str | None:
    if text := _clean_text(value):
        match = re.search(
            rf"((?:{_LISTING_PRICE_SYMBOL_PATTERN})?\s*\d[\d,]*(?:\.\d{{1,2}})?)",
            text,
        )
        return match.group(1).replace(",", "").strip() if match else None
    return None


def _clean_visual_price(value: object) -> str | None:
    if text := _clean_text(value):
        match = re.search(LISTING_VISUAL_PRICE_REGEX_PATTERN, text)
        return match.group(0).replace(",", "").strip() if match else None
    return None
