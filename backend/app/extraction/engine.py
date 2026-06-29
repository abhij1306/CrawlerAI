from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, cast
from urllib.parse import urlsplit

from app.core.config.extraction_rules import (
    DETAIL_NOT_FOUND_HTTP_STATUS_CODES,
    DETAIL_SHELL_FINDING_RULE_ID,
)
from app.core.records.url_identity import (
    detail_url_is_locale_root,
    detail_urls_conflict,
)
from app.extraction.contracts import (
    CollectorOutcome,
    Decision,
    EntityGraph,
    Evidence,
    ExtractionRequest,
    ExtractionResult,
    Finding,
    PublicRecord,
    ResolutionResult,
    StageOutcome,
    TargetSelection,
)
from app.extraction.entities import EntitySet, build_entities
from app.extraction.ids import stable_id
from app.extraction.jobs import (
    collect_job_detail,
    collect_job_listing,
    wrong_surface_findings_for_job_detail,
)
from app.extraction.job_resolution import (
    materialize_job_detail,
    materialize_job_listing,
    resolve_job_detail,
    resolve_job_listing,
)
from app.extraction.listing import (
    collect_ecommerce_listing,
    materialize_ecommerce_listing,
    resolve_ecommerce_listing,
)
from app.extraction.pipeline import (
    assess_ecommerce_detail_quality,
    collect_ecommerce_detail,
    materialize_ecommerce_detail,
    normalize_ecommerce_detail,
    normalize_ecommerce_price_units,
)
from app.extraction.resolution import resolve as resolve_ecommerce_detail
from app.extraction.result_building import (
    data_integrity_status as _data_integrity_status,
    decisions as _decisions,
    entity_graph as _entity_graph,
    field_evidence_states as _field_evidence_states,
    is_shell_record as _is_shell_record,
    metrics as _metrics,
    retry_request as _retry_request,
)
from app.extraction.surfaces import Surface, SurfaceSpec, surface_spec
from app.extraction.targeting import (
    scoped_graph as _scoped_graph_for_steps,
    select_commerce_target as _select_commerce_target,
    select_subject_targets as _select_subject_targets,
)
from app.extraction.validation import (
    validate as validate_ecommerce_detail,
    validate_selected_contract_fields,
)

ExtractionVerdict = Literal[
    "success",
    "partial",
    "review",
    "invalid",
    "empty",
    "blocked",
    "error",
    "wrong_surface",
]


@dataclass(frozen=True)
class SurfaceRuntime:
    collect: Callable[[ExtractionRequest, SurfaceSpec], tuple[Evidence, ...]]
    normalize: Callable[
        [tuple[Evidence, ...], ExtractionRequest, SurfaceSpec], tuple[Evidence, ...]
    ]
    build_graph: Callable[[tuple[Evidence, ...], ExtractionRequest, SurfaceSpec], Any]
    select_target: Callable[
        [Any, tuple[Evidence, ...], ExtractionRequest, SurfaceSpec], TargetSelection
    ]
    validate: Callable[
        [Any, TargetSelection, tuple[Evidence, ...], ExtractionRequest, SurfaceSpec],
        tuple[Finding, ...],
    ]
    resolve: Callable[
        [
            Any,
            tuple[Evidence, ...],
            tuple[Finding, ...],
            ExtractionRequest,
            SurfaceSpec,
        ],
        Any,
    ]
    materialize: Callable[
        [
            Any,
            Any,
            tuple[Evidence, ...],
            tuple[Finding, ...],
            ExtractionRequest,
            SurfaceSpec,
        ],
        tuple[PublicRecord, ...],
    ]
    assess: Callable[
        [
            tuple[PublicRecord, ...],
            Any,
            tuple[Finding, ...],
            ExtractionRequest,
            SurfaceSpec,
        ],
        str,
    ]


def _stage_outcome(stage: str, produced: int) -> StageOutcome:
    """Record a pipeline stage's outcome from how much it produced.

    A stage that ran clean but produced nothing is ``no_match`` (e.g. no
    findings, no target, no records); otherwise ``produced_evidence``.
    """

    return StageOutcome(
        stage=stage,
        outcome="produced_evidence" if produced else "no_match",
    )


def _collector_outcomes_from_evidence(
    evidence: tuple[Evidence, ...],
) -> tuple[CollectorOutcome, ...]:
    """Derive collector outcomes for surfaces without per-collector capture.

    Honest fallback: only collectors that appear in the collected evidence are
    reported, each as ``produced_evidence`` with its row count.
    """

    counts: dict[str, int] = {}
    for row in evidence:
        counts[row.collector_id] = counts.get(row.collector_id, 0) + 1
    return tuple(
        CollectorOutcome(
            collector_id=collector_id,
            outcome="produced_evidence",
            evidence_count=count,
        )
        for collector_id, count in counts.items()
    )


def extract(request: ExtractionRequest) -> ExtractionResult:
    spec = surface_spec(request.surface)
    runtime = _SURFACE_RUNTIMES[spec.surface]
    stage_outcomes: list[StageOutcome] = []
    evidence = runtime.collect(request, spec)
    collector_outcomes = _collector_outcomes_from_evidence(evidence)
    stage_outcomes.append(_stage_outcome("collect", len(evidence)))
    normalized = runtime.normalize(evidence, request, spec)
    stage_outcomes.append(_stage_outcome("normalize", len(normalized)))
    if request.capture.blocked:
        return _blocked_extraction_result(
            request, normalized, collector_outcomes, tuple(stage_outcomes)
        )
    graph_state = runtime.build_graph(normalized, request, spec)
    target = runtime.select_target(graph_state, normalized, request, spec)
    step_graph = _scoped_graph_for_steps(graph_state, target)
    stage_outcomes.append(_stage_outcome("select_target", len(target.root_entity_ids)))
    if spec.surface == Surface.ECOMMERCE_DETAIL:
        normalized = normalize_ecommerce_price_units(normalized, step_graph)
    findings = runtime.validate(step_graph, target, normalized, request, spec)
    resolution = runtime.resolve(step_graph, normalized, findings, request, spec)
    records = runtime.materialize(
        step_graph, resolution, normalized, findings, request, spec
    )
    stage_outcomes.append(_stage_outcome("materialize", len(records)))
    if spec.surface == Surface.ECOMMERCE_DETAIL:
        findings = (
            *findings,
            *validate_selected_contract_fields(
                records, request.requested_fields, normalized
            ),
        )
    # Validate outcome is recorded AFTER any post-materialize contract-level
    # findings are folded in, so the stage count reflects the final tally.
    stage_outcomes.append(_stage_outcome("validate", len(findings)))
    verdict = cast(
        ExtractionVerdict, runtime.assess(records, resolution, findings, request, spec)
    )
    decisions = _decisions(resolution)
    field_states = _field_evidence_states(
        records,
        normalized,
        decisions,
        request,
        primary_product_entity_id=getattr(
            resolution, "primary_product_entity_id", None
        ),
        primary_offer_entity_id=getattr(resolution, "primary_offer_entity_id", None),
    )
    graph = _entity_graph(graph_state, normalized, spec)
    return ExtractionResult(
        surface=spec.surface,
        bundle_id=request.capture.bundle_id,
        evidence=normalized,
        graph=graph,
        target=target,
        findings=findings,
        decisions=decisions,
        field_states=field_states,
        transport_outcome=request.capture.acquisition_outcome,
        data_integrity=_data_integrity_status(verdict, field_states),
        records=records if verdict in {"success", "partial", "review"} else (),
        verdict=verdict,
        retry_request=_retry_request(verdict, records, request, normalized),
        metrics=_metrics(
            normalized,
            graph,
            target,
            findings,
            decisions,
            records,
            verdict,
            collector_count=len(collector_outcomes),
        ),
        collector_outcomes=collector_outcomes,
        stage_outcomes=tuple(stage_outcomes),
    )


def _blocked_extraction_result(
    request: ExtractionRequest,
    evidence: tuple[Evidence, ...],
    collector_outcomes: tuple[CollectorOutcome, ...] = (),
    stage_outcomes: tuple[StageOutcome, ...] = (),
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
        scope="page",
        entity_ids=(),
        evidence_ids=tuple(row.evidence_id for row in evidence),
        message=(
            "Acquisition ended on a blocked or challenge page; "
            "public records were suppressed."
        ),
        blocking=True,
        metadata={
            "acquisition_outcome": request.capture.acquisition_outcome,
            "http_status": request.capture.http_status,
            "browser_attempted": request.capture.browser_attempted,
        },
    )
    graph = EntityGraph()
    target = TargetSelection(status="missing")
    findings = (finding,)
    field_states = _field_evidence_states((), evidence, (), request)
    return ExtractionResult(
        surface=request.surface,
        bundle_id=request.capture.bundle_id,
        evidence=evidence,
        graph=graph,
        target=target,
        findings=findings,
        decisions=(),
        field_states=field_states,
        transport_outcome=request.capture.acquisition_outcome,
        data_integrity="blocked",
        records=(),
        verdict="blocked",
        retry_request=None,
        metrics=_metrics(
            evidence,
            graph,
            target,
            findings,
            (),
            (),
            "blocked",
            collector_count=len(collector_outcomes),
        ),
        collector_outcomes=collector_outcomes,
        stage_outcomes=stage_outcomes,
    )


def _identity_normalize(
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[Evidence, ...]:
    del request, spec
    return evidence


def _collect_detail(
    request: ExtractionRequest, spec: SurfaceSpec
) -> tuple[Evidence, ...]:
    del spec
    return collect_ecommerce_detail(
        request.capture,
        request.artifact_reader,
        requested_fields=request.requested_fields,
    )


def _collect_listing(
    request: ExtractionRequest, spec: SurfaceSpec
) -> tuple[Evidence, ...]:
    del spec
    return tuple(collect_ecommerce_listing(request.capture, request.artifact_reader))


def _collect_job_detail(
    request: ExtractionRequest, spec: SurfaceSpec
) -> tuple[Evidence, ...]:
    del spec
    return tuple(collect_job_detail(request.capture, request.artifact_reader))


def _collect_job_listing(
    request: ExtractionRequest, spec: SurfaceSpec
) -> tuple[Evidence, ...]:
    del spec
    return tuple(collect_job_listing(request.capture, request.artifact_reader))


def _normalize_detail(
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[Evidence, ...]:
    del spec
    return normalize_ecommerce_detail(evidence, page_url=request.capture.final_url)


def _build_commerce_graph(
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> EntitySet:
    del spec
    return build_entities(request.capture, evidence)


def _build_subject_graph(
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[str, ...]:
    del request, spec
    return tuple(dict.fromkeys(ev.subject_id for ev in evidence if ev.subject_id))


def _validate_detail(
    graph: EntitySet,
    target: TargetSelection,
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[Finding, ...]:
    del spec
    return validate_ecommerce_detail(evidence, graph, request.requested_fields)


def _validate_none(
    graph: Any,
    target: TargetSelection,
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[Finding, ...]:
    del graph, target, evidence, request, spec
    return ()


def _validate_job_detail(
    graph: Any,
    target: TargetSelection,
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[Finding, ...]:
    del graph, target, evidence, spec
    return wrong_surface_findings_for_job_detail(
        request.capture, request.artifact_reader
    )


def _resolve_detail(
    graph: EntitySet,
    evidence: tuple[Evidence, ...],
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> ResolutionResult:
    del request, spec
    return resolve_ecommerce_detail(evidence, graph, findings)


def _resolve_listing(
    graph: Any,
    evidence: tuple[Evidence, ...],
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[Decision, ...]:
    del graph, findings, request, spec
    return tuple(resolve_ecommerce_listing(list(evidence)))


def _resolve_job_detail(
    graph: Any,
    evidence: tuple[Evidence, ...],
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[Decision, ...]:
    del graph, findings, request, spec
    return tuple(resolve_job_detail(list(evidence)))


def _resolve_job_listing(
    graph: Any,
    evidence: tuple[Evidence, ...],
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[Decision, ...]:
    del graph, findings, request, spec
    return tuple(resolve_job_listing(list(evidence)))


def _materialize_detail(
    graph: EntitySet,
    resolution: ResolutionResult,
    evidence: tuple[Evidence, ...],
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[PublicRecord, ...]:
    del findings, spec
    canonical_url = request.capture.final_url or request.capture.requested_url
    source_capabilities = dict(request.capture.acquisition_diagnostics or {}).get(
        "source_capabilities"
    )
    if isinstance(source_capabilities, dict) and source_capabilities.get(
        "terminal_shell"
    ):
        return ()
    if detail_urls_conflict(request.capture.requested_url, canonical_url):
        return ()
    if urlsplit(canonical_url).path in {"", "/"} or detail_url_is_locale_root(
        canonical_url
    ):
        return ()
    if request.capture.http_status in DETAIL_NOT_FOUND_HTTP_STATUS_CODES:
        evidence_by_id = {row.evidence_id: row for row in evidence}
        accepted_title_ids = {
            evidence_id
            for decision in resolution.decisions
            if decision.fact_type == "product.title" and decision.status == "resolved"
            for evidence_id in decision.accepted_evidence_ids
        }
        if not any(
            "url_derived_title" not in evidence_by_id[evidence_id].flags
            for evidence_id in accepted_title_ids
            if evidence_id in evidence_by_id
        ):
            return ()
    record = materialize_ecommerce_detail(
        graph,
        resolution,
        evidence,
        canonical_url=canonical_url,
    )
    if record is None or detail_url_is_locale_root(str(record.url or "")):
        return ()
    return (record,)


def _materialize_listing(
    graph: Any,
    decisions: tuple[Decision, ...],
    evidence: tuple[Evidence, ...],
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[PublicRecord, ...]:
    del graph, findings, spec
    return cast(
        tuple[PublicRecord, ...],
        tuple(
            materialize_ecommerce_listing(
                list(evidence),
                list(decisions),
                max_records=request.max_records,
            )
        ),
    )


def _materialize_job_detail(
    graph: Any,
    decisions: tuple[Decision, ...],
    evidence: tuple[Evidence, ...],
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[PublicRecord, ...]:
    del graph, request, spec
    if any(finding.blocking for finding in findings):
        return ()
    return tuple(materialize_job_detail(list(evidence), list(decisions)))


def _materialize_job_listing(
    graph: Any,
    decisions: tuple[Decision, ...],
    evidence: tuple[Evidence, ...],
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[PublicRecord, ...]:
    del graph, findings, spec
    return tuple(
        materialize_job_listing(
            list(evidence),
            list(decisions),
            max_records=request.max_records,
        )
    )


def _assess_detail(
    records: tuple[PublicRecord, ...],
    resolution: ResolutionResult,
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> str:
    del spec
    record = records[0] if records else None
    if _is_shell_record(record) or any(
        finding.rule_id == DETAIL_SHELL_FINDING_RULE_ID for finding in findings
    ):
        return "error"
    completeness = next(
        (
            float(finding.metadata.get("score", 0.0))
            for finding in findings
            if finding.rule_id == "RECORD_COMPLETENESS"
        ),
        0.0,
    )
    dumped_record = record.model_dump(mode="python") if record is not None else {}
    verdict = assess_ecommerce_detail_quality(
        dumped_record,
        resolution,
        request.capture,
        requested_fields=request.requested_fields,
    )
    if (
        verdict in {"success", "partial"}
        and completeness <= 0.4
        and not dumped_record.get("variants")
    ):
        return "review"
    if verdict == "success" and any(
        finding.rule_id
        in {
            "EXPECTED_VARIANT_AXIS_MISSING",
            "MISSING_CONTRACT_FIELD",
            "VARIANT_AVAILABILITY_MISSING",
        }
        for finding in findings
    ):
        return "partial"
    return verdict


def _assess_records(
    records: tuple[PublicRecord, ...],
    resolution: Any,
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> str:
    del resolution, request
    if any(finding.blocking for finding in findings):
        return "error" if spec.surface == Surface.JOB_DETAIL else "invalid"
    return "success" if records else "empty"


_SURFACE_RUNTIMES: dict[Surface, SurfaceRuntime] = {
    Surface.ECOMMERCE_DETAIL: SurfaceRuntime(
        collect=_collect_detail,
        normalize=_normalize_detail,
        build_graph=_build_commerce_graph,
        select_target=_select_commerce_target,
        validate=_validate_detail,
        resolve=_resolve_detail,
        materialize=_materialize_detail,
        assess=_assess_detail,
    ),
    Surface.ECOMMERCE_LISTING: SurfaceRuntime(
        collect=_collect_listing,
        normalize=_identity_normalize,
        build_graph=_build_subject_graph,
        select_target=_select_subject_targets,
        validate=_validate_none,
        resolve=_resolve_listing,
        materialize=_materialize_listing,
        assess=_assess_records,
    ),
    Surface.JOB_DETAIL: SurfaceRuntime(
        collect=_collect_job_detail,
        normalize=_identity_normalize,
        build_graph=_build_subject_graph,
        select_target=_select_subject_targets,
        validate=_validate_job_detail,
        resolve=_resolve_job_detail,
        materialize=_materialize_job_detail,
        assess=_assess_records,
    ),
    Surface.JOB_LISTING: SurfaceRuntime(
        collect=_collect_job_listing,
        normalize=_identity_normalize,
        build_graph=_build_subject_graph,
        select_target=_select_subject_targets,
        validate=_validate_none,
        resolve=_resolve_job_listing,
        materialize=_materialize_job_listing,
        assess=_assess_records,
    ),
}
