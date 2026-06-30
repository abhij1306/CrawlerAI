"""Authorized publication projection and serialized output stay identical."""

from __future__ import annotations

import pytest

from app.core.records.divergence import compare_public_record_to_projection
from app.extraction.publication import commerce_detail_projection
from app.extraction.contracts import (
    CommerceDetailProjection,
    Decision,
    Evidence,
    PublicationEntry,
    ResolutionResult,
    SourceLocator,
    VariantDecision,
)
from app.extraction.publication import serialize_commerce_detail_projection

pytestmark = pytest.mark.unit


def _projection(*entries: PublicationEntry) -> CommerceDetailProjection:
    return CommerceDetailProjection(
        record_entity_id="product:1",
        entries=entries,
    )


def test_projection_comparator_allows_decimal_representation_change() -> None:
    findings = compare_public_record_to_projection(
        {"price": "89.90"},
        _projection(
            PublicationEntry(
                path="record.price",
                entity_id="offer:1",
                value="89.9",
                selected_fact_id="selected:price",
            )
        ),
        blocking=False,
    )

    assert findings == ()


def test_projection_comparator_reports_missing_authorized_value() -> None:
    findings = compare_public_record_to_projection(
        {},
        _projection(
            PublicationEntry(
                path="record.price",
                entity_id="offer:1",
                value="89.90",
                selected_fact_id="selected:price",
            )
        ),
        blocking=False,
    )

    assert len(findings) == 1
    assert findings[0].blocking is False
    assert findings[0].metadata["reason"] == "authorized_value_missing"


def test_projection_comparator_reports_published_suppressed_value() -> None:
    findings = compare_public_record_to_projection(
        {"price": "89.90"},
        _projection(
            PublicationEntry(
                path="record.price",
                entity_id="offer:1",
                value="89.90",
                disposition="suppress",
                reason_code="currency_unresolved",
                selected_fact_id="selected:price",
            )
        ),
        blocking=True,
    )

    assert len(findings) == 1
    assert findings[0].blocking is True
    assert findings[0].severity == "critical"
    assert findings[0].metadata["reason"] == "suppress_value_published"


def test_projection_comparator_can_report_unauthorized_extra_field() -> None:
    findings = compare_public_record_to_projection(
        {"title": "Trail Shoe", "brand": "Phantom"},
        _projection(
            PublicationEntry(
                path="record.title",
                entity_id="product:1",
                value="Trail Shoe",
                selected_fact_id="selected:title",
            )
        ),
        blocking=True,
        detect_extras=True,
    )

    assert len(findings) == 1
    assert findings[0].metadata["path"] == "record.brand"
    assert findings[0].metadata["reason"] == "unauthorized_public_field"


def test_projection_suppresses_parent_sku_copied_from_multiple_variants() -> None:
    evidence = (
        _fact_evidence("product-sku", "SKU-S", "product.sku"),
        _fact_evidence("variant-s", "SKU-S", "variant.sku"),
        _fact_evidence("variant-m", "SKU-M", "variant.sku"),
    )
    decisions = tuple(
        _fact_decision(
            f"decision:{row.evidence_id}",
            "product:1" if row.fact_type == "product.sku" else row.evidence_id,
            row.fact_type,
            row.evidence_id,
        )
        for row in evidence
    )
    projection, _ = commerce_detail_projection(
        ResolutionResult(
            primary_product_entity_id="product:1",
            decisions=decisions,
            variant_decisions=(
                VariantDecision(
                    variant_entity_id="variant-s",
                    status="eligible",
                    reason_code="variant_eligible",
                    values={"sku": "SKU-S"},
                ),
                VariantDecision(
                    variant_entity_id="variant-m",
                    status="eligible",
                    reason_code="variant_eligible",
                    values={"sku": "SKU-M"},
                ),
            ),
            derived_facts=(),
            unresolved_fact_types=(),
            blocking_finding_ids=(),
        ),
        evidence,
    )

    entry = next(row for row in projection.entries if row.path == "record.sku")
    assert entry.disposition == "suppress"
    assert entry.reason_code == "parent_sku_is_variant_specific"


def test_projection_ignores_rejected_variant_skus_for_parent_sku_policy() -> None:
    evidence = (
        _fact_evidence("product-sku", "SKU-S", "product.sku"),
        _fact_evidence("variant-s", "SKU-S", "variant.sku"),
        _fact_evidence("variant-m", "SKU-M", "variant.sku"),
    )
    decisions = tuple(
        _fact_decision(
            f"decision:{row.evidence_id}",
            "product:1" if row.fact_type == "product.sku" else row.evidence_id,
            row.fact_type,
            row.evidence_id,
        )
        for row in evidence
    )
    projection, _ = commerce_detail_projection(
        ResolutionResult(
            primary_product_entity_id="product:1",
            decisions=decisions,
            variant_decisions=(
                VariantDecision(
                    variant_entity_id="variant-s",
                    status="rejected",
                    reason_code="variant_not_publishable",
                    values={"sku": "SKU-S"},
                ),
                VariantDecision(
                    variant_entity_id="variant-m",
                    status="rejected",
                    reason_code="variant_not_publishable",
                    values={"sku": "SKU-M"},
                ),
            ),
            derived_facts=(),
            unresolved_fact_types=(),
            blocking_finding_ids=(),
        ),
        evidence,
    )

    entry = next(row for row in projection.entries if row.path == "record.sku")
    assert entry.disposition == "publish"
    assert entry.reason_code is None


def test_publication_serializes_only_projection_authorized_variants() -> None:
    record = serialize_commerce_detail_projection(
        CommerceDetailProjection(
            record_entity_id="product:1",
            variant_entity_ids=("variant:kept",),
            entries=(
                PublicationEntry(
                    path="record.url",
                    entity_id="product:1",
                    value="https://example.test/product",
                    selected_fact_id="selected:url",
                ),
                PublicationEntry(
                    path="variant[variant:kept].sku",
                    entity_id="variant:kept",
                    parent_entity_id="product:1",
                    value="SKU-1",
                    selected_fact_id="selected:sku",
                ),
                PublicationEntry(
                    path="variant[variant:kept].color",
                    entity_id="variant:kept",
                    parent_entity_id="product:1",
                    value="Blue",
                    selected_fact_id="selected:color",
                ),
                PublicationEntry(
                    path="variant[variant:dropped].sku",
                    entity_id="variant:dropped",
                    parent_entity_id="product:1",
                    value="SKU-2",
                    disposition="suppress",
                    reason_code="variant_not_publishable",
                    selected_fact_id="selected:dropped-sku",
                ),
            ),
        )
    )

    dumped = record.model_dump(exclude_none=True)
    assert dumped["variants"] == ({"sku": "SKU-1", "color": "Blue"},)
    assert dumped["variant_count"] == 1


def test_projection_suppresses_resolved_price_when_currency_is_unresolved() -> None:
    evidence = (_fact_evidence("price", "19.99", "offer.price"),)
    projection, _ = commerce_detail_projection(
        ResolutionResult(
            primary_product_entity_id="product:1",
            primary_offer_entity_id="offer:1",
            decisions=(
                _fact_decision("decision:price", "offer:1", "offer.price", "price"),
            ),
            derived_facts=(),
            unresolved_fact_types=(),
            blocking_finding_ids=(),
        ),
        evidence,
    )

    entry = next(row for row in projection.entries if row.path == "record.price")
    assert entry.value == "19.99"
    assert entry.disposition == "suppress"
    assert entry.reason_code == "currency_unresolved"


def _fact_evidence(evidence_id: str, value: str, fact_type: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bundle_id="bundle:1",
        artifact_id="html",
        collector_id="jsonld",
        collector_version="1",
        fact_type=fact_type,
        raw_value=value,
        value=value,
        locator=SourceLocator(kind="json_pointer", value=f"/{evidence_id}"),
        directness="embedded",
        confidence=0.9,
        subject_id=evidence_id,
    )


def _fact_decision(
    decision_id: str, entity_id: str, fact_type: str, evidence_id: str
) -> Decision:
    return Decision(
        decision_id=decision_id,
        entity_id=entity_id,
        fact_type=fact_type,
        accepted_evidence_ids=(evidence_id,),
        rejected=(),
        finding_ids=(),
        rule_id="SCALAR_LEXICOGRAPHIC",
        status="resolved",
    )
