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
    JOB_LISTING_COMPANY_SELECTORS,
    JOB_LISTING_LOCATION_SELECTORS,
    JOB_LISTING_TITLE_SELECTORS,
    JOB_LISTING_URL_SELECTORS,
    LISTING_HTML_ARTIFACT_IDS,
)
from app.core.listing_cards import select_listing_cards
from app.extraction.collectors._helpers import (
    evidence,
    html_doc,
    json_objects,
    loads_jsonish,
    text_without_non_text_descendants,
    text_value,
)
from app.extraction.contracts import (
    ArtifactReader,
    CaptureBundle,
    Decision,
    EntityHint,
    Evidence,
    Finding,
    RejectedEvidence,
    SourceLocator,
)
from app.extraction.documents import HtmlDocument, HtmlNode
from app.core.shared.ids import stable_id
from app.extraction.surfaces import Surface, listing_schema


def _wrong_surface_findings(
    bundle: CaptureBundle,
    reader: ArtifactReader,
    *,
    finding_suffix: str,
    message: str,
) -> tuple[Finding, ...]:
    """Blocking wrong-surface finding when a job page carries product schema.

    Shared by the job_detail and job_listing guards: when the page carries
    product schema and no JobPosting schema, the surface was mis-selected as a
    job page over a commerce page. ``finding_suffix`` keeps the two callers'
    finding ids distinct; ``message`` names the mis-selected surface.
    """
    doc = reader.document_store.html("html")
    if not _has_wrong_surface_product_schema(doc):
        return ()
    return (
        Finding(
            finding_id=stable_id("finding", bundle.bundle_id, finding_suffix),
            rule_id="WRONG_SURFACE_CONTENT",
            severity="high",
            scope="page",
            entity_ids=(),
            evidence_ids=(),
            message=message,
            blocking=True,
        ),
    )


def wrong_surface_findings_for_job_detail(
    bundle: CaptureBundle,
    reader: ArtifactReader,
) -> tuple[Finding, ...]:
    return _wrong_surface_findings(
        bundle,
        reader,
        finding_suffix="wrong_surface_content",
        message="Selected job_detail but page contains product schema.",
    )


def wrong_surface_findings_for_job_listing(
    bundle: CaptureBundle,
    reader: ArtifactReader,
) -> tuple[Finding, ...]:
    """Reject a job_listing page whose structured content is a product listing.

    Mirrors ``wrong_surface_findings_for_job_detail``: when the page carries
    product schema and no JobPosting schema, it is a commerce listing selected
    as jobs — a blocking wrong-surface finding, not an empty job listing.
    """
    return _wrong_surface_findings(
        bundle,
        reader,
        finding_suffix="wrong_surface_content_listing",
        message="Selected job_listing but page contains product schema.",
    )


def collect_job_detail(bundle: CaptureBundle, reader: ArtifactReader) -> list[Evidence]:
    _, doc = html_doc(bundle, reader)
    structured = _collect_jsonld_job_evidence(bundle, doc, page_url=bundle.final_url)
    dom = _collect_dom_job_evidence(bundle, doc, page_url=bundle.final_url)
    structured_subjects = {row.subject_id for row in structured}
    if len(structured_subjects) == 1:
        subject_id = next(iter(structured_subjects))
        dom = [
            row.model_copy(update={"subject_id": subject_id, "group_id": subject_id})
            for row in dom
        ]
    return [*structured, *dom]


class _JobStructuredCollector:
    """Structured JSON-LD JobPosting floor as a cascade-shaped collector.

    Reads the rendered-preferring document so JS-rendered job pages are covered,
    then yields the JSON-LD JobPosting evidence via the shared collector.
    """

    collector_id = "job_jsonld"

    def collect(
        self, bundle: CaptureBundle, reader: ArtifactReader
    ) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, reader)
        return tuple(
            _collect_jsonld_job_evidence(bundle, doc, page_url=bundle.final_url)
        )


class _JobDomCollector:
    """DOM job-detail floor as a cascade-shaped collector.

    Rebinds its rows onto the single structured JobPosting subject when exactly
    one exists, preserving the legacy subject-unification so structured and DOM
    evidence share one subject inside the detail cascade profile.
    """

    collector_id = "job_dom"

    def collect(
        self, bundle: CaptureBundle, reader: ArtifactReader
    ) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, reader)
        subject_id = _single_structured_job_subject(
            bundle, doc, page_url=bundle.final_url
        )
        return tuple(
            _collect_dom_job_evidence(
                bundle, doc, page_url=bundle.final_url, subject_id=subject_id
            )
        )


def job_detail_structured_collectors() -> tuple[object, ...]:
    """Structured-source detail floor for job_detail (JSON-LD JobPosting)."""
    return (_JobStructuredCollector(),)


def job_detail_dom_collectors() -> tuple[object, ...]:
    """DOM detail floor for job_detail, fused onto the structured subject."""
    return (_JobDomCollector(),)


def _single_structured_job_subject(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    *,
    page_url: str,
) -> str | None:
    """The single structured JobPosting subject id, or ``None`` when absent or
    ambiguous — the DOM floor only fuses onto an unambiguous structured subject."""
    subjects = {
        row.subject_id
        for row in _collect_jsonld_job_evidence(bundle, doc, page_url=page_url)
    }
    return next(iter(subjects)) if len(subjects) == 1 else None


def collect_job_listing(
    bundle: CaptureBundle, reader: ArtifactReader
) -> list[Evidence]:
    # Read the shared LISTING HTML-artifact set (base document plus rendered
    # listing fragments / visual-element HTML) so JS-rendered job boards, whose
    # cards only appear after render, are covered — not just the raw "html".
    # The first artifact that yields cards wins, matching the DOM-floor's
    # first-non-empty-artifact contract.
    rows: list[Evidence] = []
    for artifact_id in LISTING_HTML_ARTIFACT_IDS:
        if not reader.exists(artifact_id):
            continue
        doc = reader.document_store.html(artifact_id)
        rows = _collect_job_listing_evidence(bundle, doc, page_url=bundle.final_url)
        if rows:
            return rows
    return rows


def _collect_job_listing_evidence(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    *,
    page_url: str,
) -> list[Evidence]:
    rows: list[Evidence] = []
    schema = listing_schema(Surface.JOB_LISTING)
    if schema is None:
        return rows
    for position, candidate in enumerate(
        select_listing_cards(doc, surface=schema, page_url=page_url), start=1
    ):
        subject_id = stable_id("subject", bundle.bundle_id, "job", position)
        rows.extend(
            _job_listing_card_evidence(
                bundle,
                candidate.node,
                page_url=page_url,
                subject_id=subject_id,
                card_selector=candidate.selector,
                card_index=candidate.selector_index,
                artifact_id=doc.artifact_id,
            )
        )
    return rows


def _job_listing_card_evidence(
    bundle: CaptureBundle,
    card: HtmlNode,
    *,
    page_url: str,
    subject_id: str,
    card_selector: str,
    card_index: int,
    artifact_id: str = "html",
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
                artifact_id=artifact_id,
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
    for script_index, tag in enumerate(doc.css('script[type*="ld+json"]')):
        data = loads_jsonish(tag.text(separator=" ", strip=True))
        for path, item in json_objects(data):
            if not isinstance(item, dict) or not _is_job_posting(item):
                continue
            subject_id = _job_subject_id(
                bundle,
                item,
                page_url=page_url,
                fallback=(script_index, path),
            )
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
    subject_id: str | None = None,
) -> list[Evidence]:
    subject_id = subject_id or stable_id("subject", bundle.bundle_id, "job", page_url)
    rows: list[Evidence] = []
    for fact_type, value, selector, confidence in (
        ("job.title", _first_text(doc, JOB_DETAIL_TITLE_SELECTORS), "title", 0.72),
        (
            "job.company",
            _first_text(doc, JOB_DETAIL_COMPANY_SELECTORS),
            "company",
            0.62,
        ),
        (
            "job.location",
            _first_text(doc, JOB_DETAIL_LOCATION_SELECTORS),
            "location",
            0.62,
        ),
        (
            "job.description",
            _first_text(doc, JOB_DETAIL_DESCRIPTION_SELECTORS),
            "description",
            0.55,
        ),
        (
            "job.apply_url",
            _first_url(doc, JOB_DETAIL_APPLY_SELECTORS, page_url=page_url),
            "apply_url",
            0.66,
        ),
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
                locator=SourceLocator(
                    kind="css_selector", value=selector, preview=str(value)[:120]
                ),
                confidence=confidence,
                directness="direct",
            )
        )
    return rows


def _job_subject_id(
    bundle: CaptureBundle,
    item: dict[str, Any],
    *,
    page_url: str,
    fallback: tuple[object, ...],
) -> str:
    """Prefer stable schema identity; use source position only as a last resort."""

    canonical_identity = (
        _jsonld_value(item.get("identifier"), page_url=page_url, fact_type="job.id")
        or _jsonld_value(item.get("url"), page_url=page_url, fact_type="job.url")
        or _jsonld_value(item.get("title"), page_url=page_url, fact_type="job.title")
    )
    identity = (canonical_identity,) if canonical_identity else fallback
    return stable_id("subject", bundle.bundle_id, "job", *identity)


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
        text = _clean_text(node.attribute("content") or text_without_non_text_descendants(node))
        if text:
            return text
    return None


def _first_node_text(node: HtmlNode, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        child = node.css_first(selector)
        if child is None or child.is_hidden():
            continue
        text = _clean_text(
            child.attribute("title") or child.text(separator=" ", strip=True)
        )
        if text:
            return text
    return None


def _first_node_attr(
    node: HtmlNode, selectors: tuple[str, ...], attr: str
) -> str | None:
    for selector in selectors:
        child = node.css_first(selector)
        if child is None or child.is_hidden():
            continue
        value = str(child.attribute(attr) or "").strip()
        if value:
            return value
    return None


def _first_url(
    doc: HtmlDocument, selectors: tuple[str, ...], *, page_url: str
) -> str | None:
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


def resolve_job_detail(evidence_rows: list[Evidence]) -> list[Decision]:
    by_fact: dict[str, list[Evidence]] = {}
    for row in evidence_rows:
        by_fact.setdefault(row.fact_type, []).append(row)
    return [
        _job_decision(
            rows[0].subject_id or "job",
            fact_type,
            rows,
            rule_id="job_detail_highest_confidence_v1",
        )
        for fact_type, rows in sorted(by_fact.items())
    ]


def resolve_job_listing(evidence_rows: list[Evidence]) -> list[Decision]:
    by_subject: dict[str, dict[str, list[Evidence]]] = {}
    for row in evidence_rows:
        if row.subject_id:
            by_subject.setdefault(row.subject_id, {}).setdefault(
                row.fact_type, []
            ).append(row)
    return [
        _job_decision(
            subject_id,
            fact_type,
            rows,
            rule_id="job_listing_highest_confidence_v1",
        )
        for subject_id, facts in by_subject.items()
        for fact_type, rows in sorted(facts.items())
    ]


def _job_decision(
    entity_id: str,
    fact_type: str,
    rows: list[Evidence],
    *,
    rule_id: str,
) -> Decision:
    candidates = sorted(rows, key=lambda row: (-row.confidence, row.evidence_id))
    accepted = candidates[0]
    return Decision(
        decision_id=stable_id("decision", entity_id, fact_type, accepted.evidence_id),
        entity_id=entity_id,
        fact_type=fact_type,
        accepted_evidence_ids=(accepted.evidence_id,),
        rejected=tuple(
            RejectedEvidence(
                evidence_id=row.evidence_id,
                reason="lower_confidence",
            )
            for row in candidates[1:]
        ),
        finding_ids=(),
        rule_id=rule_id,
        status="resolved",
    )
