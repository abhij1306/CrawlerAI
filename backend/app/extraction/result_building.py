from __future__ import annotations

from collections import Counter
from typing import Any

from app.core.config.extraction_rules._detail import (
    DETAIL_SHELL_TITLE_FLAG,
    DETAIL_SHELL_TITLE_KEYS,
)
from app.core.shared.text_coerce import slug_tokens
from app.extraction.contracts import (
    Decision,
    EntityGraph,
    Evidence,
    ExtractionMetrics,
    ExtractionRequest,
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


def retry_request(
    verdict: str,
    records: tuple[PublicRecord, ...],
    request: ExtractionRequest,
    evidence: tuple[Evidence, ...] = (),
) -> RetryRequest | None:
    if (
        "variants" in request.requested_fields
        and not any(record.get("variants") for record in records)
        and _explicit_variant_dom_cues(evidence)
    ):
        return RetryRequest(
            required=not request.capture.browser_attempted,
            reason="explicit_variants_missing",
            required_artifacts=("rendered_html", "network_payloads"),
        )
    shell_detected = any(is_shell_record(record) for record in records) or any(
        DETAIL_SHELL_TITLE_FLAG in row.flags for row in evidence
    )
    if verdict != "error" or not shell_detected:
        return None
    return RetryRequest(
        required=not request.capture.browser_attempted,
        reason="http_shell",
        required_artifacts=("rendered_html",),
    )


def _explicit_variant_dom_cues(evidence: tuple[Evidence, ...]) -> bool:
    return any(
        row.collector_id == "dom" and row.fact_type.startswith("option.")
        for row in evidence
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
) -> ExtractionMetrics:
    lineage_fields = sum(len(dict(record.get("_lineage") or {})) for record in records)
    public_fields = sum(
        sum(not str(key).startswith("_") for key in record.model_dump(mode="python"))
        for record in records
    )
    return ExtractionMetrics(
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
        verdict=verdict,
    )
