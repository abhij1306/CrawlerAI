from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from app.core.config.extraction_recipes import (
    JOB_DETAIL_APPLY_SELECTORS,
    JOB_DETAIL_COMPANY_SELECTORS,
    JOB_DETAIL_DESCRIPTION_SELECTORS,
    JOB_DETAIL_LOCATION_SELECTORS,
    JOB_DETAIL_TITLE_SELECTORS,
    JOB_LISTING_CARD_SELECTORS,
    JOB_LISTING_COMPANY_SELECTORS,
    JOB_LISTING_LOCATION_SELECTORS,
    JOB_LISTING_TITLE_SELECTORS,
    JOB_LISTING_URL_SELECTORS,
)
from app.extraction.collectors._helpers import evidence, json_objects, loads_jsonish, text_value
from app.extraction.contracts import (
    ArtifactReader,
    CaptureBundle,
    EntityHint,
    Evidence,
    Finding,
    SourceLocator,
)
from app.extraction.documents import HtmlDocument, HtmlNode
from app.extraction.ids import stable_id
from app.extraction.surfaces import Surface


def wrong_surface_findings_for_job_detail(
    bundle: CaptureBundle,
    reader: ArtifactReader,
) -> tuple[Finding, ...]:
    doc = reader.document_store.html("html")
    if not _has_wrong_surface_product_schema(doc):
        return ()
    return (
        Finding(
            finding_id=stable_id("finding", bundle.bundle_id, "wrong_surface_content"),
            rule_id="WRONG_SURFACE_CONTENT",
            severity="high",
            scope="page",
            entity_ids=(),
            evidence_ids=(),
            message="Selected job_detail but page contains product schema.",
            blocking=True,
        ),
    )


def collect_job_detail(bundle: CaptureBundle, reader: ArtifactReader) -> list[Evidence]:
    doc = reader.document_store.html("html")
    return [
        *_collect_jsonld_job_evidence(bundle, doc, page_url=bundle.final_url),
        *_collect_dom_job_evidence(bundle, doc, page_url=bundle.final_url),
    ]


def collect_job_listing(bundle: CaptureBundle, reader: ArtifactReader) -> list[Evidence]:
    doc = reader.document_store.html("html")
    return _collect_job_listing_evidence(bundle, doc, page_url=bundle.final_url)


def _collect_job_listing_evidence(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    *,
    page_url: str,
) -> list[Evidence]:
    rows: list[Evidence] = []
    seen_cards: set[str] = set()
    for selector in JOB_LISTING_CARD_SELECTORS:
        for index, card in enumerate(doc.css(selector)):
            if card.is_hidden():
                continue
            card_key = card.html()
            if card_key in seen_cards:
                continue
            seen_cards.add(card_key)
            subject_id = stable_id("subject", bundle.bundle_id, "job", len(seen_cards))
            card_rows = _job_listing_card_evidence(
                bundle,
                card,
                page_url=page_url,
                subject_id=subject_id,
                card_selector=selector,
                card_index=index,
            )
            facts = {row.fact_type for row in card_rows}
            if "job.title" in facts and "job.url" in facts:
                rows.extend(card_rows)
    return rows


def _job_listing_card_evidence(
    bundle: CaptureBundle,
    card: HtmlNode,
    *,
    page_url: str,
    subject_id: str,
    card_selector: str,
    card_index: int,
) -> list[Evidence]:
    title = _first_node_text(card, JOB_LISTING_TITLE_SELECTORS)
    url = _first_node_attr(card, JOB_LISTING_URL_SELECTORS, "href")
    company = _first_node_text(card, JOB_LISTING_COMPANY_SELECTORS)
    location = _first_node_text(card, JOB_LISTING_LOCATION_SELECTORS)
    values = (
        ("job.title", title, "title", 0.72),
        ("job.url", urljoin(page_url, url) if url else None, "url", 0.74),
        ("job.company", company, "company", 0.62),
        ("job.location", location, "location", 0.62),
    )
    rows: list[Evidence] = []
    for fact_type, value, field, confidence in values:
        if not value:
            continue
        rows.append(
            _job_evidence(
                bundle,
                artifact_id="html",
                collector_id="job_listing_css",
                fact_type=fact_type,
                value=value,
                subject_id=subject_id,
                locator=SourceLocator(
                    kind="css_selector",
                    value=f"{card_selector}:nth-match({card_index + 1}) {field}",
                    preview=str(value)[:120],
                ),
                confidence=confidence,
                directness="direct",
                surface=Surface.JOB_LISTING,
            )
        )
    return rows


def _collect_jsonld_job_evidence(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    *,
    page_url: str,
) -> list[Evidence]:
    rows: list[Evidence] = []
    subject_id = stable_id("subject", bundle.bundle_id, "job", page_url)
    for script_index, tag in enumerate(doc.css('script[type*="ld+json"]')):
        data = loads_jsonish(tag.text(separator=" ", strip=True))
        for path, item in json_objects(data):
            if not isinstance(item, dict) or not _is_job_posting(item):
                continue
            rows.extend(
                _jsonld_job_item_evidence(
                    bundle,
                    item,
                    artifact_id=f"jsonld:{script_index}",
                    path=path,
                    page_url=page_url,
                    subject_id=subject_id,
                )
            )
    return rows


def _jsonld_job_item_evidence(
    bundle: CaptureBundle,
    item: dict[str, Any],
    *,
    artifact_id: str,
    path: str,
    page_url: str,
    subject_id: str,
) -> list[Evidence]:
    values = {
        "title": ("job.title", 0.92),
        "identifier": ("job.id", 0.92),
        "datePosted": ("job.posted_date", 0.92),
        "employmentType": ("job.type", 0.92),
        "description": ("job.description", 0.92),
        "url": ("job.url", 0.92),
        "hiringOrganization": ("job.company", 0.9),
        "jobLocation": ("job.location", 0.9),
    }
    rows: list[Evidence] = []
    for key, (fact_type, confidence) in values.items():
        value = (
            _jsonld_location(item.get(key))
            if key == "jobLocation"
            else _jsonld_value(item.get(key), page_url=page_url, fact_type=fact_type)
        )
        if not value:
            continue
        rows.append(
            _job_evidence(
                bundle,
                artifact_id=artifact_id,
                collector_id="job_jsonld",
                fact_type=fact_type,
                value=value,
                subject_id=subject_id,
                locator=SourceLocator(
                    kind="json_pointer",
                    value=f"{path}/{key}",
                    preview=str(value)[:120],
                ),
                confidence=confidence,
                directness="embedded",
            )
        )
    return rows


def _collect_dom_job_evidence(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    *,
    page_url: str,
) -> list[Evidence]:
    subject_id = stable_id("subject", bundle.bundle_id, "job", page_url)
    rows: list[Evidence] = []
    for fact_type, value, selector, confidence in (
        ("job.title", _first_text(doc, JOB_DETAIL_TITLE_SELECTORS), "title", 0.72),
        ("job.company", _first_text(doc, JOB_DETAIL_COMPANY_SELECTORS), "company", 0.62),
        ("job.location", _first_text(doc, JOB_DETAIL_LOCATION_SELECTORS), "location", 0.62),
        ("job.description", _first_text(doc, JOB_DETAIL_DESCRIPTION_SELECTORS), "description", 0.55),
        ("job.apply_url", _first_url(doc, JOB_DETAIL_APPLY_SELECTORS, page_url=page_url), "apply_url", 0.66),
        ("job.url", page_url, "page_url", 0.5),
    ):
        if not value:
            continue
        rows.append(
            _job_evidence(
                bundle,
                artifact_id="html",
                collector_id="job_dom",
                fact_type=fact_type,
                value=value,
                subject_id=subject_id,
                locator=SourceLocator(kind="css_selector", value=selector, preview=str(value)[:120]),
                confidence=confidence,
                directness="direct",
            )
        )
    return rows


def _job_evidence(
    bundle: CaptureBundle,
    *,
    artifact_id: str,
    collector_id: str,
    fact_type: str,
    value: object,
    subject_id: str,
    locator: SourceLocator,
    confidence: float,
    directness: str,
    surface: Surface = Surface.JOB_DETAIL,
) -> Evidence:
    return evidence(
        bundle,
        artifact_id,
        collector_id,
        fact_type,
        value,
        locator,
        group_id=subject_id,
        hint=EntityHint(entity_type="job"),
        confidence=confidence,
        directness=directness,
    ).model_copy(
        update={
            "surface": surface,
            "subject_id": subject_id,
            "parent_subject_id": None,
        }
    )


def _is_job_posting(item: dict[str, Any]) -> bool:
    types = item.get("@type") or item.get("type")
    values = types if isinstance(types, list) else [types]
    return any(str(value or "").strip().lower() == "jobposting" for value in values)


def _has_wrong_surface_product_schema(doc: HtmlDocument) -> bool:
    saw_product = False
    saw_job = False
    for tag in doc.css('script[type*="ld+json"]'):
        data = loads_jsonish(tag.text(separator=" ", strip=True))
        for _, item in json_objects(data):
            if not isinstance(item, dict):
                continue
            types = item.get("@type") or item.get("type")
            values = types if isinstance(types, list) else [types]
            normalized = {str(value or "").strip().lower() for value in values}
            saw_product = saw_product or bool(normalized & {"product", "productgroup"})
            saw_job = saw_job or "jobposting" in normalized
    return saw_product and not saw_job


def _jsonld_value(value: object, *, page_url: str, fact_type: str) -> str | None:
    if fact_type in {"job.url", "job.apply_url"}:
        url_text = text_value(value)
        return urljoin(page_url, url_text) if url_text else None
    cleaned = _clean_text(text_value(value))
    return cleaned or None


def _jsonld_location(value: object) -> str | None:
    rows = value if isinstance(value, list) else [value]
    parts: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            address = row.get("address")
            if isinstance(address, dict):
                parts.extend(
                    _clean_text(address.get(key)) or ""
                    for key in ("addressLocality", "addressRegion", "addressCountry")
                )
            else:
                parts.append(_clean_text(text_value(address)) or "")
        else:
            parts.append(_clean_text(text_value(row)) or "")
    cleaned = [part for part in parts if part]
    return ", ".join(dict.fromkeys(cleaned)) or None


def _first_text(doc: HtmlDocument, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        node = doc.css_first(selector)
        if node is None or node.is_hidden():
            continue
        text = _clean_text(node.attribute("content") or node.text(separator=" ", strip=True))
        if text:
            return text
    return None


def _first_node_text(node: HtmlNode, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        child = node.css_first(selector)
        if child is None or child.is_hidden():
            continue
        text = _clean_text(child.attribute("title") or child.text(separator=" ", strip=True))
        if text:
            return text
    return None


def _first_node_attr(node: HtmlNode, selectors: tuple[str, ...], attr: str) -> str | None:
    for selector in selectors:
        child = node.css_first(selector)
        if child is None or child.is_hidden():
            continue
        value = str(child.attribute(attr) or "").strip()
        if value:
            return value
    return None


def _first_url(doc: HtmlDocument, selectors: tuple[str, ...], *, page_url: str) -> str | None:
    for selector in selectors:
        node = doc.css_first(selector)
        if node is None or node.is_hidden():
            continue
        href = str(node.attribute("href") or "").strip()
        if href:
            return urljoin(page_url, href)
    return None


def _clean_text(value: object) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None
