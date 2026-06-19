from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from app.services.config.extraction_recipes import (
    ECOMMERCE_LISTING_CARD_SELECTORS,
    ECOMMERCE_LISTING_IMAGE_SELECTORS,
    ECOMMERCE_LISTING_PRICE_SELECTORS,
    ECOMMERCE_LISTING_TITLE_SELECTORS,
    ECOMMERCE_LISTING_URL_SELECTORS,
)
from app.services.config.extraction_rules import LISTING_UTILITY_URL_TOKENS
from app.services.extraction.collectors._helpers import evidence
from app.services.extraction.contracts import (
    ArtifactReader,
    CaptureBundle,
    CommerceListingRecord,
    Decision,
    EntityHint,
    Evidence,
    RejectedEvidence,
    SourceLocator,
)
from app.services.extraction.documents import HtmlDocument, HtmlNode
from app.services.extraction.ids import stable_id
from app.services.extraction.materialization import lineage
from app.services.extraction.surfaces import Surface
from app.services.url_identity import listing_url_is_structural


def collect_ecommerce_listing(
    bundle: CaptureBundle,
    reader: ArtifactReader,
) -> list[Evidence]:
    doc = reader.document_store.html("html")
    return _collect_listing_evidence(bundle, doc, page_url=bundle.final_url)


def resolve_ecommerce_listing(evidence_rows: list[Evidence]) -> list[Decision]:
    return _resolve_listing_decisions(evidence_rows)


def materialize_ecommerce_listing(
    evidence_rows: list[Evidence],
    decisions: list[Decision],
    *,
    max_records: int,
) -> list[CommerceListingRecord]:
    return [
        CommerceListingRecord.model_validate(row)
        for row in _materialize_listing_records(
            evidence_rows,
            decisions,
            max_records=max_records,
        )
    ]


def _collect_listing_evidence(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    *,
    page_url: str,
) -> list[Evidence]:
    rows: list[Evidence] = []
    seen_cards: set[str] = set()
    for selector in ECOMMERCE_LISTING_CARD_SELECTORS:
        for index, card in enumerate(doc.css(selector)):
            if card.is_hidden():
                continue
            card_key = card.html()
            if card_key in seen_cards:
                continue
            seen_cards.add(card_key)
            subject_id = stable_id("subject", bundle.bundle_id, "product", len(seen_cards))
            card_rows = _card_evidence(
                bundle,
                card,
                page_url=page_url,
                subject_id=subject_id,
                card_selector=selector,
                card_index=index,
            )
            if _has_required_listing_facts(card_rows):
                rows.extend(card_rows)
    return rows


def _card_evidence(
    bundle: CaptureBundle,
    card: HtmlNode,
    *,
    page_url: str,
    subject_id: str,
    card_selector: str,
    card_index: int,
) -> list[Evidence]:
    rows: list[Evidence] = []
    title = _first_text(card, ECOMMERCE_LISTING_TITLE_SELECTORS)
    url = _first_attr(card, ECOMMERCE_LISTING_URL_SELECTORS, "href")
    price = _first_price(card)
    image_url = _first_image(card)
    product_url = urljoin(page_url, url) if url else None
    if product_url and not _valid_listing_product_url(product_url, page_url):
        product_url = None
    absolute_image_url = urljoin(page_url, image_url) if image_url else None
    for fact_type, value, selector, confidence in (
        ("product.title", title, "title", 0.72),
        ("product.url", product_url, "url", 0.74),
        ("offer.price", price, "price", 0.62),
        ("asset.image_url", absolute_image_url, "image", 0.58),
    ):
        if not value:
            continue
        rows.append(
            _listing_evidence(
                bundle,
                fact_type=fact_type,
                value=value,
                subject_id=subject_id,
                locator=SourceLocator(
                    kind="css_selector",
                    value=f"{card_selector}:nth-match({card_index + 1}) {selector}",
                    preview=str(value)[:120],
                ),
                confidence=confidence,
            )
        )
    return rows


def _valid_listing_product_url(product_url: str, page_url: str) -> bool:
    product = urlparse(product_url)
    page = urlparse(page_url)
    return (
        product.scheme in {"http", "https"}
        and product.netloc.casefold() == page.netloc.casefold()
        and product.path not in {"", "/"}
        and not any(token in product.path.casefold() for token in LISTING_UTILITY_URL_TOKENS)
        and not listing_url_is_structural(product_url)
    )


def _listing_evidence(
    bundle: CaptureBundle,
    *,
    fact_type: str,
    value: object,
    subject_id: str,
    locator: SourceLocator,
    confidence: float,
) -> Evidence:
    entity_type = "offer" if fact_type.startswith("offer.") else "asset" if fact_type.startswith("asset.") else "product"
    return evidence(
        bundle,
        "html",
        "ecommerce_listing_css",
        fact_type,
        value,
        locator,
        group_id=subject_id,
        hint=EntityHint(entity_type=entity_type),  # type: ignore[arg-type]
        confidence=confidence,
    ).model_copy(
        update={
            "surface": Surface.ECOMMERCE_LISTING,
            "subject_id": subject_id,
            "parent_subject_id": None,
            "directness": "direct",
        }
    )


def _has_required_listing_facts(rows: list[Evidence]) -> bool:
    facts = {row.fact_type for row in rows}
    return "product.title" in facts and "product.url" in facts


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
                    decision_id=stable_id("decision", subject_id, fact_type, accepted.evidence_id),
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


def _materialize_listing_records(
    evidence_rows: list[Evidence],
    decisions: list[Decision],
    *,
    max_records: int,
) -> list[dict[str, Any]]:
    by_id = {row.evidence_id: row for row in evidence_rows}
    rows_by_subject: dict[str, dict[str, Any]] = {}
    lineage_by_subject: dict[str, dict[str, object]] = {}
    field_map = {
        "product.title": "title",
        "product.url": "url",
        "offer.price": "price",
        "asset.image_url": "image_url",
    }
    for decision in decisions:
        field = field_map.get(decision.fact_type)
        if not field or not decision.accepted_evidence_ids:
            continue
        accepted = by_id[decision.accepted_evidence_ids[0]]
        subject_id = accepted.subject_id or decision.entity_id
        rows_by_subject.setdefault(subject_id, {})[field] = accepted.value
        lineage_by_subject.setdefault(subject_id, {})[field] = lineage(decision=decision)
    materialized = []
    for subject_id, row in rows_by_subject.items():
        if not row.get("title") or not row.get("url"):
            continue
        row["_lineage"] = lineage_by_subject.get(subject_id, {})
        row["_subject_id"] = subject_id
        materialized.append(row)
    materialized.sort(key=lambda row: str(row.get("url") or ""))
    return materialized[:max_records]


def _first_text(card: HtmlNode, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        node = card.css_first(selector)
        if node is None or node.is_hidden():
            continue
        text = _clean_text(node.attribute("title") or node.text(separator=" ", strip=True))
        if text:
            return text
    return None


def _first_attr(card: HtmlNode, selectors: tuple[str, ...], attr: str) -> str | None:
    for selector in selectors:
        node = card.css_first(selector)
        if node is None or node.is_hidden():
            continue
        value = str(node.attribute(attr) or "").strip()
        if value:
            return value
    return None


def _first_image(card: HtmlNode) -> str | None:
    for selector in ECOMMERCE_LISTING_IMAGE_SELECTORS:
        node = card.css_first(selector)
        if node is None or node.is_hidden():
            continue
        value = node.attribute("src") or node.attribute("data-src") or node.attribute("srcset")
        if value:
            return str(value).split(",", 1)[0].strip().split(" ", 1)[0]
    return None


def _first_price(card: HtmlNode) -> str | None:
    for selector in ECOMMERCE_LISTING_PRICE_SELECTORS:
        node = card.css_first(selector)
        if node is None or node.is_hidden():
            continue
        value = node.attribute("data-price") or node.text(separator=" ", strip=True)
        price = _clean_price(value)
        if price:
            return price
    return None


def _clean_text(value: object) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def _clean_price(value: object) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    match = re.search(r"([$€£₹]?\s*\d[\d,]*(?:\.\d{1,2})?)", text)
    return match.group(1).replace(",", "").strip() if match else None
