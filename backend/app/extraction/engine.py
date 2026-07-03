"""Common extraction orchestration: Harvest → Resolve → Publish."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from typing import Literal, cast

from app.core.config.extraction_rules import (
    DETAIL_CAPTURE_NOT_FOUND_OUTCOME,
    DETAIL_CAPTURE_SEMANTIC_SHELL_OUTCOME,
    DETAIL_NOT_FOUND_HTTP_STATUS_CODES,
    DETAIL_REVIEW_HIGH_VALUE_REQUESTED_FIELDS,
    DETAIL_REVIEW_PARENT_CHILD_DIVERGENCE_FIELDS,
    DETAIL_REVIEW_RISK_FINDING_RULE_IDS,
    DETAIL_SHELL_FINDING_RULE_ID,
    DETAIL_SHELL_MEANINGFUL_RECORD_FIELDS,
)
from app.core.domain_utils import normalize_domain
from app.core.config.extraction_memory import EXTRACTION_MEMORY_STATUS_SUSPENDED
from app.core.extraction_memory.contract_runtime import match_template
from app.core.extraction_memory.templates import normalize_route
from app.core.shared.ids import stable_id
from app.extraction.adapters import SurfaceAdapter, adapter_for, harvest_compiled_recipe
from app.extraction.contracts import (
    CollectorOutcome,
    DiagnosticSummary,
    EntityGraph,
    Evidence,
    ExecutionManifestContext,
    ExtractionRequest,
    ExtractionResult,
    FailureClassification,
    Finding,
    HarvestResult,
    PublicationResult,
    PublicRecord,
    ResolutionEnvelope,
    SentinelObservation,
    StageOutcome,
    TargetSelection,
    Verdict,
)
from app.extraction.model_runtime import (
    ModelFallbackResult,
    RuntimeModelAdapter,
    run_model_fallback,
)
from app.extraction.sentinel import (
    compare_challenger,
    sentinel_enabled,
    sentinel_sample_rate,
    should_sample_sentinel,
)
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


@dataclass(frozen=True)
class _ExtractionAttempt:
    harvest: HarvestResult
    resolution: ResolutionEnvelope
    publication: PublicationResult
    findings: tuple[Finding, ...]
    verdict: Verdict
    records: tuple[PublicRecord, ...]
    resolve_duration_ms: float
    publish_duration_ms: float
    stage_outcomes: tuple[StageOutcome, ...]


def extract(
    request: ExtractionRequest,
    *,
    model_adapter: RuntimeModelAdapter | None = None,
) -> ExtractionResult:
    if request.capture.blocked:
        return _blocked_result(request, (), ())
    adapter = adapter_for(request.surface)
    compiled_template = _compiled_recipe_template(request)
    extractor_tier: Literal["deterministic", "recipe", "ml"] = "deterministic"
    if compiled_template is not None:
        harvest = harvest_compiled_recipe(request)
        if any(row.collector_id == "css_recipe" for row in harvest.evidence):
            extractor_tier = "recipe"
        else:
            harvest = adapter.harvest(request)
    else:
        harvest = (
            _generic_harvest(request, adapter)
            if _has_suspended_runtime_template(request)
            else adapter.harvest(request)
        )
    attempt = _execute_attempt(request, adapter, harvest)
    stage_outcomes = list(attempt.stage_outcomes)
    sentinel_observations: tuple[SentinelObservation, ...] = ()

    if extractor_tier == "recipe" and not attempt.records:
        generic_harvest = _generic_harvest(request, adapter)
        generic_collector_ids = {
            row.collector_id for row in generic_harvest.collector_outcomes
        }
        # Keep only the recipe-specific outcomes (e.g. css_recipe) that the
        # generic collectors don't already report — prepending the full recipe
        # outcome set would double-count shared collectors (url) in metrics().
        recipe_only_outcomes = tuple(
            row
            for row in harvest.collector_outcomes
            if row.collector_id not in generic_collector_ids
        )
        generic_harvest = generic_harvest.model_copy(
            update={
                "collector_outcomes": (
                    *recipe_only_outcomes,
                    *generic_harvest.collector_outcomes,
                )
            }
        )
        attempt = _execute_attempt(
            request, adapter, generic_harvest, stage_prefix="generic_"
        )
        stage_outcomes.extend(attempt.stage_outcomes)
        extractor_tier = "deterministic"

    model_fallback: ModelFallbackResult | None = None
    if extractor_tier == "recipe" and attempt.records:
        sentinel_observations = _sentinel_observations(
            request,
            adapter,
            recipe_attempt=attempt,
            compiled_template=compiled_template,
            model_adapter=model_adapter,
        )
        for observation in sentinel_observations:
            stage_outcomes.append(
                StageOutcome(
                    stage=f"sentinel_{observation.challenger}_challenger",
                    outcome="produced_evidence",
                    detail=observation.state,
                )
            )
    if _needs_contract_fallback(attempt.verdict):
        model_fallback = run_model_fallback(request, model_adapter)
        model_outcome = _model_collector_outcome(model_fallback)
        stage_outcomes.append(
            StageOutcome(
                stage="model_fallback",
                outcome=model_outcome.outcome,
                detail=model_outcome.detail,
            )
        )
        attempt = replace(
            attempt,
            harvest=attempt.harvest.model_copy(
                update={
                    "collector_outcomes": (
                        *attempt.harvest.collector_outcomes,
                        model_outcome,
                    )
                }
            ),
        )
        if model_fallback.evidence:
            model_harvest = attempt.harvest.model_copy(
                update={
                    "evidence": (*attempt.harvest.evidence, *model_fallback.evidence),
                }
            )
            attempt = _execute_attempt(
                request, adapter, model_harvest, stage_prefix="model_"
            )
            stage_outcomes.extend(attempt.stage_outcomes)
            extractor_tier = "ml"

    harvest = attempt.harvest
    resolution = attempt.resolution
    publication = attempt.publication
    findings = attempt.findings
    verdict = attempt.verdict
    records = attempt.records
    failures = _failure_classifications(
        request,
        verdict=verdict,
        records=records,
        target=resolution.target,
        findings=findings,
        evidence=harvest.evidence,
        model_fallback=model_fallback,
    )
    field_states = resolution.field_states
    retry = retry_request(verdict, publication.records, request, harvest.evidence)
    review_required = _review_required(
        request,
        verdict=verdict,
        findings=findings,
        field_states=field_states,
        retry=retry,
    )
    extraction_metrics = metrics(
        harvest.evidence,
        resolution.graph,
        resolution.target,
        findings,
        resolution.decisions,
        publication.records,
        verdict,
        collector_count=len(harvest.collector_outcomes),
        resolve_duration_ms=attempt.resolve_duration_ms,
        publish_duration_ms=attempt.publish_duration_ms,
    )
    if model_fallback is not None:
        extraction_metrics = extraction_metrics.model_copy(
            update={
                "universal_representation_build_count": int(
                    model_fallback.representation_built
                ),
                "universal_model_invocation_count": int(model_fallback.invoked),
                "universal_model_latency_ms": model_fallback.latency_ms,
                "universal_model_service_failure_count": int(
                    model_fallback.failure_code == "model_service_failure"
                ),
                "universal_model_ungrounded_rejection_count": (
                    model_fallback.ungrounded_rejection_count
                ),
                "universal_model_ungrounded_rejection_rate": (
                    model_fallback.ungrounded_rejection_count
                    / model_fallback.prediction_count
                    if model_fallback.prediction_count
                    else 0.0
                ),
                "universal_model_cost_usd": model_fallback.cost_usd,
                "universal_model_cost_per_1000_pages": (
                    model_fallback.cost_usd * 1_000
                ),
            }
        )
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
        field_states=field_states,
        transport_outcome=_capture_outcome(
            request, verdict, findings, publication.records
        ),
        data_integrity=data_integrity_status(verdict, field_states, findings),
        records=records,
        verdict=verdict,
        retry_request=retry,
        metrics=extraction_metrics,
        collector_outcomes=harvest.collector_outcomes,
        stage_outcomes=tuple(stage_outcomes),
        contract_outcomes=resolution.contract_outcomes,
        sentinel_observations=sentinel_observations,
        manifest_context=_manifest_context(request, compiled_template),
        failure_classifications=failures,
        diagnostics=_diagnostic_summary(
            verdict=verdict,
            records=records,
            evidence=harvest.evidence,
            stage_outcomes=tuple(stage_outcomes),
            field_states=field_states,
            findings=findings,
            failures=failures,
            review_required=review_required,
            extractor_tier=extractor_tier,
            model_fallback=model_fallback,
            sentinel_observations=sentinel_observations,
        ),
    )


def _execute_attempt(
    request: ExtractionRequest,
    adapter: SurfaceAdapter,
    harvest: HarvestResult,
    *,
    stage_prefix: str = "",
) -> _ExtractionAttempt:
    stage_outcomes = [_stage_outcome(f"{stage_prefix}harvest", len(harvest.evidence))]
    resolve_started = perf_counter()
    resolution = adapter.resolve(request, harvest)
    resolve_duration_ms = (perf_counter() - resolve_started) * 1_000
    stage_outcomes.append(
        _stage_outcome(f"{stage_prefix}resolve", len(resolution.decisions))
    )
    publish_started = perf_counter()
    publication = adapter.publish(resolution)
    publish_duration_ms = (perf_counter() - publish_started) * 1_000
    stage_outcomes.append(
        _stage_outcome(f"{stage_prefix}publish", len(publication.records))
    )
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
    stage_outcomes.append(_stage_outcome(f"{stage_prefix}validate", len(findings)))
    return _ExtractionAttempt(
        harvest=harvest,
        resolution=resolution,
        publication=publication,
        findings=findings,
        verdict=verdict,
        records=records,
        resolve_duration_ms=resolve_duration_ms,
        publish_duration_ms=publish_duration_ms,
        stage_outcomes=tuple(stage_outcomes),
    )


def _needs_contract_fallback(verdict: Verdict) -> bool:
    # "review" means extraction produced a usable record that merely needs
    # human confirmation — it is a success outcome and must not trigger the
    # expensive model fallback. Only truly deficient results fall back.
    return verdict in {"empty", "partial"}


def _model_collector_outcome(result: ModelFallbackResult) -> CollectorOutcome:
    return CollectorOutcome(
        collector_id="universal_model",
        outcome=("skipped" if result.outcome == "disabled" else result.outcome),
        evidence_count=len(result.evidence),
        detail=result.detail,
    )


def _compiled_recipe_template(request: ExtractionRequest) -> dict[str, object] | None:
    if request.surface != Surface.ECOMMERCE_DETAIL or request.runtime_snapshot is None:
        return None
    if not request.artifact_reader.exists("css_field_rules"):
        return None
    template = match_template(
        dict(request.runtime_snapshot),
        "",
        request.surface.value,
        url=request.capture.final_url or request.capture.requested_url,
    )
    if not template:
        return None
    if (
        str(template.get("status") or "").strip().lower()
        == EXTRACTION_MEMORY_STATUS_SUSPENDED
    ):
        return None
    if bool(template.get("sentinel_suspended")):
        return None
    compiled_recipe = template.get("compiled_recipe")
    if not isinstance(compiled_recipe, dict):
        return None
    selector_rules = compiled_recipe.get("selector_rules")
    if not isinstance(selector_rules, list) or not selector_rules:
        return None
    return template


def _has_suspended_runtime_template(request: ExtractionRequest) -> bool:
    templates = (
        request.runtime_snapshot.get("templates", [])
        if request.runtime_snapshot
        else ()
    )
    route = normalize_route(
        request.capture.final_url or request.capture.requested_url,
        request.surface.value,
    )
    return any(
        isinstance(row, dict)
        and str(row.get("surface") or "") == request.surface.value
        and str(row.get("route_pattern") or "") == route
        and (
            str(row.get("status") or "").strip().lower()
            == EXTRACTION_MEMORY_STATUS_SUSPENDED
            or bool(row.get("sentinel_suspended"))
        )
        for row in templates
    )


def _sentinel_observations(
    request: ExtractionRequest,
    adapter: SurfaceAdapter,
    *,
    recipe_attempt: _ExtractionAttempt,
    compiled_template: dict[str, object] | None,
    model_adapter: RuntimeModelAdapter | None,
) -> tuple[SentinelObservation, ...]:
    if compiled_template is None or not request.runtime_snapshot:
        return ()
    manifest_context = _manifest_context(request, compiled_template)
    sample_rate = sentinel_sample_rate(request.runtime_snapshot)
    if not should_sample_sentinel(
        bundle_id=request.capture.bundle_id,
        template_id=manifest_context.template_id,
        sample_rate=sample_rate,
    ):
        return ()
    observations = []
    if sentinel_enabled(request.runtime_snapshot, "deterministic_challenger_enabled"):
        generic_attempt = _execute_attempt(
            request,
            adapter,
            _generic_harvest(request, adapter),
            stage_prefix="sentinel_generic_",
        )
        observations.append(
            compare_challenger(
                challenger="deterministic",
                manifest_context=manifest_context,
                sample_rate=sample_rate,
                recipe_verdict=recipe_attempt.verdict,
                challenger_verdict=generic_attempt.verdict,
                recipe_records=recipe_attempt.records,
                challenger_records=generic_attempt.records,
                evidence_ids=(
                    *(row.evidence_id for row in recipe_attempt.harvest.evidence),
                    *(row.evidence_id for row in generic_attempt.harvest.evidence),
                ),
            )
        )
    if sentinel_enabled(request.runtime_snapshot, "ml_challenger_enabled"):
        model_result = run_model_fallback(request, model_adapter)
        model_harvest = recipe_attempt.harvest.model_copy(
            update={
                "evidence": model_result.evidence,
                "collector_outcomes": (_model_collector_outcome(model_result),),
            }
        )
        model_attempt = (
            _execute_attempt(
                request,
                adapter,
                model_harvest,
                stage_prefix="sentinel_model_",
            )
            if model_result.evidence
            else replace(
                recipe_attempt,
                harvest=model_harvest,
                records=(),
                verdict="empty",
            )
        )
        observations.append(
            compare_challenger(
                challenger="ml",
                manifest_context=manifest_context,
                sample_rate=sample_rate,
                recipe_verdict=recipe_attempt.verdict,
                challenger_verdict=model_attempt.verdict,
                recipe_records=recipe_attempt.records,
                challenger_records=model_attempt.records,
                evidence_ids=(
                    *(row.evidence_id for row in recipe_attempt.harvest.evidence),
                    *(row.evidence_id for row in model_result.evidence),
                ),
            )
        )
    return tuple(observations)


def _generic_harvest(
    request: ExtractionRequest, adapter: SurfaceAdapter
) -> HarvestResult:
    harvest = adapter.harvest(request)
    if request.surface != Surface.ECOMMERCE_DETAIL:
        return harvest
    return harvest.model_copy(
        update={
            "evidence": tuple(
                row for row in harvest.evidence if row.collector_id != "css_recipe"
            ),
            "collector_outcomes": tuple(
                row
                for row in harvest.collector_outcomes
                if row.collector_id != "css_recipe"
            ),
        }
    )


def _manifest_context(
    request: ExtractionRequest, template: dict[str, object] | None
) -> ExecutionManifestContext:
    if template is None:
        return request.manifest_context
    template_id = str(template.get("template_id") or "").strip()
    if not template_id:
        return request.manifest_context
    return request.manifest_context.model_copy(update={"template_id": template_id})


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
            and _is_thin_detail_record(record)
        )
        if _is_semantic_detail_shell(request, records, findings) or thin_not_found:
            return "error"
    if any(row.blocking for row in findings if row.rule_id != "WRONG_SURFACE_CONTENT"):
        return "error" if request.surface == Surface.JOB_DETAIL else "invalid"
    if wrong_surface:
        return "wrong_surface"
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
        evidence_ids=tuple(row.evidence_id for row in evidence),
        message="Acquisition was blocked before extraction.",
        blocking=True,
    )
    target = TargetSelection(status="missing")
    dispositions = evidence_dispositions(evidence, (), (), target)
    assert_resolution_accounting(evidence, (), (), dispositions)
    states = field_evidence_states((), evidence, (), request)
    failures = _failure_classifications(
        request,
        verdict="blocked",
        records=(),
        target=target,
        findings=(finding,),
        evidence=evidence,
    )
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
        transport_outcome=_capture_outcome(request, "blocked", (finding,), ()),
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
        manifest_context=request.manifest_context,
        failure_classifications=failures,
        diagnostics=_diagnostic_summary(
            verdict="blocked",
            records=(),
            evidence=evidence,
            stage_outcomes=(_stage_outcome("harvest", len(evidence)),),
            field_states=states,
            findings=(finding,),
            failures=failures,
            review_required=_review_required(
                request,
                verdict="blocked",
                findings=(finding,),
                field_states=states,
                retry=None,
            ),
        ),
    )


def _stage_outcome(stage: str, produced: int) -> StageOutcome:
    return StageOutcome(
        stage=stage,
        outcome="produced_evidence" if produced else "no_match",
    )


def _failure_classifications(
    request: ExtractionRequest,
    *,
    verdict: Verdict,
    records: tuple[PublicRecord, ...],
    target: TargetSelection,
    findings: tuple[Finding, ...],
    evidence: tuple[Evidence, ...],
    model_fallback: ModelFallbackResult | None = None,
) -> tuple[FailureClassification, ...]:
    if records:
        return ()
    if model_fallback is not None and model_fallback.failure_code is not None:
        deterministic = _failure_classifications(
            request,
            verdict=verdict,
            records=records,
            target=target,
            findings=findings,
            evidence=evidence,
        )
        return (
            *deterministic,
            _failure(
                model_fallback.failure_code,
                "Universal model fallback degraded; deterministic extraction remained authoritative.",
                findings,
                evidence,
            ),
        )
    if (
        request.capture.acquisition_outcome in {"blocked", "error"}
        or request.capture.blocked
    ):
        return (
            _failure(
                "insufficient_input_bundle",
                "Input bundle could not supply usable extraction content.",
                findings,
                evidence,
            ),
        )
    if verdict == "wrong_surface" or target.status == "wrong_surface":
        return (
            _failure(
                "wrong_surface",
                "Input content does not match the requested surface.",
                findings,
                evidence,
            ),
        )
    if any(row.blocking for row in findings):
        return (
            _failure(
                "validation",
                "Critical validation blocked publication.",
                findings,
                evidence,
            ),
        )
    if target.status == "ambiguous":
        return (
            _failure(
                "entity_binding",
                "Primary entity could not be selected safely.",
                findings,
                evidence,
            ),
        )
    if target.status == "missing":
        code = "discovery" if evidence else "insufficient_input_bundle"
        return (
            _failure(
                code, "No publishable record boundary was found.", findings, evidence
            ),
        )
    if verdict in {"invalid", "error"}:
        return (
            _failure(
                "semantic_resolution",
                "Resolved evidence could not pass publication trust gates.",
                findings,
                evidence,
            ),
        )
    return (
        _failure(
            "discovery", "No publishable records were discovered.", findings, evidence
        ),
    )


def _capture_outcome(
    request: ExtractionRequest,
    verdict: Verdict,
    findings: tuple[Finding, ...],
    records: tuple[PublicRecord, ...],
) -> str:
    if request.capture.blocked or request.capture.acquisition_outcome == "blocked":
        return "blocked"
    if (
        request.surface == Surface.ECOMMERCE_DETAIL
        and request.capture.http_status in DETAIL_NOT_FOUND_HTTP_STATUS_CODES
    ):
        return DETAIL_CAPTURE_NOT_FOUND_OUTCOME
    if _is_semantic_detail_shell(request, records, findings):
        return DETAIL_CAPTURE_SEMANTIC_SHELL_OUTCOME
    if verdict == "blocked":
        return "blocked"
    return request.capture.acquisition_outcome or "unknown"


def _is_semantic_detail_shell(
    request: ExtractionRequest,
    records: tuple[PublicRecord, ...],
    findings: tuple[Finding, ...],
) -> bool:
    if request.surface != Surface.ECOMMERCE_DETAIL:
        return False
    record = records[0] if records else None
    if (record is not None and is_shell_record(record)) or any(
        row.rule_id == DETAIL_SHELL_FINDING_RULE_ID for row in findings
    ):
        return True
    requested_host = normalize_domain(request.capture.requested_url)
    final_host = normalize_domain(request.capture.final_url)
    crossed_host = bool(requested_host and final_host and requested_host != final_host)
    return record is not None and _is_thin_detail_record(record) and crossed_host


def _is_thin_detail_record(record: PublicRecord | None) -> bool:
    return record is None or not any(
        record.get(field) not in (None, "", [], {}, ())
        for field in DETAIL_SHELL_MEANINGFUL_RECORD_FIELDS
    )


def _review_required(
    request: ExtractionRequest,
    *,
    verdict: Verdict,
    findings: tuple[Finding, ...],
    field_states,
    retry,
) -> bool:
    if verdict == "review":
        return True
    if retry is not None and retry.required:
        return False
    if any(
        row.rule_id in DETAIL_REVIEW_RISK_FINDING_RULE_IDS and row.scope != "candidate"
        for row in findings
    ):
        return True
    if _parent_child_commercial_divergence(field_states):
        return True
    return _requested_high_value_field_unresolved(request, field_states)


def _parent_child_commercial_divergence(field_states) -> bool:
    states_by_field = {row.field: row.state for row in field_states}
    for field in DETAIL_REVIEW_PARENT_CHILD_DIVERGENCE_FIELDS:
        child_state = states_by_field.get(f"variants.{field}")
        parent_state = states_by_field.get(field)
        if child_state == "captured_published" and parent_state not in {
            "captured_published",
            "captured_and_resolved",
        }:
            return True
    return False


def _requested_high_value_field_unresolved(
    request: ExtractionRequest, field_states
) -> bool:
    if request.surface != Surface.ECOMMERCE_DETAIL:
        return False
    requested = {
        "image_url" if field == "image" else field for field in request.requested_fields
    } & DETAIL_REVIEW_HIGH_VALUE_REQUESTED_FIELDS
    if not requested:
        return False
    states_by_field = {row.field: row.state for row in field_states}
    return any(
        states_by_field.get(field)
        not in {"captured_published", "captured_and_resolved"}
        for field in requested
    )


def _failure(
    code,
    message: str,
    findings: tuple[Finding, ...],
    evidence: tuple[Evidence, ...],
) -> FailureClassification:
    return FailureClassification(
        code=code,
        message=message,
        finding_ids=tuple(row.finding_id for row in findings),
        evidence_ids=tuple(row.evidence_id for row in evidence),
    )


def _diagnostic_summary(
    *,
    verdict: Verdict,
    records: tuple[PublicRecord, ...],
    evidence: tuple[Evidence, ...],
    stage_outcomes: tuple[StageOutcome, ...],
    field_states,
    failures: tuple[FailureClassification, ...],
    findings: tuple[Finding, ...] = (),
    review_required: bool = False,
    extractor_tier: Literal["deterministic", "recipe", "ml"] = "deterministic",
    model_fallback: ModelFallbackResult | None = None,
    sentinel_observations=(),
) -> DiagnosticSummary:
    # ``missing_critical_fields`` reports the unfulfilled *contract* fields so it
    # agrees with the verdict and trust state (Crawl-Run-2 §4.5). The contract
    # scorer publishes exactly that set as RECORD_COMPLETENESS ``missing_fields``;
    # fall back to the raw not-present field-state scan for surfaces that emit no
    # completeness contract (e.g. job_detail).
    completeness = next(
        (row for row in findings if row.rule_id == "RECORD_COMPLETENESS"), None
    )
    if completeness is not None:
        missing = tuple(completeness.metadata.get("missing_fields") or ())
    else:
        missing = tuple(
            row.field
            for row in field_states
            if row.state in {"not_present_in_captured_sources", "source_unavailable"}
        )
    return DiagnosticSummary(
        decision_path=tuple(row.stage for row in stage_outcomes),
        extractor_tier="blocked" if verdict == "blocked" else extractor_tier,
        trust_state=_trust_state(verdict, records, review_required),
        missing_critical_fields=missing,
        failure_codes=tuple(row.code for row in failures),
        evidence_count=len(evidence),
        review_required=review_required,
        model_invoked=model_fallback.invoked if model_fallback is not None else False,
        model_artifact_id=(
            model_fallback.artifact.artifact_id
            if model_fallback is not None and model_fallback.artifact is not None
            else None
        ),
        model_artifact_version=(
            model_fallback.artifact.artifact_version
            if model_fallback is not None and model_fallback.artifact is not None
            else None
        ),
        model_outcome=(
            model_fallback.outcome if model_fallback is not None else "not_considered"
        ),
        sentinel_state=sentinel_observations[0].state
        if sentinel_observations
        else None,
        sentinel_diagnostic=sentinel_observations[0].diagnostic
        if sentinel_observations
        else None,
    )


def _trust_state(
    verdict: Verdict,
    records: tuple[PublicRecord, ...],
    review_required: bool,
) -> Literal["verified", "partial", "needs_review", "rejected", "blocked", "unknown"]:
    if review_required or verdict == "review":
        return "needs_review"
    if verdict == "success":
        return "verified"
    if verdict == "partial":
        return "partial"
    if verdict == "blocked":
        return "blocked"
    if verdict in {"invalid", "error", "wrong_surface", "empty"} or not records:
        return "rejected"
    return "unknown"
