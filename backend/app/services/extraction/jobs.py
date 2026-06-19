from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from app.services.config.extraction_recipes import (
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
from app.services.extraction.collectors._helpers import evidence, json_objects, loads_jsonish, text_value
from app.services.extraction.contracts import (
    CaptureBundle,
    Decision,
    EntityHint,
    Evidence,
    ExtractionResult,
    Finding,
    RejectedEvidence,
    SourceLocator,
)
from app.services.extraction.documents import HtmlDocument, HtmlNode
from app.services.extraction.ids import stable_id
from app.services.extraction.materialization import lineage
from app.services.extraction.replay import bundle_from_inputs
from app.services.extraction.surfaces import Surface


def extract_job_detail(
    html: str,
    page_url: str,
    *,
    requested_page_url: str | None = None,
) -> ExtractionResult:
    bundle, reader = bundle_from_inputs(html, page_url, requested_page_url)
    doc = reader.document_store.html("html")
    if _has_wrong_surface_product_schema(doc):
        finding = Finding(
            finding_id=stable_id("finding", bundle.bundle_id, "wrong_surface_content"),
            rule_id="WRONG_SURFACE_CONTENT",
            severity="high",
            entity_ids=(),
            evidence_ids=(),
            message="Selected job_detail but page contains product schema.",
            blocking=True,
        )
        replay = _job_replay(
            surface=Surface.JOB_DETAIL,
            bundle=bundle,
            evidence_rows=[],
            decisions=[],
            records=[],
            verdict="error",
            findings=[finding],
        )
        return ExtractionResult(
            surface=Surface.JOB_DETAIL,
            records=(),
            evidence=(),
            findings=(finding,),
            decisions=(),
            verdict="error",
            replay=replay,
        )
    evidence_rows = [
        *_collect_jsonld_job_evidence(bundle, doc, page_url=page_url),
        *_collect_dom_job_evidence(bundle, doc, page_url=page_url),
    ]
    decisions = _resolve_job_decisions(evidence_rows)
    records = _materialize_job_detail(evidence_rows, decisions)
    verdict = "success" if records else "empty"
    replay = _job_replay(
        surface=Surface.JOB_DETAIL,
        bundle=bundle,
        evidence_rows=evidence_rows,
        decisions=decisions,
        records=records,
        verdict=verdict,
    )
    return ExtractionResult(
        surface=Surface.JOB_DETAIL,
        records=tuple(records),
        evidence=tuple(evidence_rows),
        decisions=tuple(decisions),
        verdict=verdict,
        replay=replay,
    )


def extract_job_listing(
    html: str,
    page_url: str,
    *,
    max_records: int,
    requested_page_url: str | None = None,
) -> ExtractionResult:
    bundle, reader = bundle_from_inputs(html, page_url, requested_page_url)
    doc = reader.document_store.html("html")
    evidence_rows = _collect_job_listing_evidence(bundle, doc, page_url=page_url)
    decisions = _resolve_listing_job_decisions(evidence_rows)
    records = _materialize_job_listing(evidence_rows, decisions, max_records=max_records)
    verdict = "success" if records else "empty"
    replay = _job_replay(
        surface=Surface.JOB_LISTING,
        bundle=bundle,
        evidence_rows=evidence_rows,
        decisions=decisions,
        records=records,
        verdict=verdict,
    )
    return ExtractionResult(
        surface=Surface.JOB_LISTING,
        records=tuple(records),
        evidence=tuple(evidence_rows),
        decisions=tuple(decisions),
        verdict=verdict,
        replay=replay,
    )


def _job_replay(
    *,
    surface: Surface,
    bundle: CaptureBundle,
    evidence_rows: list[Evidence],
    decisions: list[Decision],
    records: list[dict[str, Any]],
    verdict: str,
    findings: list[Finding] | None = None,
) -> dict[str, Any]:
    return {
        "surface": surface.value,
        "bundle": bundle.model_dump(mode="json"),
        "evidence": [row.model_dump(mode="json") for row in evidence_rows],
        "findings": [row.model_dump(mode="json") for row in findings or []],
        "decisions": [row.model_dump(mode="json") for row in decisions],
        "records": records,
        "verdict": verdict,
    }


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
            fields = {
                "title": "job.title",
                "identifier": "job.id",
                "datePosted": "job.posted_date",
                "employmentType": "job.type",
                "description": "job.description",
                "url": "job.url",
            }
            for key, fact_type in fields.items():
                value = _jsonld_value(item.get(key), page_url=page_url, fact_type=fact_type)
                if value:
                    rows.append(
                        _job_evidence(
                            bundle,
                            artifact_id=f"jsonld:{script_index}",
                            collector_id="job_jsonld",
                            fact_type=fact_type,
                            value=value,
                            subject_id=subject_id,
                            locator=SourceLocator(kind="json_pointer", value=f"{path}/{key}", preview=str(value)[:120]),
                            confidence=0.92,
                            directness="embedded",
                        )
                    )
            company = _jsonld_value(item.get("hiringOrganization"), page_url=page_url, fact_type="job.company")
            if company:
                rows.append(
                    _job_evidence(
                        bundle,
                        artifact_id=f"jsonld:{script_index}",
                        collector_id="job_jsonld",
                        fact_type="job.company",
                        value=company,
                        subject_id=subject_id,
                        locator=SourceLocator(kind="json_pointer", value=f"{path}/hiringOrganization", preview=company[:120]),
                        confidence=0.9,
                        directness="embedded",
                    )
                )
            location = _jsonld_location(item.get("jobLocation"))
            if location:
                rows.append(
                    _job_evidence(
                        bundle,
                        artifact_id=f"jsonld:{script_index}",
                        collector_id="job_jsonld",
                        fact_type="job.location",
                        value=location,
                        subject_id=subject_id,
                        locator=SourceLocator(kind="json_pointer", value=f"{path}/jobLocation", preview=location[:120]),
                        confidence=0.9,
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


def _resolve_job_decisions(evidence_rows: list[Evidence]) -> list[Decision]:
    by_fact: dict[str, list[Evidence]] = {}
    for row in evidence_rows:
        by_fact.setdefault(row.fact_type, []).append(row)
    decisions: list[Decision] = []
    for fact_type, rows in sorted(by_fact.items()):
        candidates = sorted(rows, key=lambda row: (-row.confidence, row.evidence_id))
        accepted = candidates[0]
        decisions.append(
            Decision(
                decision_id=stable_id("decision", accepted.subject_id, fact_type, accepted.evidence_id),
                entity_id=accepted.subject_id or "job",
                fact_type=fact_type,
                accepted_evidence_ids=(accepted.evidence_id,),
                rejected=tuple(
                    RejectedEvidence(evidence_id=row.evidence_id, reason="lower_confidence")
                    for row in candidates[1:]
                ),
                finding_ids=(),
                rule_id="job_detail_highest_confidence_v1",
                status="resolved",
            )
        )
    return decisions


def _resolve_listing_job_decisions(evidence_rows: list[Evidence]) -> list[Decision]:
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
            accepted = candidates[0]
            decisions.append(
                Decision(
                    decision_id=stable_id("decision", subject_id, fact_type, accepted.evidence_id),
                    entity_id=subject_id,
                    fact_type=fact_type,
                    accepted_evidence_ids=(accepted.evidence_id,),
                    rejected=tuple(
                        RejectedEvidence(evidence_id=row.evidence_id, reason="lower_confidence")
                        for row in candidates[1:]
                    ),
                    finding_ids=(),
                    rule_id="job_listing_highest_confidence_v1",
                    status="resolved",
                )
            )
    return decisions


def _materialize_job_detail(
    evidence_rows: list[Evidence],
    decisions: list[Decision],
) -> list[dict[str, Any]]:
    by_id = {row.evidence_id: row for row in evidence_rows}
    field_map = {
        "job.title": "title",
        "job.id": "job_id",
        "job.company": "company",
        "job.location": "location",
        "job.type": "job_type",
        "job.posted_date": "posted_date",
        "job.url": "url",
        "job.apply_url": "apply_url",
        "job.description": "description",
    }
    row: dict[str, Any] = {}
    lineages: dict[str, object] = {}
    for decision in decisions:
        field = field_map.get(decision.fact_type)
        if not field or not decision.accepted_evidence_ids:
            continue
        evidence_row = by_id[decision.accepted_evidence_ids[0]]
        row[field] = evidence_row.value
        lineages[field] = lineage(decision=decision)
    if not row.get("title"):
        return []
    if lineages:
        row["_lineage"] = lineages
    return [row]


def _materialize_job_listing(
    evidence_rows: list[Evidence],
    decisions: list[Decision],
    *,
    max_records: int,
) -> list[dict[str, Any]]:
    by_id = {row.evidence_id: row for row in evidence_rows}
    field_map = {
        "job.title": "title",
        "job.url": "url",
        "job.company": "company",
        "job.location": "location",
    }
    rows_by_subject: dict[str, dict[str, Any]] = {}
    lineage_by_subject: dict[str, dict[str, object]] = {}
    for decision in decisions:
        field = field_map.get(decision.fact_type)
        if not field or not decision.accepted_evidence_ids:
            continue
        evidence_row = by_id[decision.accepted_evidence_ids[0]]
        subject_id = evidence_row.subject_id or decision.entity_id
        rows_by_subject.setdefault(subject_id, {})[field] = evidence_row.value
        lineage_by_subject.setdefault(subject_id, {})[field] = lineage(decision=decision)
    materialized: list[dict[str, Any]] = []
    for subject_id, row in rows_by_subject.items():
        if not row.get("title") or not row.get("url"):
            continue
        row["_lineage"] = lineage_by_subject.get(subject_id, {})
        row["_subject_id"] = subject_id
        materialized.append(row)
    materialized.sort(key=lambda row: str(row.get("url") or ""))
    return materialized[:max_records]


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
        text = text_value(value)
        return urljoin(page_url, text) if text else None
    text = _clean_text(text_value(value))
    return text or None


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
