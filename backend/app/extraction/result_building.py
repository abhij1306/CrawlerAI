"""Recipe extraction result assembly."""

from __future__ import annotations


from pydantic import ValidationError

from app.core.config.extraction_rules import DETAIL_SHELL_TITLE_KEYS
from app.core.extraction_memory.recipe_contracts import (
    DiscoveryResult,
    ExtractionRecipe,
    RecipeCandidate,
    RecipeExecutionResult,
    RecipeFailureCode,
)
from app.core.shared.ids import stable_id
from app.extraction.contracts import (
    CommerceDetailRecord,
    DiagnosticSummary,
    EntityGraph,
    Evidence,
    ExecutionManifestContext,
    ExtractionMetrics,
    ExtractionRequest,
    ExtractionResult,
    FailureClassification,
    Finding,
    StageOutcome,
    TargetSelection,
    Verdict,
)
from app.extraction.model_runtime import ModelRecipeProposalResult
from app.extraction.publication import publish_recipe_execution
from app.extraction.result_policy import retry_request
from app.extraction.surfaces import Surface
from app.extraction.result_policy import assess, review_required
from app.observability.extraction_diagnostics import (
    _discovery_collector_outcomes,
    _execution_diagnostics,
    _failure_diagnostics,
    _failure_field_states,
    _failure_message,
    _failure_taxonomy,
    _recipe_reader_outcomes,
    capture_outcome,
    field_states,
    integrity,
    metrics,
    trust_state,
)

# Stable private aliases retained for focused contract tests.
_review_required = review_required
_trust_state = trust_state


def execution_result(
    request: ExtractionRequest,
    recipe: ExtractionRecipe,
    execution: RecipeExecutionResult,
    *,
    candidate: RecipeCandidate | None,
    template: dict[str, object] | None,
    stages: tuple[StageOutcome, ...],
    model: ModelRecipeProposalResult | None,
    discovery: DiscoveryResult | None = None,
) -> ExtractionResult:
    published = _publish_execution(request, recipe, execution, discovery)
    if isinstance(published, RecipeExecutionResult):
        return failed_result(
            request,
            execution=published,
            discovery=None,
            template=template,
            stages=stages,
            model=model,
        )
    records, findings = published
    retry_records = records
    records, terminal_outcome = _terminal_records(request, records, findings)
    target, graph = _target_graph(records)
    states = field_states(request, records, execution)
    verdict = _execution_verdict(request, target, records, findings, terminal_outcome)
    retry = retry_request(verdict, retry_records, request)
    review = review_required(
        request,
        verdict=verdict,
        findings=findings,
        field_states=states,
        retry=retry,
    )
    collectors = _discovery_collector_outcomes(discovery) + _recipe_reader_outcomes(
        recipe, execution
    )
    return ExtractionResult(
        surface=request.surface,
        bundle_id=request.capture.bundle_id,
        records=records,
        graph=graph,
        target=target,
        findings=findings,
        field_states=states,
        transport_outcome=terminal_outcome,
        data_integrity=integrity(verdict),
        verdict=verdict,
        retry_request=retry,
        metrics=metrics(
            records,
            graph,
            verdict,
            findings=findings,
            model=model,
            collector_count=len(collectors),
        ),
        collector_outcomes=collectors,
        stage_outcomes=stages,
        manifest_context=request.manifest_context,
        diagnostics=_execution_diagnostics(
            request, records, findings, verdict, review, candidate, stages, model
        ),
        recipe_candidate=candidate,
        recipe_execution=execution,
    )


def failed_result(
    request: ExtractionRequest,
    *,
    execution: RecipeExecutionResult | None,
    discovery: DiscoveryResult | None,
    template: dict[str, object] | None,
    stages: tuple[StageOutcome, ...],
    model: ModelRecipeProposalResult | None,
) -> ExtractionResult:
    code = _failure_code(execution, discovery)
    terminal_outcome = capture_outcome(request, (), ())
    verdict = _failure_verdict(request, discovery, terminal_outcome)
    taxonomy = _failure_taxonomy(code, request.surface)
    target = _failure_target(discovery)
    states = _failure_field_states(request, terminal_outcome)
    retry = retry_request(
        verdict, _failure_retry_records(request, terminal_outcome), request
    )
    manifest = _manifest_context(request, template)
    collectors = _discovery_collector_outcomes(discovery)
    return ExtractionResult(
        surface=request.surface,
        bundle_id=request.capture.bundle_id,
        records=(),
        target=target,
        field_states=states,
        verdict=verdict,
        transport_outcome=terminal_outcome,
        data_integrity=integrity(verdict),
        retry_request=retry,
        metrics=metrics(
            (), EntityGraph(), verdict, model=model, collector_count=len(collectors)
        ),
        collector_outcomes=collectors,
        stage_outcomes=stages,
        manifest_context=manifest,
        failure_classifications=(
            FailureClassification(
                code=taxonomy,
                message=_failure_message(execution, discovery),
            ),
        ),
        diagnostics=_failure_diagnostics(
            taxonomy, terminal_outcome, template, stages, model
        ),
        recipe_execution=execution,
    )


def blocked_result(
    request: ExtractionRequest,
    evidence: tuple[Evidence, ...],
    collector_outcomes,
) -> ExtractionResult:
    finding = Finding(
        finding_id=stable_id("finding", request.capture.bundle_id, "blocked"),
        rule_id="ACQUISITION_BLOCKED",
        severity="critical",
        scope="artifact",
        entity_ids=(),
        evidence_ids=tuple(row.evidence_id for row in evidence),
        message="Acquisition was blocked before extraction.",
        blocking=True,
    )
    failure = FailureClassification(
        code="insufficient_input_bundle",
        message="Input bundle was blocked before extraction.",
        finding_ids=(finding.finding_id,),
        evidence_ids=finding.evidence_ids,
    )
    collectors = tuple(collector_outcomes)
    return ExtractionResult(
        surface=request.surface,
        bundle_id=request.capture.bundle_id,
        records=(),
        evidence=evidence,
        findings=(finding,),
        verdict="blocked",
        transport_outcome="blocked",
        data_integrity="blocked",
        metrics=ExtractionMetrics(collector_count=len(collectors), verdict="blocked"),
        collector_outcomes=collectors,
        stage_outcomes=(StageOutcome(stage="blocked", outcome="failed"),),
        manifest_context=request.manifest_context,
        failure_classifications=(failure,),
        diagnostics=DiagnosticSummary(
            decision_path=("blocked",),
            extractor_tier="blocked",
            trust_state="blocked",
            failure_codes=("insufficient_input_bundle",),
        ),
    )


def _publish_execution(request, recipe, execution, discovery):
    try:
        records, findings = publish_recipe_execution(request, recipe, execution)
        discovered = (
            tuple(Finding.model_validate(row) for row in discovery.finding_diagnostics)
            if discovery is not None
            else ()
        )
        return records, _merge_findings(discovered, findings)
    except (TypeError, ValueError, ValidationError) as exc:
        return execution.model_copy(
            update={
                "records": (),
                "failure_code": "recipe_value_validation_failed",
                "detail": str(exc),
            }
        )


def _terminal_records(request, records, findings):
    terminal_outcome = capture_outcome(request, findings, records)
    if request.surface is Surface.ECOMMERCE_DETAIL and terminal_outcome in {
        "not_found",
        "semantic_shell",
    }:
        return (), terminal_outcome
    return records, terminal_outcome


def _target_graph(records):
    roots = tuple(str(record.get("_subject_id") or "") for record in records)
    target = TargetSelection(
        status="resolved" if records else "missing",
        root_entity_ids=roots,
        selected_root_entity_id=roots[0] if roots else None,
    )
    return target, EntityGraph(
        root_entity_ids=roots, entity_counts={"record": len(records)}
    )


def _execution_verdict(request, target, records, findings, terminal_outcome):
    if terminal_outcome in {"not_found", "semantic_shell"}:
        return "error"
    return assess(request, target, records, findings)


def _merge_findings(*groups: tuple[Finding, ...]) -> tuple[Finding, ...]:
    merged: list[Finding] = []
    seen: set[str] = set()
    for finding in (row for group in groups for row in group):
        key = finding.model_dump_json()
        if key not in seen:
            seen.add(key)
            merged.append(finding)
    return tuple(merged)


def _failure_code(execution, discovery) -> RecipeFailureCode:
    if execution and execution.failure_code:
        return execution.failure_code
    if discovery and discovery.failure_code:
        return discovery.failure_code
    return "recipe_binding_not_found"


def _failure_verdict(request, discovery, terminal_outcome) -> Verdict:
    if discovery is not None and discovery.detail == "wrong surface discovery target":
        return "wrong_surface"
    if request.capture.acquisition_outcome == "error" or terminal_outcome in {
        "not_found",
        "semantic_shell",
    }:
        return "error"
    return "empty"


def _failure_target(discovery):
    detail = discovery.detail if discovery is not None else None
    statuses = {
        "wrong surface discovery target": "wrong_surface",
        "ambiguous discovery target": "ambiguous",
    }
    return TargetSelection(status=statuses.get(detail, "missing"))


def _failure_retry_records(request, terminal_outcome):
    if terminal_outcome != "semantic_shell":
        return ()
    return (
        CommerceDetailRecord(
            url=request.capture.final_url,
            title=next(iter(DETAIL_SHELL_TITLE_KEYS)),
        ),
    )


def _manifest_context(
    request: ExtractionRequest, template: dict[str, object] | None
) -> ExecutionManifestContext:
    if template is None:
        return request.manifest_context
    return request.manifest_context.model_copy(
        update={
            "template_id": str(template.get("template_id") or "") or None,
            "compiled_recipe_id": str(template.get("compiled_recipe_id") or "") or None,
        }
    )
