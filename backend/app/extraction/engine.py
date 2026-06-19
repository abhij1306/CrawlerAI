from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.extraction.contracts import (
    Decision,
    Evidence,
    ExtractionMetrics,
    ExtractionRequest,
    ExtractionResult,
    Finding,
    PublicRecord,
    ResolutionResult,
    TargetSelection,
)
from app.extraction.entities import EntitySet, build_entities
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
)
from app.extraction.resolution import resolve as resolve_ecommerce_detail
from app.extraction.result_building import (
    decisions as _decisions,
    entity_graph as _entity_graph,
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
from app.extraction.validation import validate as validate_ecommerce_detail


@dataclass(frozen=True)
class SurfaceRuntime:
    collect: Callable[[ExtractionRequest, SurfaceSpec], tuple[Evidence, ...]]
    normalize: Callable[[tuple[Evidence, ...], ExtractionRequest, SurfaceSpec], tuple[Evidence, ...]]
    build_graph: Callable[[tuple[Evidence, ...], ExtractionRequest, SurfaceSpec], Any]
    select_target: Callable[[Any, tuple[Evidence, ...], ExtractionRequest, SurfaceSpec], TargetSelection]
    validate: Callable[[Any, TargetSelection, tuple[Evidence, ...], ExtractionRequest, SurfaceSpec], tuple[Finding, ...]]
    resolve: Callable[[Any, tuple[Evidence, ...], tuple[Finding, ...], ExtractionRequest, SurfaceSpec], Any]
    materialize: Callable[[Any, Any, tuple[Evidence, ...], tuple[Finding, ...], ExtractionRequest, SurfaceSpec], tuple[PublicRecord, ...]]
    assess: Callable[[tuple[PublicRecord, ...], Any, tuple[Finding, ...], ExtractionRequest, SurfaceSpec], str]


def extract(request: ExtractionRequest) -> ExtractionResult:
    spec = surface_spec(request.surface)
    runtime = _SURFACE_RUNTIMES[spec.surface]
    evidence = runtime.collect(request, spec)
    normalized = runtime.normalize(evidence, request, spec)
    graph_state = runtime.build_graph(normalized, request, spec)
    target = runtime.select_target(graph_state, normalized, request, spec)
    step_graph = _scoped_graph_for_steps(graph_state, target)
    findings = runtime.validate(step_graph, target, normalized, request, spec)
    resolution = runtime.resolve(step_graph, normalized, findings, request, spec)
    records = runtime.materialize(step_graph, resolution, normalized, findings, request, spec)
    verdict = runtime.assess(records, resolution, findings, request, spec)
    decisions = _decisions(resolution)
    graph = _entity_graph(graph_state, normalized, spec)
    return ExtractionResult(
        surface=spec.surface,
        bundle_id=request.capture.bundle_id,
        evidence=normalized,
        graph=graph,
        target=target,
        findings=findings,
        decisions=decisions,
        records=records if verdict in {"success", "partial", "review"} else (),
        verdict=verdict,
        retry_request=_retry_request(verdict, records, request),
        metrics=_metrics(normalized, graph, target, findings, decisions, records, verdict),
    )


def _identity_normalize(
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[Evidence, ...]:
    del request, spec
    return evidence


def _collect_detail(request: ExtractionRequest, spec: SurfaceSpec) -> tuple[Evidence, ...]:
    del spec
    return collect_ecommerce_detail(
        request.capture,
        request.artifact_reader,
        requested_fields=request.requested_fields,
    )


def _collect_listing(request: ExtractionRequest, spec: SurfaceSpec) -> tuple[Evidence, ...]:
    del spec
    return tuple(collect_ecommerce_listing(request.capture, request.artifact_reader))


def _collect_job_detail(request: ExtractionRequest, spec: SurfaceSpec) -> tuple[Evidence, ...]:
    del spec
    return tuple(collect_job_detail(request.capture, request.artifact_reader))


def _collect_job_listing(request: ExtractionRequest, spec: SurfaceSpec) -> tuple[Evidence, ...]:
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
    return wrong_surface_findings_for_job_detail(request.capture, request.artifact_reader)


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
    del findings, request, spec
    record = materialize_ecommerce_detail(graph, resolution, evidence)
    return (record,) if record else ()


def _materialize_listing(
    graph: Any,
    decisions: tuple[Decision, ...],
    evidence: tuple[Evidence, ...],
    findings: tuple[Finding, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> tuple[PublicRecord, ...]:
    del graph, findings, spec
    return tuple(
        materialize_ecommerce_listing(
            list(evidence),
            list(decisions),
            max_records=request.max_records,
        )
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
    del findings, spec
    record = records[0] if records else None
    if _is_shell_record(record):
        return "error"
    return assess_ecommerce_detail_quality(
        record.model_dump(mode="python") if record is not None else {},
        resolution,
        request.capture,
    )


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
