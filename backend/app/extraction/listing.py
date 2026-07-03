from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urljoin, urlparse, urlunparse

from app.core.config.extraction_recipes import (
    ECOMMERCE_LISTING_CARD_SELECTORS,
    ECOMMERCE_LISTING_GENERIC_CARD_SELECTORS,
    ECOMMERCE_LISTING_HTML_ARTIFACT_IDS,
    ECOMMERCE_LISTING_IMAGE_SELECTORS,
    ECOMMERCE_LISTING_PRICE_SELECTORS,
    ECOMMERCE_LISTING_SCOPE_SELECTORS,
    ECOMMERCE_LISTING_TITLE_ATTRIBUTES,
    ECOMMERCE_LISTING_TITLE_SELECTORS,
    ECOMMERCE_LISTING_URL_SELECTORS,
)
from app.core.config.extraction_rules import (
    CURRENCY_SYMBOL_MAP,
    LISTING_VISUAL_PRICE_REGEX_PATTERN,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_TITLE_CONTROL_ATTRIBUTES,
    LISTING_TITLE_CONTROL_MARKERS,
    LISTING_TITLE_CTA_TITLES,
    LISTING_UTILITY_TITLE_PATTERNS,
    LISTING_UTILITY_URL_TOKENS,
    LISTING_WEAK_TITLES,
    LISTING_MARKET_LOCALE_GENDER_SEGMENTS,
    LISTING_MARKET_LOCALE_PRODUCT_PREFIX,
    LISTING_STRUCTURAL_CATEGORY_PATH_SEGMENTS,
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
from app.extraction.surfaces import Surface
from app.core.records.field_url_normalization import same_site
from app.core.records.url_identity import (
    listing_detail_like_path,
    listing_url_is_structural,
)

_LISTING_PRICE_SYMBOL_PATTERN = "|".join(
    re.escape(symbol) for symbol in sorted(CURRENCY_SYMBOL_MAP, key=len, reverse=True)
)


def collect_ecommerce_listing(
    bundle: CaptureBundle, reader: ArtifactReader
) -> list[Evidence]:
    rows: list[Evidence] = []
    for artifact_id in ECOMMERCE_LISTING_HTML_ARTIFACT_IDS:
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
    seen_cards: set[str] = set()
    scopes = tuple(
        node
        for selector in ECOMMERCE_LISTING_SCOPE_SELECTORS
        for node in doc.safe_css(selector)
    ) or (doc,)
    for selector in ECOMMERCE_LISTING_CARD_SELECTORS:
        for scope in scopes:
            for index, card in enumerate(scope.safe_css(selector)):
                if card.is_hidden():
                    continue
                card_key = card.html()
                if card_key in seen_cards:
                    continue
                seen_cards.add(card_key)
                subject_id = stable_id(
                    "subject",
                    bundle.bundle_id,
                    doc.artifact_id,
                    "product",
                    len(seen_cards),
                )
                card_rows = _card_evidence(
                    bundle,
                    card,
                    page_url=page_url,
                    subject_id=subject_id,
                    card_selector=selector,
                    card_index=index,
                )
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
    selector_price = _first_price(card)
    strong_card = (
        card_selector not in ECOMMERCE_LISTING_GENERIC_CARD_SELECTORS
        or selector_price is not None
        or _node_has_image(card)
    )
    price = selector_price or _first_price(card, allow_text_scan=strong_card)
    product_link, product_url = _listing_product_link(
        card, page_url=page_url, strong_card=strong_card
    )
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


def _valid_listing_product_url(product_url: str, page_url: str) -> bool:
    product = urlparse(product_url)
    page = urlparse(page_url)
    same_document = (
        product.path.rstrip("/") == page.path.rstrip("/")
        and product.query == page.query
    )
    return (
        product.scheme in {"http", "https"}
        and same_site(page_url, product_url)
        and product.path not in {"", "/"}
        and not same_document
        and not any(
            token in product.path.casefold() for token in LISTING_UTILITY_URL_TOKENS
        )
        and not (
            _listing_url_has_category_segment(product_url)
            and not listing_detail_like_path(product_url)
        )
        and not listing_url_is_structural(product_url)
    )


def _listing_product_link(
    card: HtmlNode,
    *,
    page_url: str,
    strong_card: bool,
) -> tuple[HtmlNode | None, str | None]:
    fallback: tuple[HtmlNode, str] | None = None
    image_fallback: tuple[HtmlNode, str] | None = None
    detail_fallback: tuple[HtmlNode, str] | None = None
    for selector in ECOMMERCE_LISTING_URL_SELECTORS:
        for link in card.css(selector):
            href = str(link.attribute("href") or "").strip()
            product_url = _resolve_listing_href(page_url, href) if href else ""
            if link.is_hidden() or not _valid_listing_product_url(
                product_url, page_url
            ):
                continue
            detail_like = listing_detail_like_path(product_url)
            if detail_like and _link_has_title_signal(link):
                return link, product_url
            if not strong_card:
                continue
            if detail_like:
                detail_fallback = detail_fallback or (link, product_url)
                continue
            fallback = fallback or (link, product_url)
            if image_fallback is None and any(
                link.css_first(image_selector) is not None
                for image_selector in ECOMMERCE_LISTING_IMAGE_SELECTORS
            ):
                image_fallback = (link, product_url)
    return detail_fallback or image_fallback or fallback or (None, None)


def _resolve_listing_href(page_url: str, href: str) -> str:
    product_url = urljoin(page_url, href)
    return _restore_market_locale_product_path(page_url, href, product_url)


def _restore_market_locale_product_path(
    page_url: str, raw_href: str, product_url: str
) -> str:
    if not raw_href.strip():
        return product_url
    page = urlparse(page_url)
    product = urlparse(product_url)
    if not same_site(page_url, product_url):
        return product_url
    page_parts = _path_parts(page.path)
    product_parts = _path_parts(product.path)
    category_index = next(
        (
            index
            for index, part in enumerate(page_parts)
            if part.casefold() in LISTING_STRUCTURAL_CATEGORY_PATH_SEGMENTS
        ),
        None,
    )
    if category_index is None:
        return product_url
    market_prefix = page_parts[:category_index]
    if not market_prefix or product_parts[: len(market_prefix)] == market_prefix:
        return product_url
    first = product_parts[0].casefold() if product_parts else ""
    if first == LISTING_MARKET_LOCALE_PRODUCT_PREFIX:
        restored_parts = (*market_prefix, *product_parts)
    elif first in LISTING_MARKET_LOCALE_GENDER_SEGMENTS and _probable_product_slug(
        product_parts[-1] if product_parts else ""
    ):
        restored_parts = (
            *market_prefix,
            LISTING_MARKET_LOCALE_PRODUCT_PREFIX,
            *product_parts,
        )
    else:
        return product_url
    return urlunparse(product._replace(path="/" + "/".join(restored_parts)))


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
