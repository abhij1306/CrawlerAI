"""Common extraction orchestration: Harvest → Resolve → Publish."""

from __future__ import annotations

from time import perf_counter
from typing import Literal, cast

from app.core.config.extraction_rules import (
    DETAIL_NOT_FOUND_HTTP_STATUS_CODES,
    DETAIL_SHELL_FINDING_RULE_ID,
)
from app.extraction.adapters import adapter_for
from app.extraction.contracts import (
    EntityGraph,
    Evidence,
    ExtractionRequest,
    ExtractionResult,
    Finding,
    PublicRecord,
    StageOutcome,
    TargetSelection,
)
from app.core.shared.ids import stable_id
from app.extraction.result_building import (
    assert_resolution_accounting,
    data_integrity_status,
    evidence_dispositions,
    field_evidence_states,
    is_shell_record,
    metrics,
    retry_request,
)
from app.extraction.surfaces import Surface
from app.extraction.validation import validate_selected_contract_fields

Verdict = Literal[
    "success",
    "partial",
    "review",
    "invalid",
    "empty",
    "blocked",
    "error",
    "wrong_surface",
]


def extract(request: ExtractionRequest) -> ExtractionResult:
    if request.capture.blocked:
        return _blocked_result(request, (), ())
    adapter = adapter_for(request.surface)
    harvest = adapter.harvest(request)
    stage_outcomes = [_stage_outcome("harvest", len(harvest.evidence))]

    resolve_started = perf_counter()
    resolution = adapter.resolve(request, harvest)
    resolve_duration_ms = (perf_counter() - resolve_started) * 1_000
    stage_outcomes.append(_stage_outcome("resolve", len(resolution.decisions)))

    publish_started = perf_counter()
    publication = adapter.publish(resolution)
    publish_duration_ms = (perf_counter() - publish_started) * 1_000
    stage_outcomes.append(_stage_outcome("publish", len(publication.records)))

    publication_validation = (
        validate_selected_contract_fields(
            publication.records,
            request.requested_fields,
            harvest.evidence,
        )
        if request.surface == Surface.ECOMMERCE_DETAIL
        else ()
    )
    findings = (
        *resolution.findings,
        *publication.findings,
        *publication_validation,
    )
    verdict = _assess(request, resolution.target, publication.records, findings)
    records = publication.records if verdict in {"success", "partial", "review"} else ()
    stage_outcomes.append(_stage_outcome("validate", len(findings)))
    return ExtractionResult(
        surface=request.surface,
        bundle_id=request.capture.bundle_id,
        evidence=harvest.evidence,
        graph=resolution.graph,
        target=resolution.target,
        findings=findings,
        decisions=resolution.decisions,
        selected_facts=resolution.selected_facts,
        derived_facts=resolution.derived_facts,
        evidence_dispositions=resolution.evidence_dispositions,
        field_states=resolution.field_states,
        transport_outcome=request.capture.acquisition_outcome,
        data_integrity=data_integrity_status(
            verdict, resolution.field_states, findings
        ),
        records=records,
        verdict=verdict,
        retry_request=retry_request(
            verdict, publication.records, request, harvest.evidence
        ),
        metrics=metrics(
            harvest.evidence,
            resolution.graph,
            resolution.target,
            findings,
            resolution.decisions,
            publication.records,
            verdict,
            collector_count=len(harvest.collector_outcomes),
            resolve_duration_ms=resolve_duration_ms,
            publish_duration_ms=publish_duration_ms,
        ),
        collector_outcomes=harvest.collector_outcomes,
        stage_outcomes=tuple(stage_outcomes),
        contract_outcomes=resolution.contract_outcomes,
    )


def _assess(
    request: ExtractionRequest,
    target: TargetSelection,
    records: tuple[PublicRecord, ...],
    findings: tuple[Finding, ...],
) -> Verdict:
    if request.capture.acquisition_outcome in {"blocked", "error"}:
        return cast(Verdict, request.capture.acquisition_outcome)
    if any(row.rule_id == "PUBLIC_RESOLUTION_DIVERGENCE" for row in findings):
        return "invalid"
    wrong_surface = any(row.rule_id == "WRONG_SURFACE_CONTENT" for row in findings)
    if request.surface == Surface.ECOMMERCE_DETAIL:
        record = records[0] if records else None
        thin_not_found = (
            request.capture.http_status in DETAIL_NOT_FOUND_HTTP_STATUS_CODES
            and (
                record is None
                or not any(
                    record.get(field) not in (None, "", [], {}, ())
                    for field in (
                        "brand",
                        "description",
                        "image_url",
                        "price",
                        "sku",
                        "variants",
                    )
                )
            )
        )
        if (
            (record is not None and is_shell_record(record))
            or any(row.rule_id == DETAIL_SHELL_FINDING_RULE_ID for row in findings)
            or thin_not_found
        ):
            return "error"
    if any(row.blocking for row in findings if row.rule_id != "WRONG_SURFACE_CONTENT"):
        return "invalid"
    if wrong_surface:
        return "empty" if not records else "review"
    if target.status == "ambiguous":
        return "invalid" if request.surface == Surface.JOB_DETAIL else "review"
    if not records:
        return "empty"
    if request.surface == Surface.ECOMMERCE_DETAIL:
        record = records[0]
        missing_requested = {
            "image_url" if field == "image" else field
            for field in request.requested_fields
            if record.get("image_url" if field == "image" else field)
            in (None, "", [], {}, ())
        }
        if missing_requested or any(
            row.rule_id
            in {
                "EXPECTED_VARIANT_AXIS_MISSING",
                "MISSING_CONTRACT_FIELD",
                "VARIANT_AVAILABILITY_MISSING",
            }
            for row in findings
        ):
            return "partial"
        if target.status != "resolved":
            return "review"
    return "success"


def _blocked_result(
    request: ExtractionRequest,
    evidence: tuple[Evidence, ...],
    collector_outcomes,
) -> ExtractionResult:
    finding = Finding(
        finding_id=stable_id(
            "finding",
            request.capture.bundle_id,
            "ACQUISITION_BLOCKED",
            request.capture.acquisition_outcome,
        ),
        rule_id="ACQUISITION_BLOCKED",
        severity="critical",
        scope="artifact",
        entity_ids=(),
        evidence_ids=(),
        message="Acquisition was blocked before extraction.",
        blocking=True,
    )
    target = TargetSelection(status="missing")
    dispositions = evidence_dispositions(evidence, (), (), target)
    assert_resolution_accounting(evidence, (), (), dispositions)
    states = field_evidence_states((), evidence, (), request)
    return ExtractionResult(
        surface=request.surface,
        bundle_id=request.capture.bundle_id,
        evidence=evidence,
        graph=EntityGraph(),
        target=target,
        findings=(finding,),
        decisions=(),
        selected_facts=(),
        derived_facts=(),
        evidence_dispositions=dispositions,
        field_states=states,
        transport_outcome=request.capture.acquisition_outcome,
        data_integrity="blocked",
        records=(),
        verdict="blocked",
        retry_request=None,
        metrics=metrics(
            evidence,
            EntityGraph(),
            target,
            (finding,),
            (),
            (),
            "blocked",
            collector_count=len(collector_outcomes),
        ),
        collector_outcomes=tuple(collector_outcomes),
        stage_outcomes=(_stage_outcome("harvest", len(evidence)),),
    )


def _stage_outcome(stage: str, produced: int) -> StageOutcome:
    return StageOutcome(
        stage=stage,
        outcome="produced_evidence" if produced else "no_match",
    )
