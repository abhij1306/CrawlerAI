"""Four surface adapters behind the common Harvest → Resolve → Publish API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, cast

from app.core.extraction_memory.contract_runtime import (
    contract_preferences,
    resolved_contract_outcomes,
)
from app.core.extraction_memory.templates import fingerprint_from_parts
from app.core.records.divergence import (
    compare_public_record_to_projection,
    compare_records_to_projection,
)
from app.extraction.contracts import (
    CollectorOutcome,
    CommerceDetailProjection,
    CommerceListingProjection,
    Decision,
    Evidence,
    ExtractionRequest,
    Finding,
    HarvestResult,
    JobDetailProjection,
    JobListingProjection,
    PublicationResult,
    PublicRecord,
    ResolutionEnvelope,
    TargetSelection,
)
from app.extraction.collectors.dom import css_recipe_evidence
from app.extraction.collectors.url import UrlCollector
from app.extraction.entities import EntitySet, build_entities
from app.core.shared.ids import stable_id
from app.extraction.job_resolution import resolve_job_detail, resolve_job_listing
from app.extraction.jobs import (
    collect_job_detail,
    collect_job_listing,
    wrong_surface_findings_for_job_detail,
)
from app.extraction.listing import (
    collect_ecommerce_listing,
    resolve_ecommerce_listing,
)
from app.extraction.publication import (
    serialize_commerce_detail_projection,
    serialize_commerce_listing_projection,
    serialize_job_detail_projection,
    serialize_job_listing_projection,
)
from app.extraction.pipeline import harvest_ecommerce_detail, normalize_ecommerce_detail
from app.extraction.publication import (
    commerce_detail_projection,
    commerce_listing_projection,
    job_detail_projection,
    job_listing_projection,
)
from app.extraction.resolution import resolve as resolve_ecommerce_detail
from app.extraction.result_building import (
    assert_resolution_accounting,
    entity_graph,
    evidence_dispositions,
    projection_field_states,
)
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
    publish: Callable[[ResolutionEnvelope], PublicationResult]


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
    )
    _assert_representation_only(harvested.evidence, normalized)
    return harvested.model_copy(update={"evidence": normalized})


def harvest_compiled_recipe(request: ExtractionRequest) -> HarvestResult:
    """Known-template recipe fast path: recipe evidence plus URL identity only."""

    recipe_rows = tuple(css_recipe_evidence(request.capture, request.artifact_reader))
    url_rows = tuple(UrlCollector().collect(request.capture, request.artifact_reader))
    rows = normalize_ecommerce_detail(
        (*recipe_rows, *url_rows),
        page_url=request.capture.final_url or request.capture.requested_url,
    )
    outcomes: list[CollectorOutcome] = []
    if recipe_rows:
        outcomes.append(
            CollectorOutcome(
                collector_id="css_recipe",
                outcome="produced_evidence",
                evidence_count=len(recipe_rows),
            )
        )
    outcomes.append(
        CollectorOutcome(
            collector_id="url",
            outcome="produced_evidence" if url_rows else "no_match",
            evidence_count=len(url_rows),
        )
    )
    return HarvestResult(
        surface=request.surface,
        evidence=rows,
        collector_outcomes=tuple(outcomes),
        admitted_source_objects=len({row.subject_id for row in rows if row.subject_id}),
    )


def _harvest_listing(request: ExtractionRequest) -> HarvestResult:
    return _harvest_from_rows(
        Surface.ECOMMERCE_LISTING,
        tuple(collect_ecommerce_listing(request.capture, request.artifact_reader)),
    )


def _harvest_job_detail(request: ExtractionRequest) -> HarvestResult:
    return _harvest_from_rows(
        Surface.JOB_DETAIL,
        tuple(collect_job_detail(request.capture, request.artifact_reader)),
    )


def _harvest_job_listing(request: ExtractionRequest) -> HarvestResult:
    return _harvest_from_rows(
        Surface.JOB_LISTING,
        tuple(collect_job_listing(request.capture, request.artifact_reader)),
    )


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
    spec = _surface_spec(request)
    target = select_commerce_target(graph_state, evidence, request, spec)
    graph = scoped_graph(graph_state, target)
    findings = validate_ecommerce_detail(evidence, graph, request.requested_fields)
    preferences: dict[str, tuple[str, ...]] = {}
    fingerprint = ""
    if request.runtime_snapshot:
        fingerprint = fingerprint_from_parts(
            request.capture.final_url or request.capture.requested_url,
            request.surface.value,
            evidence,
            harvest.collector_outcomes,
        )
        preferences = contract_preferences(
            snapshot=dict(request.runtime_snapshot),
            fingerprint=fingerprint,
            surface=request.surface.value,
            url=request.capture.final_url or request.capture.requested_url,
            evidence=evidence,
            requested_fields=frozenset(request.requested_fields),
            user_controlled_fields=frozenset(request.user_controlled_fields),
        )
    resolution = resolve_ecommerce_detail(
        evidence,
        cast(EntitySet, graph),
        findings,
        contract_preferences=preferences,
    )
    projection, selected = commerce_detail_projection(resolution, evidence)
    outcomes = (
        resolved_contract_outcomes(
            snapshot=dict(request.runtime_snapshot),
            fingerprint=fingerprint,
            surface=request.surface.value,
            url=request.capture.final_url or request.capture.requested_url,
            evidence=evidence,
            resolution=resolution,
            requested_fields=frozenset(request.requested_fields),
            user_controlled_fields=frozenset(request.user_controlled_fields),
        )
        if request.runtime_snapshot
        else ()
    )
    return _envelope(
        request,
        harvest,
        graph_state=graph_state,
        target=target,
        decisions=resolution.decisions,
        selected=selected,
        derived=resolution.derived_facts,
        findings=findings,
        projection=projection,
        contract_outcomes=outcomes,
    )


def _resolve_listing(
    request: ExtractionRequest, harvest: HarvestResult
) -> ResolutionEnvelope:
    spec = _surface_spec(request)
    graph_state = _subject_graph(harvest.evidence)
    target = select_subject_targets(graph_state, harvest.evidence, request, spec)
    selected_subjects = set(target.root_entity_ids)
    rows = [row for row in harvest.evidence if row.subject_id in selected_subjects]
    decisions = tuple(resolve_ecommerce_listing(rows))
    findings = _incomplete_record_findings(
        target.root_entity_ids,
        decisions,
        required={"product.title", "product.url"},
        rule_id="INCOMPLETE_COMMERCE_LISTING_CARD",
    )
    projection, selected = commerce_listing_projection(
        decisions, harvest.evidence, max_records=request.max_records
    )
    return _envelope(
        request,
        harvest,
        graph_state=graph_state,
        target=target,
        decisions=decisions,
        selected=selected,
        findings=findings,
        projection=projection,
    )


def _resolve_job_detail_adapter(
    request: ExtractionRequest, harvest: HarvestResult
) -> ResolutionEnvelope:
    spec = _surface_spec(request)
    graph_state = _subject_graph(harvest.evidence)
    target = select_subject_targets(graph_state, harvest.evidence, request, spec)
    findings = wrong_surface_findings_for_job_detail(
        request.capture, request.artifact_reader
    )
    if findings:
        return ResolutionEnvelope(
            surface=request.surface,
            graph=entity_graph(EntitySet(), harvest.evidence, spec),
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
    rows = [row for row in harvest.evidence if row.subject_id == entity_id]
    decisions = tuple(resolve_job_detail(rows)) if entity_id else ()
    projection, selected = job_detail_projection(
        decisions, harvest.evidence, target_entity_id=entity_id
    )
    return _envelope(
        request,
        harvest,
        graph_state=graph_state,
        target=target,
        decisions=decisions,
        selected=selected,
        findings=findings,
        projection=projection,
    )


def _resolve_job_listing_adapter(
    request: ExtractionRequest, harvest: HarvestResult
) -> ResolutionEnvelope:
    spec = _surface_spec(request)
    graph_state = _subject_graph(harvest.evidence)
    target = select_subject_targets(graph_state, harvest.evidence, request, spec)
    selected_subjects = set(target.root_entity_ids)
    rows = [row for row in harvest.evidence if row.subject_id in selected_subjects]
    decisions = tuple(resolve_job_listing(rows))
    findings = _incomplete_record_findings(
        target.root_entity_ids,
        decisions,
        required={"job.title", "job.url"},
        rule_id="INCOMPLETE_JOB_LISTING_CARD",
    )
    projection, selected = job_listing_projection(
        decisions, harvest.evidence, max_records=request.max_records
    )
    return _envelope(
        request,
        harvest,
        graph_state=graph_state,
        target=target,
        decisions=decisions,
        selected=selected,
        findings=findings,
        projection=projection,
    )


def _envelope(
    request: ExtractionRequest,
    harvest: HarvestResult,
    *,
    graph_state,
    target,
    decisions: tuple[Decision, ...],
    selected,
    findings: tuple[Finding, ...],
    projection,
    derived=(),
    contract_outcomes=(),
) -> ResolutionEnvelope:
    dispositions = evidence_dispositions(
        harvest.evidence,
        decisions,
        selected,
        target,
    )
    assert_resolution_accounting(harvest.evidence, decisions, selected, dispositions)
    return ResolutionEnvelope(
        surface=request.surface,
        graph=entity_graph(graph_state, harvest.evidence, _surface_spec(request)),
        target=target,
        decisions=decisions,
        selected_facts=selected,
        derived_facts=derived,
        evidence_dispositions=dispositions,
        findings=findings,
        field_states=projection_field_states(
            projection, harvest.evidence, dispositions, request, findings
        ),
        publication=projection,
        contract_outcomes=contract_outcomes,
    )


def _publish(envelope: ResolutionEnvelope) -> PublicationResult:
    projection = envelope.publication
    records: tuple[PublicRecord, ...]
    if isinstance(projection, CommerceDetailProjection):
        has_url = any(
            row.path == "record.url" and row.disposition == "publish"
            for row in projection.entries
        )
        records = (serialize_commerce_detail_projection(projection),) if has_url else ()
        findings = (
            compare_public_record_to_projection(
                records[0].model_dump(mode="python", exclude_none=True),
                projection,
                blocking=True,
                detect_extras=True,
            )
            if records
            else ()
        )
        return PublicationResult(records=records, findings=findings)
    if isinstance(projection, CommerceListingProjection):
        records = serialize_commerce_listing_projection(projection)
    elif isinstance(projection, JobDetailProjection):
        records = serialize_job_detail_projection(projection)
    elif isinstance(projection, JobListingProjection):
        records = serialize_job_listing_projection(projection)
    else:  # pragma: no cover - discriminated union exhaustiveness
        return PublicationResult()
    findings = compare_records_to_projection(
        tuple(row.model_dump(mode="python", exclude_none=True) for row in records),
        projection,
        blocking=True,
    )
    return PublicationResult(records=records, findings=findings)


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
    Surface.ECOMMERCE_DETAIL: SurfaceAdapter(
        harvest=_harvest_detail,
        resolve=_resolve_detail,
        publish=_publish,
    ),
    Surface.ECOMMERCE_LISTING: SurfaceAdapter(
        harvest=_harvest_listing,
        resolve=_resolve_listing,
        publish=_publish,
    ),
    Surface.JOB_DETAIL: SurfaceAdapter(
        harvest=_harvest_job_detail,
        resolve=_resolve_job_detail_adapter,
        publish=_publish,
    ),
    Surface.JOB_LISTING: SurfaceAdapter(
        harvest=_harvest_job_listing,
        resolve=_resolve_job_listing_adapter,
        publish=_publish,
    ),
}
