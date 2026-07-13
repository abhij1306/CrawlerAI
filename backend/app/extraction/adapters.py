"""Four surface discovery adapters behind one harvest and resolve contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, cast

from app.core.shared.ids import stable_id
from app.extraction.contracts import (
    CollectorOutcome,
    Decision,
    Evidence,
    ExtractionRequest,
    Finding,
    HarvestResult,
    JobDetailProjection,
    ResolutionEnvelope,
    TargetSelection,
)
from app.extraction.entities import EntitySet, build_entities
from app.extraction.jobs import (
    collect_job_detail,
    resolve_job_detail,
    resolve_job_listing,
    wrong_surface_findings_for_job_detail,
)
from app.extraction.listing import resolve_ecommerce_listing
from app.extraction.listing_tier0 import collect_deterministic_listing
from app.extraction.pipeline import harvest_ecommerce_detail, normalize_ecommerce_detail
from app.extraction.publication import (
    commerce_detail_projection,
    commerce_listing_projection,
    job_detail_projection,
    job_listing_projection,
)
from app.extraction.resolution import resolve as resolve_ecommerce_detail
from app.extraction.surfaces import Surface
from app.extraction.targeting import (
    scoped_graph,
    select_commerce_target,
    select_subject_targets,
)
from app.extraction.validation import validate as validate_ecommerce_detail


@dataclass(frozen=True)
class SurfaceAdapter:
    harvest: Callable[[ExtractionRequest], HarvestResult]
    resolve: Callable[[ExtractionRequest, HarvestResult], ResolutionEnvelope]


def adapter_for(surface: Surface) -> SurfaceAdapter:
    return _ADAPTERS[surface]


def _harvest_detail(request: ExtractionRequest) -> HarvestResult:
    harvested = harvest_ecommerce_detail(
        request.capture,
        request.artifact_reader,
        requested_fields=request.requested_fields,
    )
    normalized = normalize_ecommerce_detail(
        harvested.evidence,
        page_url=request.capture.final_url or request.capture.requested_url,
        locale_hint=_request_locale_hint(request),
    )
    _assert_representation_only(harvested.evidence, normalized)
    return harvested.model_copy(update={"evidence": normalized})


def _request_locale_hint(request: ExtractionRequest) -> str | None:
    context = request.capture.request_context
    return context.locale or context.country


def _harvest_listing(request: ExtractionRequest) -> HarvestResult:
    return _harvest_structured_listing(request)


def _harvest_job_detail(request: ExtractionRequest) -> HarvestResult:
    return _harvest_from_rows(
        Surface.JOB_DETAIL,
        tuple(collect_job_detail(request.capture, request.artifact_reader)),
    )


def _harvest_job_listing(request: ExtractionRequest) -> HarvestResult:
    return _harvest_structured_listing(request)


def _harvest_structured_listing(request: ExtractionRequest) -> HarvestResult:
    rows = tuple(
        collect_deterministic_listing(
            request.capture,
            request.artifact_reader,
            surface=request.surface,
        )
    )
    return _harvest_from_rows(request.surface, rows)


def _harvest_from_rows(surface: Surface, rows: tuple[Evidence, ...]) -> HarvestResult:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.collector_id] = counts.get(row.collector_id, 0) + 1
    return HarvestResult(
        surface=surface,
        evidence=rows,
        collector_outcomes=tuple(
            CollectorOutcome(
                collector_id=collector_id,
                outcome="produced_evidence",
                evidence_count=count,
            )
            for collector_id, count in sorted(counts.items())
        ),
        admitted_source_objects=len({row.subject_id for row in rows}),
    )


def _resolve_detail(
    request: ExtractionRequest, harvest: HarvestResult
) -> ResolutionEnvelope:
    evidence = harvest.evidence
    graph_state = build_entities(request.capture, evidence)
    graph = scoped_graph(
        graph_state,
        target := select_commerce_target(
            graph_state, evidence, request, _surface_spec(request)
        ),
    )
    findings = validate_ecommerce_detail(evidence, graph, request.requested_fields)
    resolution = resolve_ecommerce_detail(
        evidence,
        cast(EntitySet, graph),
        findings,
    )
    projection, _selected = commerce_detail_projection(resolution, evidence)
    return ResolutionEnvelope(
        surface=request.surface,
        target=target,
        findings=findings,
        publication=projection,
    )


def _resolve_listing(
    request: ExtractionRequest, harvest: HarvestResult
) -> ResolutionEnvelope:
    target = select_subject_targets(
        _subject_graph(harvest.evidence),
        harvest.evidence,
        request,
        _surface_spec(request),
    )
    selected_subjects = set(target.root_entity_ids)
    decisions = tuple(
        resolve_ecommerce_listing(
            [row for row in harvest.evidence if row.subject_id in selected_subjects]
        )
    )
    findings = _incomplete_record_findings(
        target.root_entity_ids,
        decisions,
        required={"product.title", "product.url"},
        rule_id="INCOMPLETE_COMMERCE_LISTING_CARD",
    )
    projection, _selected = commerce_listing_projection(
        decisions, harvest.evidence, max_records=request.max_records
    )
    return ResolutionEnvelope(
        surface=request.surface,
        target=target,
        findings=findings,
        publication=projection,
    )


def _resolve_job_detail_adapter(
    request: ExtractionRequest, harvest: HarvestResult
) -> ResolutionEnvelope:
    target = select_subject_targets(
        _subject_graph(harvest.evidence),
        harvest.evidence,
        request,
        _surface_spec(request),
    )
    findings = wrong_surface_findings_for_job_detail(
        request.capture, request.artifact_reader
    )
    if findings:
        return ResolutionEnvelope(
            surface=request.surface,
            target=TargetSelection(status="wrong_surface"),
            findings=findings,
            publication=JobDetailProjection(record_entity_id=""),
        )
    if target.status == "ambiguous":
        findings = (
            *findings,
            Finding(
                finding_id=stable_id(
                    "finding", request.capture.bundle_id, "AMBIGUOUS_JOB_ROOT"
                ),
                rule_id="AMBIGUOUS_JOB_ROOT",
                severity="critical",
                scope="page",
                entity_ids=target.root_entity_ids,
                evidence_ids=(),
                message="Competing JobPosting roots cannot be selected safely.",
                blocking=True,
            ),
        )
    entity_id = target.selected_root_entity_id
    decisions = (
        tuple(
            resolve_job_detail(
                [row for row in harvest.evidence if row.subject_id == entity_id]
            )
        )
        if entity_id
        else ()
    )
    projection, _selected = job_detail_projection(
        decisions, harvest.evidence, target_entity_id=entity_id
    )
    return ResolutionEnvelope(
        surface=request.surface,
        target=target,
        findings=findings,
        publication=projection,
    )


def _resolve_job_listing_adapter(
    request: ExtractionRequest, harvest: HarvestResult
) -> ResolutionEnvelope:
    target = select_subject_targets(
        _subject_graph(harvest.evidence),
        harvest.evidence,
        request,
        _surface_spec(request),
    )
    selected_subjects = set(target.root_entity_ids)
    decisions = tuple(
        resolve_job_listing(
            [row for row in harvest.evidence if row.subject_id in selected_subjects]
        )
    )
    findings = _incomplete_record_findings(
        target.root_entity_ids,
        decisions,
        required={"job.title", "job.url"},
        rule_id="INCOMPLETE_JOB_LISTING_CARD",
    )
    projection, _selected = job_listing_projection(
        decisions, harvest.evidence, max_records=request.max_records
    )
    return ResolutionEnvelope(
        surface=request.surface,
        target=target,
        findings=findings,
        publication=projection,
    )


def _subject_graph(evidence: tuple[Evidence, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(row.subject_id for row in evidence if row.subject_id))


def _incomplete_record_findings(
    entity_ids: tuple[str, ...],
    decisions: tuple[Decision, ...],
    *,
    required: set[str],
    rule_id: str,
) -> tuple[Finding, ...]:
    resolved = {
        (row.entity_id, row.fact_type) for row in decisions if row.status == "resolved"
    }
    return tuple(
        Finding(
            finding_id=stable_id("finding", rule_id, entity_id, tuple(missing)),
            rule_id=rule_id,
            severity="info",
            scope="entity",
            entity_ids=(entity_id,),
            evidence_ids=(),
            message=f"Candidate omitted; missing required facts: {', '.join(missing)}.",
            blocking=False,
            metadata={"missing_fact_types": missing},
        )
        for entity_id in entity_ids
        if (
            missing := tuple(
                sorted(
                    fact_type
                    for fact_type in required
                    if (entity_id, fact_type) not in resolved
                )
            )
        )
    )


def _assert_representation_only(
    before: tuple[Evidence, ...], after: tuple[Evidence, ...]
) -> None:
    before_identity = tuple(
        (
            row.evidence_id,
            row.fact_type,
            row.subject_id,
            row.parent_subject_id,
            row.relation_type,
        )
        for row in before
    )
    after_identity = tuple(
        (
            row.evidence_id,
            row.fact_type,
            row.subject_id,
            row.parent_subject_id,
            row.relation_type,
        )
        for row in after
    )
    if before_identity != after_identity:
        raise RuntimeError("representation canonicalization changed evidence identity")


def _surface_spec(request: ExtractionRequest):
    from app.extraction.surfaces import surface_spec

    return surface_spec(request.surface)


_ADAPTERS = {
    Surface.ECOMMERCE_DETAIL: SurfaceAdapter(_harvest_detail, _resolve_detail),
    Surface.ECOMMERCE_LISTING: SurfaceAdapter(_harvest_listing, _resolve_listing),
    Surface.JOB_DETAIL: SurfaceAdapter(
        _harvest_job_detail, _resolve_job_detail_adapter
    ),
    Surface.JOB_LISTING: SurfaceAdapter(
        _harvest_job_listing, _resolve_job_listing_adapter
    ),
}
