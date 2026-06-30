from __future__ import annotations

from collections import Counter
import typing
from typing import Any

from app.core.config.extraction_rules._detail import (
    DETAIL_SHELL_TITLE_FLAG,
    DETAIL_SHELL_TITLE_KEYS,
)
from app.core.config import field_mappings
from app.core.shared.text_coerce import slug_tokens
from app.extraction.contracts import (
    Decision,
    EntityGraph,
    Evidence,
    ExtractionMetrics,
    ExtractionRequest,
    FieldEvidenceState,
    Finding,
    PublicRecord,
    ResolutionResult,
    RetryRequest,
    TargetSelection,
)
from app.extraction.entities import EntitySet
from app.extraction.surfaces import SurfaceSpec


def decisions(resolution: Any) -> tuple[Decision, ...]:
    if isinstance(resolution, ResolutionResult):
        return resolution.decisions
    return tuple(resolution or ())


def field_evidence_states(
    records: tuple[PublicRecord, ...],
    evidence: tuple[Evidence, ...],
    decision_rows: tuple[Decision, ...],
    request: ExtractionRequest,
    *,
    primary_product_entity_id: str | None = None,
    primary_offer_entity_id: str | None = None,
) -> tuple[FieldEvidenceState, ...]:
    record = records[0] if records else None
    public_to_fact = {
        "title": field_mappings.PRODUCT_TITLE_FACT_TYPE,
        "brand": field_mappings.PRODUCT_BRAND_FACT_TYPE,
        "description": field_mappings.PRODUCT_DESCRIPTION_FACT_TYPE,
        "sku": field_mappings.PRODUCT_SKU_FACT_TYPE,
        "price": field_mappings.OFFER_PRICE_FACT_TYPE,
        "currency": field_mappings.OFFER_CURRENCY_FACT_TYPE,
        "availability": field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
        "image_url": field_mappings.ASSET_IMAGE_URL_FACT_TYPE,
    }
    requested = {
        "image_url" if field == "image" else field for field in request.requested_fields
    }
    fields = tuple(dict.fromkeys((*public_to_fact, *sorted(requested))))
    source_capabilities = dict(request.capture.acquisition_diagnostics or {}).get(
        "source_capabilities"
    )
    affected = set(
        source_capabilities.get("affected_field_families", ())
        if isinstance(source_capabilities, dict)
        else ()
    )
    by_fact = {
        fact: tuple(row for row in evidence if row.fact_type == fact)
        for fact in set(public_to_fact.values())
    }
    decisions_by_fact = {
        fact: tuple(row for row in decision_rows if row.fact_type == fact)
        for fact in set(public_to_fact.values())
    }
    states: list[FieldEvidenceState] = []
    for field in fields:
        fact = public_to_fact.get(field)
        rows = by_fact.get(fact, ()) if fact else ()
        candidate_decisions = decisions_by_fact.get(fact, ()) if fact else ()
        target_entity_id = (
            primary_offer_entity_id
            if fact
            in {
                field_mappings.OFFER_PRICE_FACT_TYPE,
                field_mappings.OFFER_CURRENCY_FACT_TYPE,
                field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
            }
            else primary_product_entity_id
        )
        relevant_decisions = tuple(
            row
            for row in candidate_decisions
            if target_entity_id is None or row.entity_id == target_entity_id
        )
        present = bool(record and record.get(field) not in (None, "", [], {}, ()))
        state: typing.Literal[
            "captured_and_resolved",
            "captured_but_rejected",
            "captured_conflicting",
            "source_unavailable",
            "not_present_in_captured_sources",
        ]
        if present:
            state = "captured_and_resolved"
            reasons: tuple[str, ...] = ()
        elif field in affected or (field == "image_url" and "images" in affected):
            state = "source_unavailable"
            reasons = ("product_data_source_unavailable",)
        elif any(row.status == "conflicted" for row in relevant_decisions):
            state = "captured_conflicting"
            reasons = tuple(
                sorted(
                    {
                        item.reason
                        for row in relevant_decisions
                        if row.status == "conflicted"
                        for item in row.rejected
                    }
                )
            )
        elif rows:
            state = "captured_but_rejected"
            row_ids = {row.evidence_id for row in rows}
            # Carry the resolver's rejection reasons (RejectedEvidence.reason)
            # for these captured rows so diagnose.json explains *why* a captured
            # sku/availability/price was not published — not just its flags.
            rejection_reasons = {
                item.reason
                for decision in relevant_decisions
                for item in decision.rejected
                if item.evidence_id in row_ids and item.reason
            }
            flag_reasons = {flag for row in rows for flag in row.flags}
            reasons = tuple(sorted(rejection_reasons | flag_reasons))
        else:
            state = "not_present_in_captured_sources"
            reasons = ()
        states.append(
            FieldEvidenceState(
                field=field,
                state=state,
                evidence_ids=tuple(row.evidence_id for row in rows),
                reason_codes=reasons,
            )
        )
    return tuple(states)


def data_integrity_status(
    verdict: str, field_states: tuple[FieldEvidenceState, ...]
) -> typing.Literal["clean", "partial", "defect", "blocked", "unknown"]:
    if verdict == "blocked":
        return "blocked"
    if any(row.state == "captured_conflicting" for row in field_states):
        return "defect"
    if verdict in {"success"}:
        return "clean"
    if verdict in {"partial", "review"}:
        return "partial"
    if verdict in {"invalid", "error"}:
        return "defect"
    return "unknown"


def retry_request(
    verdict: str,
    records: tuple[PublicRecord, ...],
    request: ExtractionRequest,
    evidence: tuple[Evidence, ...] = (),
) -> RetryRequest | None:
    shell_detected = any(is_shell_record(record) for record in records) or any(
        DETAIL_SHELL_TITLE_FLAG in row.flags for row in evidence
    )
    if verdict == "error" and shell_detected:
        return RetryRequest(
            required=not request.capture.browser_attempted,
            reason="http_shell",
            required_artifacts=("rendered_html",),
        )
    ecommerce_detail = request.surface.value == "ecommerce_detail"
    explicit_variants = "variants" in request.requested_fields
    if (
        ecommerce_detail
        and not request.capture.browser_attempted
        and (
            (
                _explicit_variant_dom_cues(evidence)
                and _variant_controls_incomplete(records, evidence)
            )
            or (explicit_variants and _variants_missing_or_incomplete(records))
        )
    ):
        return RetryRequest(
            required=True,
            reason="explicit_variants_missing",
            required_artifacts=("rendered_html", "network_payloads"),
        )
    requested_core_fields = {
        "image_url" if field == "image" else field
        for field in request.requested_fields
        if field
        in {
            "title",
            "brand",
            "description",
            "price",
            "currency",
            "image",
            "image_url",
            "additional_images",
            "sku",
            "availability",
        }
    }
    if (
        ecommerce_detail
        and verdict in {"error", "partial", "review"}
        and not request.capture.browser_attempted
        and (not request.requested_fields or requested_core_fields or not records)
    ):
        record = records[0] if records else PublicRecord()
        target_core_fields = requested_core_fields or {
            "title",
            "price",
            "currency",
            "image_url",
        }
        missing_core_fields = tuple(
            field
            for field in target_core_fields
            if record.get(field) in (None, "", [], {}, ())
        )
        if missing_core_fields or not records:
            return RetryRequest(
                required=True,
                reason="dynamic_content_missing",
                required_artifacts=("rendered_html", "network_payloads"),
            )
    return None


def _explicit_variant_dom_cues(evidence: tuple[Evidence, ...]) -> bool:
    return any(
        row.collector_id == "dom" and row.fact_type.startswith("option.")
        for row in evidence
    )


def _variants_missing_or_incomplete(records: tuple[PublicRecord, ...]) -> bool:
    if not records:
        return True
    variants = tuple(records[0].get("variants") or ())
    if not variants:
        return True
    return any(
        not isinstance(variant, dict)
        or all(
            variant.get(field) in (None, "", [], {}, ())
            for field in ("variant_id", "sku", "size", "color", "style")
        )
        for variant in variants
    )


def _variant_controls_incomplete(
    records: tuple[PublicRecord, ...], evidence: tuple[Evidence, ...]
) -> bool:
    variants = tuple(records[0].get("variants") or ()) if records else ()
    axes = {
        row.fact_type.removeprefix("option.")
        for row in evidence
        if row.collector_id == "dom" and row.fact_type.startswith("option.")
    }
    if not variants:
        return True
    return any(
        any(variant.get(axis) in (None, "", [], {}, ()) for variant in variants)
        for axis in axes
    )


def is_shell_record(record: PublicRecord | None) -> bool:
    title = " ".join(slug_tokens(record.get("title"))) if record else ""
    return bool(title and title in DETAIL_SHELL_TITLE_KEYS)


def entity_graph(
    graph_state: Any,
    evidence: tuple[Evidence, ...],
    spec: SurfaceSpec,
) -> EntityGraph:
    if isinstance(graph_state, EntitySet):
        return EntityGraph(
            root_entity_ids=tuple(
                product.entity_id for product in graph_state.products
            ),
            entity_counts={
                "product": len(graph_state.products),
                "variant": len(graph_state.variants),
                "offer": len(graph_state.offers),
                "asset": len(graph_state.assets),
                "option": sum(
                    len(axis.values)
                    for catalog in graph_state.option_catalogs
                    for axis in catalog.axes
                ),
            },
        )
    roots = tuple(graph_state or ())
    return EntityGraph(
        root_entity_ids=roots,
        entity_counts={
            spec.root_entity: len(roots),
            "evidence_subject": len(
                {row.subject_id for row in evidence if row.subject_id}
            ),
        },
    )


def metrics(
    evidence: tuple[Evidence, ...],
    graph: EntityGraph,
    target: TargetSelection,
    findings: tuple[Finding, ...],
    decision_rows: tuple[Decision, ...],
    records: tuple[PublicRecord, ...],
    verdict: str,
    *,
    collector_count: int = 0,
) -> ExtractionMetrics:
    lineage_fields = sum(len(dict(record.get("_lineage") or {})) for record in records)
    public_fields = sum(
        sum(not str(key).startswith("_") for key in record.model_dump(mode="python"))
        for record in records
    )
    completeness_score = next(
        (
            float(finding.metadata.get("score", 0.0))
            for finding in findings
            if finding.rule_id == "RECORD_COMPLETENESS"
        ),
        0.0,
    )
    return ExtractionMetrics(
        collector_count=collector_count,
        evidence_count=len(evidence),
        entity_counts=graph.entity_counts,
        finding_counts_by_severity=dict(
            Counter(finding.severity for finding in findings)
        ),
        decision_counts_by_status=dict(
            Counter(decision.status for decision in decision_rows)
        ),
        selected_root_ids=target.root_entity_ids,
        variant_count=sum(len(record.get("variants") or []) for record in records),
        public_lineage_coverage=(
            lineage_fields / public_fields if public_fields else 0.0
        ),
        completeness_score=completeness_score,
        verdict=verdict,
    )
