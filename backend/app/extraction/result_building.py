from __future__ import annotations

from collections import Counter
import typing
from typing import Any

from app.core.config.extraction_rules._detail import (
    DETAIL_SHELL_TITLE_FLAG,
    DETAIL_SHELL_TITLE_KEYS,
)
from app.core.config import field_mappings
from app.core.config.variant_policy import CHILD_JOIN_FAILED_RULE_ID
from app.core.config.variant_policy import DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
from app.core.records.field_policy import canonical_fields_for_surface
from app.core.shared.text_coerce import slug_tokens
from app.extraction.contracts import (
    Decision,
    EvidenceDisposition,
    EntityGraph,
    Evidence,
    ExtractionMetrics,
    ExtractionRequest,
    FieldEvidenceState,
    Finding,
    PublicationProjection,
    PublicRecord,
    ResolutionResult,
    RetryRequest,
    SelectedFact,
    TargetSelection,
)
from app.extraction.entities import EntitySet
from app.extraction.field_states import FieldStateName, field_state
from app.core.shared.ids import stable_id
from app.extraction.surfaces import SurfaceSpec


def decisions(resolution: Any) -> tuple[Decision, ...]:
    if isinstance(resolution, ResolutionResult):
        return resolution.decisions
    return tuple(resolution or ())


def selected_facts(
    decision_rows: tuple[Decision, ...], evidence: tuple[Evidence, ...]
) -> tuple[SelectedFact, ...]:
    """Build direct resolved truth. Inheritance remains derived truth."""

    evidence_by_id = {row.evidence_id: row for row in evidence}
    facts: list[SelectedFact] = []
    for decision in decision_rows:
        if (
            decision.status != "resolved"
            or len(decision.accepted_evidence_ids) != 1
            or decision.rule_id == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
        ):
            continue
        accepted = evidence_by_id.get(decision.accepted_evidence_ids[0])
        if accepted is None:
            continue
        facts.append(
            SelectedFact(
                selected_fact_id=stable_id("selected", decision.decision_id),
                decision_id=decision.decision_id,
                entity_id=decision.entity_id,
                fact_type=decision.fact_type,
                value=accepted.value,
                evidence_ids=decision.accepted_evidence_ids,
                rule_id=decision.rule_id,
            )
        )
    return tuple(facts)


def assert_resolution_accounting(
    evidence: tuple[Evidence, ...],
    decisions: tuple[Decision, ...],
    selected_rows: tuple[SelectedFact, ...],
    dispositions: tuple[EvidenceDisposition, ...],
) -> None:
    """Fail closed when resolution accounting stops being exact."""

    evidence_ids = [row.evidence_id for row in evidence]
    disposition_ids = [row.evidence_id for row in dispositions]
    if Counter(evidence_ids) != Counter(disposition_ids):
        raise RuntimeError("every evidence row must have exactly one disposition")
    evidence_by_id = {row.evidence_id: row for row in evidence}
    decisions_by_id = {row.decision_id: row for row in decisions}
    for selected in selected_rows:
        decision = decisions_by_id.get(selected.decision_id)
        if decision is None:
            raise RuntimeError("selected fact references a missing decision")
        if selected.evidence_ids != decision.accepted_evidence_ids:
            raise RuntimeError(
                "selected fact evidence does not match accepted evidence"
            )
        if len(selected.evidence_ids) != 1:
            raise RuntimeError(
                "selected facts must represent one direct evidence value"
            )
        accepted = evidence_by_id.get(selected.evidence_ids[0])
        if accepted is None:
            raise RuntimeError("selected fact references missing evidence")
        if selected.value != accepted.value:
            raise RuntimeError("selected fact value diverges from accepted evidence")


def evidence_dispositions(
    evidence: tuple[Evidence, ...],
    decision_rows: tuple[Decision, ...],
    selected_rows: tuple[SelectedFact, ...],
    target: TargetSelection | None = None,
) -> tuple[EvidenceDisposition, ...]:
    """Assign exactly one terminal accounting state to every evidence row."""

    selected_by_evidence = {
        evidence_id: row for row in selected_rows for evidence_id in row.evidence_ids
    }
    accepted_by_evidence: dict[str, Decision] = {}
    rejected_by_evidence: dict[str, tuple[Decision, str]] = {}
    for decision in decision_rows:
        for evidence_id in decision.accepted_evidence_ids:
            accepted_by_evidence.setdefault(evidence_id, decision)
        for rejected in decision.rejected:
            rejected_by_evidence.setdefault(
                rejected.evidence_id, (decision, rejected.reason)
            )
    return tuple(
        _evidence_disposition(
            row,
            accepted_by_evidence.get(row.evidence_id),
            rejected_by_evidence.get(row.evidence_id),
            selected_by_evidence.get(row.evidence_id),
            target,
        )
        for row in evidence
    )


def _evidence_disposition(
    evidence: Evidence,
    accepted: Decision | None,
    rejected: tuple[Decision, str] | None,
    selected: SelectedFact | None,
    target: TargetSelection | None,
) -> EvidenceDisposition:
    if accepted is not None:
        return EvidenceDisposition(
            evidence_id=evidence.evidence_id,
            entity_id=accepted.entity_id,
            status="conflicted" if accepted.status == "conflicted" else "accepted",
            reason_code=accepted.rule_id,
            decision_id=accepted.decision_id,
            selected_fact_id=selected.selected_fact_id if selected else None,
        )
    if rejected is not None:
        decision, reason = rejected
        invalid = reason not in {"lower_confidence", "stable_tiebreak"}
        return EvidenceDisposition(
            evidence_id=evidence.evidence_id,
            entity_id=decision.entity_id,
            status="rejected_invalid" if invalid else "rejected_lower_rank",
            reason_code=reason,
            decision_id=decision.decision_id,
        )
    if target is not None and target.status in {"ambiguous", "missing"}:
        return EvidenceDisposition(
            evidence_id=evidence.evidence_id,
            entity_id=evidence.subject_id,
            status="unowned",
            reason_code=f"target_{target.status}",
        )
    if (
        target is not None
        and target.status == "resolved"
        and target.root_entity_ids
        and evidence.subject_id
        and evidence.subject_id not in set(target.root_entity_ids)
    ):
        return EvidenceDisposition(
            evidence_id=evidence.evidence_id,
            entity_id=evidence.subject_id,
            status="outside_selected_target",
            reason_code="outside_selected_target",
        )
    return EvidenceDisposition(
        evidence_id=evidence.evidence_id,
        status="diagnostic_only",
        reason_code="not_considered_by_current_resolver",
    )


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
    public_to_fact = field_mappings.ECOMMERCE_PUBLIC_FIELD_FACT_TYPES
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
        resolved_decision = any(
            row.status == "resolved" and row.accepted_evidence_ids
            for row in relevant_decisions
        )
        state: FieldStateName
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
        elif resolved_decision:
            # Resolution accepted a value for this field, but publication policy
            # suppressed it. Authoritative state comes from the decision graph,
            # so this is a rejection with a reason, never a silent miss.
            state = "captured_but_rejected"
            reasons = ("withheld_after_resolution",)
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
            field_state(
                field=field,
                state=state,
                evidence_ids=(row.evidence_id for row in rows),
                reason_codes=reasons,
            )
        )
    return tuple(states)


def projection_field_states(
    projection: PublicationProjection,
    evidence: tuple[Evidence, ...],
    dispositions: tuple[EvidenceDisposition, ...],
    request: ExtractionRequest,
    findings: tuple[Finding, ...] = (),
) -> tuple[FieldEvidenceState, ...]:
    """Derive field state from evidence and publication policy, never records."""

    entries_by_field: dict[str, list] = {}
    for entry in projection.entries:
        field = (
            "image_url"
            if entry.path.startswith("asset[") and entry.path.endswith(".url")
            else entry.path.rsplit(".", 1)[-1]
        )
        entries_by_field.setdefault(field, []).append(entry)
    requested = {
        "image_url" if field == "image" else field for field in request.requested_fields
    }
    surface_fields = {
        "url" if field == "canonical_url" else field
        for field in canonical_fields_for_surface(request.surface.value)
    }
    contract_required = set(
        field_mappings.SURFACE_FIELD_REPAIR_TARGETS.get(request.surface.value, ())
    )
    disposition_by_id = {row.evidence_id: row for row in dispositions}
    join_failed_evidence_ids = {
        evidence_id
        for finding in findings
        if finding.rule_id == CHILD_JOIN_FAILED_RULE_ID
        for evidence_id in finding.evidence_ids
    }
    source_capabilities = dict(request.capture.acquisition_diagnostics or {}).get(
        "source_capabilities"
    )
    unavailable_families = set(
        source_capabilities.get("affected_field_families", ())
        if isinstance(source_capabilities, dict)
        else ()
    )
    fact_by_field = {
        **field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES,
        "title": "job.title"
        if request.surface.value.startswith("job_")
        else "product.title",
        "url": "job.url" if request.surface.value.startswith("job_") else "product.url",
        "company": "job.company",
        "location": "job.location",
        "apply_url": "job.apply_url",
        "job_id": "job.id",
        "job_type": "job.type",
        "posted_date": "job.posted_date",
        "image_url": "asset.image_url",
    }
    for fact_type in field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES.values():
        field = fact_type.rsplit(".", 1)[-1]
        fact_by_field.setdefault(field, fact_type)
    field_by_fact = {
        fact_type: field for field, fact_type in fact_by_field.items() if fact_type
    }
    evidence_fields = {
        field_by_fact[row.fact_type]
        for row in evidence
        if row.fact_type in field_by_fact
    }
    fields = tuple(
        sorted(
            surface_fields
            | contract_required
            | requested
            | set(entries_by_field)
            | evidence_fields
        )
    )
    states: list[FieldEvidenceState] = []
    for field in fields:
        state: FieldStateName
        entries = entries_by_field.get(field, [])
        variant_entity_ids = tuple(getattr(projection, "variant_entity_ids", ()) or ())
        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id for entry in entries for evidence_id in entry.evidence_ids
            )
        )
        if field == "variants" and variant_entity_ids:
            state = "captured_published"
        elif any(entry.disposition == "publish" for entry in entries):
            state = "captured_published"
        elif any(entry.disposition == "suppress" for entry in entries):
            state = "captured_suppressed"
        elif any(entry.disposition == "review" for entry in entries):
            state = "captured_conflicting"
        else:
            fact_type = fact_by_field.get(field, field)
            candidates = tuple(row for row in evidence if row.fact_type == fact_type)
            evidence_ids = tuple(row.evidence_id for row in candidates)
            candidate_dispositions = tuple(
                disposition_by_id[row.evidence_id]
                for row in candidates
                if row.evidence_id in disposition_by_id
            )
            if field in unavailable_families or (
                field == "image_url" and "images" in unavailable_families
            ):
                state = "source_unavailable"
            elif any(row.evidence_id in join_failed_evidence_ids for row in candidates):
                state = "join_failed"
            elif any(row.status == "unowned" for row in candidate_dispositions):
                state = "captured_unowned"
            elif any(row.status == "conflicted" for row in candidate_dispositions):
                state = "captured_conflicting"
            elif candidates:
                state = "captured_but_rejected"
            elif field in requested or field in contract_required:
                state = "not_present_in_captured_sources"
            else:
                state = "not_requested"
        disposition_reason_codes = tuple(
            row.reason_code
            for evidence_id in evidence_ids
            if (row := disposition_by_id.get(evidence_id)) is not None
            and row.reason_code
        )
        state_reason_codes = (
            ("product_data_source_unavailable",)
            if state == "source_unavailable"
            else ()
        )
        states.append(
            field_state(
                field=field,
                state=state,
                evidence_ids=evidence_ids,
                reason_codes=(
                    *(entry.reason_code for entry in entries if entry.reason_code),
                    *(code for code in disposition_reason_codes if code),
                    *state_reason_codes,
                ),
            )
        )
    return tuple(states)


def data_integrity_status(
    verdict: str,
    field_states: tuple[FieldEvidenceState, ...],
    findings: tuple[Finding, ...] = (),
) -> typing.Literal["clean", "partial", "defect", "blocked", "unknown", "divergent"]:
    if any(row.rule_id == "PUBLIC_RESOLUTION_DIVERGENCE" for row in findings):
        return "divergent"
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
        if field in field_mappings.ECOMMERCE_DETAIL_REQUESTED_CORE_FIELDS
    }
    if (
        ecommerce_detail
        and verdict in {"error", "partial", "review"}
        and not request.capture.browser_attempted
        and (not request.requested_fields or requested_core_fields or not records)
    ):
        record = records[0] if records else PublicRecord()
        target_core_fields = requested_core_fields or set(
            field_mappings.ECOMMERCE_DETAIL_DYNAMIC_RETRY_CORE_FIELDS
        )
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
    resolve_duration_ms: float = 0.0,
    publish_duration_ms: float = 0.0,
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
        resolve_duration_ms=resolve_duration_ms,
        publish_duration_ms=publish_duration_ms,
    )
