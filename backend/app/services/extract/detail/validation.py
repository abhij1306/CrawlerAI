from __future__ import annotations

from typing import Any

from app.services.config.variant_policy import (
    DETAIL_MINIMUM_KNOWLEDGE_FIELDS,
    DETAIL_REQUIRED_OFFER_FIELDS,
)
from app.services.extract.variant_axis import public_variant_axis_fields
from app.services.extract.variant_identity_merge import variant_url_matches_parent_product
from app.services.shared.field_coerce import extract_currency_code, text_or_none

__all__ = (
    "attach_detail_validation_findings",
    "validate_detail_record",
    "validate_price_currency",
    "validate_product_evidence",
    "validate_variant_offers",
    "variant_offer_is_complete",
    "variant_offer_status",
)

_EXPLICITLY_UNAVAILABLE = frozenset(
    {"out_of_stock", "sold_out", "unavailable", "discontinued"}
)
_OFFER_FIELDS = ("price", "currency")


def variant_offer_status(
    variant: dict[str, Any],
    *,
    parent: dict[str, Any] | None = None,
) -> str:
    availability = str(variant.get("availability") or "").strip().lower()
    if availability in _EXPLICITLY_UNAVAILABLE:
        return "explicitly_unavailable"
    has_axis = any(text_or_none(variant.get(axis)) for axis in public_variant_axis_fields)
    if not has_axis:
        return "non_commercial_option"
    if all(text_or_none(variant.get(field_name)) for field_name in _OFFER_FIELDS):
        return "complete_sellable"
    parent_offer_complete = isinstance(parent, dict) and all(
        text_or_none(parent.get(field_name)) for field_name in _OFFER_FIELDS
    )
    parent_url = (
        text_or_none(parent.get("url") or parent.get("source_url"))
        if isinstance(parent, dict)
        else None
    )
    variant_url = text_or_none(variant.get("url"))
    distinct_product_url = (
        bool(variant_url and parent_url)
        and not variant_url_matches_parent_product(variant_url, parent_url=parent_url)
    )
    has_offer_identity = any(
        text_or_none(variant.get(field_name))
        for field_name in ("sku", "variant_id", "url", "image_url")
    ) and not distinct_product_url
    if parent_offer_complete and has_offer_identity:
        return "inherited_parent_offer"
    return "incomplete_sellable"


def variant_offer_is_complete(
    variant: dict[str, Any],
    *,
    parent: dict[str, Any] | None = None,
) -> bool:
    return variant_offer_status(variant, parent=parent) in {
        "complete_sellable",
        "inherited_parent_offer",
        "explicitly_unavailable",
        "non_commercial_option",
    }


def validate_detail_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *validate_product_evidence(record),
        *validate_variant_offers(record),
        *validate_price_currency(record),
    ]


def attach_detail_validation_findings(record: dict[str, Any]) -> None:
    findings = validate_detail_record(record)
    if not findings:
        return
    existing = [
        finding
        for finding in record.get("_validation_findings") or []
        if isinstance(finding, dict)
    ]
    signatures = {
        (
            str(finding.get("rule_id") or ""),
            str(finding.get("entity_ref") or ""),
            str(finding.get("field_name") or ""),
        )
        for finding in existing
    }
    for finding in findings:
        finding["evidence_ids"] = _evidence_ids_for_finding(record, finding)
        signature = (
            str(finding.get("rule_id") or ""),
            str(finding.get("entity_ref") or ""),
            str(finding.get("field_name") or ""),
        )
        if signature not in signatures:
            existing.append(finding)
            signatures.add(signature)
    record["_validation_findings"] = existing
    _link_findings_to_field_summaries(record, existing)


def validate_variant_offers(record: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, variant in enumerate(record.get("variants") or []):
        if (
            not isinstance(variant, dict)
            or variant_offer_status(variant, parent=record) != "incomplete_sellable"
        ):
            continue
        missing_fields = [
            field_name
            for field_name in _OFFER_FIELDS
            if not text_or_none(variant.get(field_name))
        ]
        findings.append(
            {
                "finding_id": f"variant_offer:{index}",
                "rule_id": "INCOMPLETE_SELLABLE_VARIANT_OFFER",
                "severity": "high",
                "field_name": "variants",
                "entity_ref": f"variant:{index}",
                "evidence_ids": [],
                "message": "Sellable variant lacks complete offer evidence.",
                "suggested_action": "collect_dom_or_review",
                "metadata": {"missing_fields": missing_fields},
            }
        )
    return findings


def validate_product_evidence(record: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    missing_offer_fields = [
        field_name
        for field_name in DETAIL_REQUIRED_OFFER_FIELDS
        if not text_or_none(record.get(field_name))
    ]
    if missing_offer_fields:
        findings.append(
            {
                "finding_id": "product_offer:missing",
                "rule_id": "MISSING_PRODUCT_OFFER_EVIDENCE",
                "severity": "high",
                "field_name": "price",
                "entity_ref": "product",
                "evidence_ids": [],
                "message": "Product lacks complete price and currency evidence.",
                "suggested_action": "retry_acquisition_or_review",
                "metadata": {"missing_fields": missing_offer_fields},
            }
        )
    present_knowledge = [
        field_name
        for field_name in DETAIL_MINIMUM_KNOWLEDGE_FIELDS
        if record.get(field_name) not in (None, "", [], {})
    ]
    if not present_knowledge:
        findings.append(
            {
                "finding_id": "product_knowledge:insufficient",
                "rule_id": "INSUFFICIENT_DETAIL_EVIDENCE",
                "severity": "high",
                "field_name": "_product",
                "entity_ref": "product",
                "evidence_ids": [],
                "message": "Page capture contains no product knowledge beyond identity.",
                "suggested_action": "retry_acquisition_or_review",
                "metadata": {},
            }
        )
    return findings


def validate_price_currency(record: dict[str, Any]) -> list[dict[str, Any]]:
    parent_currency = _currency_code(record.get("currency"))
    if not parent_currency:
        return []
    findings: list[dict[str, Any]] = []
    for index, variant in enumerate(record.get("variants") or []):
        if not isinstance(variant, dict):
            continue
        variant_currency = _currency_code(variant.get("currency"))
        if not variant_currency or variant_currency == parent_currency:
            continue
        findings.append(
            {
                "finding_id": f"currency_contradiction:{index}",
                "rule_id": "CURRENCY_CONTRADICTION",
                "severity": "high",
                "field_name": "currency",
                "entity_ref": f"variant:{index}",
                "evidence_ids": [],
                "message": "Variant currency contradicts parent currency.",
                "suggested_action": "review_request_context",
                "metadata": {
                    "parent_currency": parent_currency,
                    "variant_currency": variant_currency,
                },
            }
        )
    return findings


def _currency_code(value: object) -> str:
    extracted = extract_currency_code(value)
    return str(extracted or text_or_none(value) or "").strip().upper()


def _evidence_ids_for_finding(
    record: dict[str, Any],
    finding: dict[str, Any],
) -> list[str]:
    field_evidence = record.get("_field_evidence")
    if not isinstance(field_evidence, dict):
        return []
    field_name = str(finding.get("field_name") or "")
    field_summary = field_evidence.get(field_name)
    if isinstance(field_summary, dict):
        ids = field_summary.get("winning_evidence_ids")
        if isinstance(ids, list) and ids:
            return [str(item) for item in ids if str(item)]
    if field_name:
        return []
    linked: list[str] = []
    for summary in field_evidence.values():
        if not isinstance(summary, dict):
            continue
        for evidence_id in summary.get("winning_evidence_ids") or []:
            normalized = str(evidence_id or "")
            if normalized and normalized not in linked:
                linked.append(normalized)
    return linked


def _link_findings_to_field_summaries(
    record: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    field_evidence = record.get("_field_evidence")
    if not isinstance(field_evidence, dict):
        return
    graph = record.get("_evidence_graph")
    raw_graph_decisions = graph.get("field_decisions") if isinstance(graph, dict) else {}
    graph_decisions: dict[str, Any] = (
        raw_graph_decisions if isinstance(raw_graph_decisions, dict) else {}
    )
    for finding in findings:
        finding_id = str(finding.get("finding_id") or "")
        if not finding_id:
            continue
        linked_ids = set(finding.get("evidence_ids") or [])
        for field_name, summary in field_evidence.items():
            if not isinstance(summary, dict):
                continue
            winning_ids = set(summary.get("winning_evidence_ids") or [])
            if not linked_ids.intersection(winning_ids):
                continue
            validation_ids = summary.setdefault("validation_finding_ids", [])
            if finding_id not in validation_ids:
                validation_ids.append(finding_id)
            graph_summary = graph_decisions.get(field_name)
            if isinstance(graph_summary, dict):
                graph_validation_ids = graph_summary.setdefault(
                    "validation_finding_ids", []
                )
                if finding_id not in graph_validation_ids:
                    graph_validation_ids.append(finding_id)
