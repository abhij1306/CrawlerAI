"""One extraction runtime: select/compile recipe, execute, validate, publish."""

from __future__ import annotations

from typing import Literal, cast

from pydantic import ValidationError

from app.acquisition.browser_block_detection import classify_blocked_page
from app.core.config import field_mappings
from app.core.config.extraction_rules import (
    DETAIL_NOT_FOUND_HTTP_STATUS_CODES,
    DETAIL_REVIEW_HIGH_VALUE_REQUESTED_FIELDS,
    DETAIL_REVIEW_PARENT_CHILD_DIVERGENCE_FIELDS,
    DETAIL_REVIEW_RISK_FINDING_RULE_IDS,
    DETAIL_SHELL_FINDING_RULE_ID,
    DETAIL_SHELL_MEANINGFUL_RECORD_FIELDS,
    DETAIL_SHELL_TITLE_KEYS,
)
from app.core.domain_utils import normalize_domain
from app.core.extraction_memory.contract_runtime import select_active_recipe
from app.core.extraction_memory.recipe_contracts import (
    DiscoveryResult,
    ExtractionRecipe,
    RecipeCandidate,
    RecipeExecutionResult,
    RecipeFailureCode,
)
from app.core.extraction_memory.recipe_executor import execute_recipe
from app.core.records.detail_outcome import normalized_detail_outcome
from app.core.shared.ids import stable_id
from app.extraction.contracts import (
    CollectorOutcome,
    CommerceDetailRecord,
    DiagnosticSummary,
    EntityGraph,
    Evidence,
    ExecutionManifestContext,
    ExtractionMetrics,
    ExtractionRequest,
    ExtractionResult,
    FailureClassification,
    FieldEvidenceState,
    Finding,
    PublicRecord,
    StageOutcome,
    TargetSelection,
    Verdict,
)
from app.extraction.model_runtime import (
    ModelRecipeProposalResult,
    RuntimeModelAdapter,
    run_model_recipe_proposals,
)
from app.extraction.recipe_compiler import (
    compile_model_proposals,
    compile_recipe_candidate,
)
from app.extraction.recipe_publication import publish_recipe_execution
from app.extraction.result_building import is_shell_record, retry_request
from app.extraction.surfaces import Surface, listing_schema


def extract(
    request: ExtractionRequest,
    *,
    model_adapter: RuntimeModelAdapter | None = None,
) -> ExtractionResult:
    if request.capture.blocked:
        return _blocked_result(request, (), ())

    stages = [StageOutcome(stage="recipe_select", outcome="no_match")]
    template = select_active_recipe(
        dict(request.runtime_snapshot),
        surface=request.surface.value,
        url=request.capture.final_url or request.capture.requested_url,
        template_signature=str(
            request.runtime_snapshot.get("_template_signature") or ""
        ),
    )
    active_failure: RecipeExecutionResult | None = None
    if template is not None:
        stages[0] = StageOutcome(stage="recipe_select", outcome="ran")
        active_request, recipe = _active_recipe_request(request, template)
        active_failure = execute_recipe(active_request, recipe)
        stages.append(_execution_stage("recipe_execute", active_failure))
        if active_failure.records:
            return _execution_result(
                active_request,
                recipe,
                active_failure,
                candidate=None,
                template=template,
                stages=tuple(stages),
                model=None,
            )

    discovery = compile_recipe_candidate(request)
    stages.append(_discovery_stage("recipe_discovery", discovery))
    if discovery.candidate is not None:
        execution = execute_recipe(request, discovery.candidate.recipe)
        stages.append(_execution_stage("candidate_recipe_execute", execution))
        if execution.records:
            return _execution_result(
                request,
                discovery.candidate.recipe,
                execution,
                candidate=discovery.candidate,
                template=template,
                stages=tuple(stages),
                model=None,
                discovery=discovery,
            )
        active_failure = execution

    model = run_model_recipe_proposals(request, model_adapter)
    stages.append(_model_stage(model))
    if model.proposals:
        model_discovery = compile_model_proposals(request, model.proposals)
        stages.append(_discovery_stage("model_recipe_compile", model_discovery))
        if model_discovery.candidate is not None:
            execution = execute_recipe(request, model_discovery.candidate.recipe)
            stages.append(_execution_stage("candidate_recipe_execute", execution))
            if execution.records:
                return _execution_result(
                    request,
                    model_discovery.candidate.recipe,
                    execution,
                    candidate=model_discovery.candidate,
                    template=template,
                    stages=tuple(stages),
                    model=model,
                )
            active_failure = execution

    return _failed_result(
        request,
        execution=active_failure,
        discovery=discovery,
        template=template,
        stages=tuple(stages),
        model=model,
    )


def _active_recipe_request(
    request: ExtractionRequest, template: dict[str, object]
) -> tuple[ExtractionRequest, ExtractionRecipe]:
    recipe = ExtractionRecipe.model_validate(template.get("compiled_recipe"))
    manifest = request.manifest_context.model_copy(
        update={
            "template_id": str(template.get("template_id") or "") or None,
            "compiled_recipe_id": str(template.get("compiled_recipe_id") or "") or None,
        }
    )
    return request.model_copy(update={"manifest_context": manifest}), recipe


def _execution_result(
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
    try:
        records, findings = publish_recipe_execution(request, recipe, execution)
    except (TypeError, ValueError, ValidationError) as exc:
        failed = execution.model_copy(
            update={
                "records": (),
                "failure_code": "recipe_value_validation_failed",
                "detail": str(exc),
            }
        )
        return _failed_result(
            request,
            execution=failed,
            discovery=None,
            template=template,
            stages=stages,
            model=model,
        )
    retry_records = records
    semantic_shell = _is_semantic_detail_shell(request, records, findings)
    terminal_outcome = normalized_detail_outcome(
        http_status=request.capture.http_status,
        blocked=request.capture.blocked,
        acquisition_outcome=request.capture.acquisition_outcome,
        semantic_shell=semantic_shell,
    )
    if request.surface is Surface.ECOMMERCE_DETAIL and terminal_outcome in {
        "not_found",
        "semantic_shell",
    }:
        records = ()
    roots = tuple(str(record.get("_subject_id") or "") for record in records)
    target = TargetSelection(
        status="resolved" if records else "missing",
        root_entity_ids=roots,
        selected_root_entity_id=roots[0] if roots else None,
    )
    graph = EntityGraph(
        root_entity_ids=roots,
        entity_counts={"record": len(records)},
    )
    field_states = _field_states(request, records, execution)
    verdict = (
        "error"
        if terminal_outcome in {"not_found", "semantic_shell"}
        else _assess(request, target, records, findings)
    )
    retry = retry_request(verdict, retry_records, request)
    review = _review_required(
        request,
        verdict=verdict,
        findings=findings,
        field_states=field_states,
        retry=retry,
    )
    tier: Literal["candidate_recipe", "recipe"] = (
        "candidate_recipe" if candidate is not None else "recipe"
    )
    collector_outcomes = _discovery_collector_outcomes(
        discovery
    ) + _recipe_reader_outcomes(recipe, execution)
    metrics = _metrics(
        records,
        graph,
        verdict,
        findings=findings,
        model=model,
        collector_count=len(collector_outcomes),
    )
    return ExtractionResult(
        surface=request.surface,
        bundle_id=request.capture.bundle_id,
        records=records,
        graph=graph,
        target=target,
        findings=findings,
        field_states=field_states,
        transport_outcome=terminal_outcome,
        data_integrity=_integrity(verdict),
        verdict=verdict,
        retry_request=retry,
        metrics=metrics,
        collector_outcomes=collector_outcomes,
        stage_outcomes=stages,
        manifest_context=request.manifest_context,
        diagnostics=DiagnosticSummary(
            decision_path=tuple(row.stage for row in stages),
            extractor_tier=tier,
            trust_state=_trust_state(verdict, records, review),
            missing_critical_fields=_missing_fields(findings),
            review_required=review,
            model_invoked=bool(model and model.invoked),
            model_artifact_id=(
                model.artifact.artifact_id if model and model.artifact else None
            ),
            model_artifact_version=(
                model.artifact.artifact_version if model and model.artifact else None
            ),
            model_outcome=(
                "produced_proposals"
                if model and model.proposals
                else model.outcome
                if model
                else "not_considered"
            ),
            model_terminal_state=(
                "invoked_produced_proposals"
                if model and model.proposals
                else model.terminal_state
                if model and model.terminal_state
                else "not_considered"
            ),
            variant_coverage=_variant_coverage(records, request.requested_fields),
            additional_image_coverage=_image_coverage(
                records, request.requested_fields
            ),
        ),
        recipe_candidate=candidate,
        recipe_execution=execution,
    )


def _failed_result(
    request: ExtractionRequest,
    *,
    execution: RecipeExecutionResult | None,
    discovery: DiscoveryResult | None,
    template: dict[str, object] | None,
    stages: tuple[StageOutcome, ...],
    model: ModelRecipeProposalResult | None,
) -> ExtractionResult:
    code: RecipeFailureCode = (
        execution.failure_code
        if execution and execution.failure_code
        else discovery.failure_code
        if discovery
        else "recipe_binding_not_found"
    ) or "recipe_binding_not_found"
    terminal_outcome = _capture_outcome(request, "empty", (), ())
    verdict: Verdict = (
        "wrong_surface"
        if discovery is not None
        and discovery.detail == "wrong surface discovery target"
        else "error"
        if request.capture.acquisition_outcome == "error"
        or terminal_outcome in {"not_found", "semantic_shell"}
        else "empty"
    )
    taxonomy = _failure_taxonomy(code, request.surface)
    failure = FailureClassification(
        code=taxonomy,
        message=(execution.detail if execution else None)
        or (discovery.detail if discovery else None)
        or "No executable recipe produced a valid record.",
    )
    target = TargetSelection(
        status=(
            "wrong_surface"
            if discovery is not None
            and discovery.detail == "wrong surface discovery target"
            else "ambiguous"
            if discovery is not None
            and discovery.detail == "ambiguous discovery target"
            else "missing"
        )
    )
    field_states = (
        tuple(
            FieldEvidenceState(
                field=field,
                state="source_unavailable",
                reason_codes=("semantic_shell",),
            )
            for field in sorted(
                {
                    "image_url" if field == "image" else field
                    for field in request.requested_fields
                }
            )
        )
        if terminal_outcome == "semantic_shell"
        else ()
    )
    retry_records: tuple[PublicRecord, ...] = (
        (
            CommerceDetailRecord(
                url=request.capture.final_url,
                title=next(iter(DETAIL_SHELL_TITLE_KEYS)),
            ),
        )
        if terminal_outcome == "semantic_shell"
        else ()
    )
    retry = retry_request(verdict, retry_records, request)
    manifest = _manifest_context(request, template)
    collector_outcomes = _discovery_collector_outcomes(discovery)
    metrics = _metrics(
        (), EntityGraph(), verdict, model=model, collector_count=len(collector_outcomes)
    )
    return ExtractionResult(
        surface=request.surface,
        bundle_id=request.capture.bundle_id,
        records=(),
        target=target,
        field_states=field_states,
        verdict=verdict,
        transport_outcome=terminal_outcome,
        data_integrity=_integrity(verdict),
        retry_request=retry,
        metrics=metrics,
        collector_outcomes=collector_outcomes,
        stage_outcomes=stages,
        manifest_context=manifest,
        failure_classifications=(failure,),
        diagnostics=DiagnosticSummary(
            decision_path=tuple(row.stage for row in stages),
            extractor_tier="recipe" if template is not None else "candidate_recipe",
            trust_state=(
                "needs_review" if terminal_outcome == "semantic_shell" else "rejected"
            ),
            failure_codes=(taxonomy,),
            review_required=terminal_outcome == "semantic_shell",
            model_invoked=bool(model and model.invoked),
            model_artifact_id=(
                model.artifact.artifact_id if model and model.artifact else None
            ),
            model_artifact_version=(
                model.artifact.artifact_version if model and model.artifact else None
            ),
            model_outcome=model.outcome if model else "not_considered",
            model_terminal_state=(
                model.terminal_state
                if model and model.terminal_state
                else "not_considered"
            ),
        ),
        recipe_execution=execution,
    )


def _blocked_result(
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
    return ExtractionResult(
        surface=request.surface,
        bundle_id=request.capture.bundle_id,
        records=(),
        evidence=evidence,
        findings=(finding,),
        verdict="blocked",
        transport_outcome="blocked",
        data_integrity="blocked",
        metrics=ExtractionMetrics(
            collector_count=len(tuple(collector_outcomes)), verdict="blocked"
        ),
        collector_outcomes=tuple(collector_outcomes),
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


def _assess(
    request: ExtractionRequest,
    target: TargetSelection,
    records: tuple[PublicRecord, ...],
    findings: tuple[Finding, ...],
) -> Verdict:
    if request.surface is Surface.ECOMMERCE_DETAIL and (
        request.capture.http_status in DETAIL_NOT_FOUND_HTTP_STATUS_CODES
        or _is_semantic_detail_shell(request, records, findings)
    ):
        return "error"
    if request.capture.acquisition_outcome in {"blocked", "error"}:
        return cast(Verdict, request.capture.acquisition_outcome)
    if any(row.rule_id == "PUBLIC_RESOLUTION_DIVERGENCE" for row in findings):
        return "invalid"
    if any(row.blocking for row in findings):
        return "error" if request.surface is Surface.JOB_DETAIL else "invalid"
    if target.status == "ambiguous":
        return "review"
    if not records:
        return "empty"
    if request.surface is Surface.ECOMMERCE_DETAIL:
        if _is_semantic_detail_shell(request, records, findings):
            return "error"
        missing_requested = {
            "image_url" if field == "image" else field
            for field in request.requested_fields
            if records[0].get("image_url" if field == "image" else field)
            in (None, "", [], {}, ())
        }
        if missing_requested or any(
            row.rule_id in {"MISSING_CONTRACT_FIELD", "VARIANT_AVAILABILITY_MISSING"}
            for row in findings
        ):
            return "partial"
    return "success"


def _review_required(request, *, verdict, findings, field_states, retry) -> bool:
    if verdict == "review":
        return True
    if retry is not None and retry.required:
        return False
    if any(
        row.rule_id in DETAIL_REVIEW_RISK_FINDING_RULE_IDS and row.scope != "candidate"
        for row in findings
    ):
        return True
    states = {row.field: row.state for row in field_states}
    if any(
        states.get(f"variants.{field}") == "captured_published"
        and states.get(field) not in {"captured_published", "captured_and_resolved"}
        for field in DETAIL_REVIEW_PARENT_CHILD_DIVERGENCE_FIELDS
    ):
        return True
    requested = {
        "image_url" if field == "image" else field for field in request.requested_fields
    } & DETAIL_REVIEW_HIGH_VALUE_REQUESTED_FIELDS
    return any(
        states.get(field) not in {"captured_published", "captured_and_resolved"}
        for field in requested
    )


def _field_states(
    request: ExtractionRequest,
    records: tuple[PublicRecord, ...],
    execution: RecipeExecutionResult,
) -> tuple[FieldEvidenceState, ...]:
    resolved = {
        row.binding_id.removeprefix("field."): row
        for row in execution.outcomes
        if row.status == "resolved" and row.binding_id.startswith("field.")
    }
    published = {
        key
        for record in records
        for key, value in record.model_dump(mode="python").items()
        if not key.startswith("_") and value not in (None, "", [], {}, ())
    }
    fields = (
        set(field_mappings.ECOMMERCE_PUBLIC_FIELD_FACT_TYPES)
        | {"variants", "variant_count"}
        | published
    )
    source_capabilities = dict(request.capture.acquisition_diagnostics or {}).get(
        "source_capabilities"
    )
    affected = set(
        source_capabilities.get("affected_field_families", ())
        if isinstance(source_capabilities, dict)
        else ()
    )
    return tuple(
        FieldEvidenceState(
            field=field,
            state=(
                "captured_published"
                if field in published
                else "not_requested"
                if field == "variants" and field not in request.requested_fields
                else "source_unavailable"
                if field in affected or field == "image_url" and "images" in affected
                else "not_present_in_captured_sources"
            ),
            reason_codes=(
                (resolved[field].binding_id,)
                if field in resolved
                else ("product_data_source_unavailable",)
                if field in affected or field == "image_url" and "images" in affected
                else ()
            ),
        )
        for field in sorted(fields)
    )


def _recipe_reader_outcomes(
    recipe: ExtractionRecipe, execution: RecipeExecutionResult
) -> tuple[CollectorOutcome, ...]:
    sources = {
        binding.source
        for binding in (
            recipe.record_root,
            *recipe.identity,
            *sum(recipe.fields.values(), ()),
        )
    }
    return tuple(
        CollectorOutcome(
            collector_id=f"recipe_reader:{source}",
            outcome="produced_evidence",
            evidence_count=sum(row.status == "resolved" for row in execution.outcomes),
        )
        for source in sorted(sources)
    )


def _discovery_collector_outcomes(
    discovery: DiscoveryResult | None,
) -> tuple[CollectorOutcome, ...]:
    if discovery is None:
        return ()
    return tuple(
        CollectorOutcome.model_validate(row) for row in discovery.collector_diagnostics
    )


def _metrics(
    records: tuple[PublicRecord, ...],
    graph: EntityGraph,
    verdict: Verdict,
    *,
    findings: tuple[Finding, ...] = (),
    model: ModelRecipeProposalResult | None,
    collector_count: int = 0,
) -> ExtractionMetrics:
    public_fields = sum(
        sum(not str(key).startswith("_") for key in record.model_dump(mode="python"))
        for record in records
    )
    lineage_fields = sum(len(dict(record.get("_lineage") or {})) for record in records)
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
        entity_counts=graph.entity_counts,
        variant_count=sum(len(record.get("variants") or ()) for record in records),
        public_lineage_coverage=(
            lineage_fields / public_fields if public_fields else 0.0
        ),
        completeness_score=completeness_score,
        verdict=verdict,
        universal_representation_build_count=int(
            bool(model and model.representation_built)
        ),
        universal_model_invocation_count=int(bool(model and model.invoked)),
        universal_model_latency_ms=model.latency_ms if model else 0.0,
        universal_model_service_failure_count=int(
            bool(model and model.failure_code == "model_service_failure")
        ),
        universal_model_ungrounded_rejection_count=(
            model.ungrounded_rejection_count if model else 0
        ),
        universal_model_ungrounded_rejection_rate=(
            model.ungrounded_rejection_count / model.prediction_count
            if model and model.prediction_count
            else 0.0
        ),
        universal_model_cost_usd=model.cost_usd if model else 0.0,
        universal_model_cost_per_1000_pages=(model.cost_usd * 1000 if model else 0.0),
        universal_model_input_tokens=model.input_tokens if model else 0,
        universal_model_output_tokens=model.output_tokens if model else 0,
    )


def _execution_stage(stage: str, execution: RecipeExecutionResult) -> StageOutcome:
    return StageOutcome(
        stage=stage,
        outcome="ran" if execution.records else "failed",
        detail=execution.failure_code or execution.detail,
    )


def _discovery_stage(stage: str, discovery: DiscoveryResult) -> StageOutcome:
    return StageOutcome(
        stage=stage,
        outcome="ran" if discovery.candidate else "no_match",
        detail=discovery.failure_code or discovery.detail,
    )


def _model_stage(model: ModelRecipeProposalResult) -> StageOutcome:
    outcome: Literal[
        "produced_evidence",
        "no_match",
        "failed",
        "timed_out",
        "budget_limited",
        "skipped",
    ] = (
        "produced_evidence"
        if model.proposals
        else (
            cast(
                Literal["no_match", "failed", "timed_out", "budget_limited"],
                model.outcome,
            )
            if model.outcome in {"no_match", "failed", "timed_out", "budget_limited"}
            else "skipped"
        )
    )
    return StageOutcome(
        stage="model_recipe_proposal", outcome=outcome, detail=model.detail
    )


def _failure_taxonomy(code: RecipeFailureCode, surface: Surface):
    if code == "recipe_capture_requirement_missing":
        return "insufficient_input_bundle"
    if code == "recipe_root_not_found":
        return (
            "listing_detection_failed" if listing_schema(surface) else "record_boundary"
        )
    if code in {"recipe_identity_mismatch", "recipe_join_failed"}:
        return "entity_binding"
    if code == "recipe_binding_not_found":
        return "listing_detection_failed" if listing_schema(surface) else "discovery"
    return "validation"


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


def _capture_outcome(request, verdict, findings, records) -> str:
    if request.surface is not Surface.ECOMMERCE_DETAIL:
        return request.capture.acquisition_outcome or "unknown"
    browser = dict(request.capture.acquisition_diagnostics or {}).get(
        "browser_diagnostics"
    )
    return normalized_detail_outcome(
        http_status=request.capture.http_status,
        blocked=request.capture.blocked,
        acquisition_outcome=request.capture.acquisition_outcome,
        browser_outcome=(
            str(browser.get("browser_outcome") or "")
            if isinstance(browser, dict)
            else None
        ),
        semantic_shell=_is_semantic_detail_shell(request, records, findings),
    )


def _is_semantic_detail_shell(request, records, findings) -> bool:
    if request.surface is not Surface.ECOMMERCE_DETAIL:
        return False
    record = records[0] if records else None
    if (record is not None and is_shell_record(record)) or any(
        row.rule_id == DETAIL_SHELL_FINDING_RULE_ID for row in findings
    ):
        return True
    if record is None:
        artifact = next(
            (
                row
                for row in request.capture.artifacts
                if row.artifact_type in {"rendered_html", "http_html"}
            ),
            None,
        )
        if artifact is not None:
            document = request.artifact_reader.document_store.html(artifact.artifact_id)
            classification = classify_blocked_page(
                document.html(), request.capture.http_status or 200
            )
            if classification.blocked or classification.outcome in {
                "challenge_page",
                "low_content_shell",
            }:
                return True
            title_node = document.css_first("h1") or document.css_first("title")
            if title_node is not None and is_shell_record(
                CommerceDetailRecord(
                    url=request.capture.final_url,
                    title=title_node.content_text(),
                )
            ):
                return True
    requested_host = normalize_domain(request.capture.requested_url)
    final_host = normalize_domain(request.capture.final_url)
    thin = record is None or not any(
        record.get(field) not in (None, "", [], {}, ())
        for field in DETAIL_SHELL_MEANINGFUL_RECORD_FIELDS
    )
    return bool(record is not None and thin and requested_host != final_host)


def _missing_fields(findings: tuple[Finding, ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(row.metadata.get("field"))
                for row in findings
                if row.rule_id == "MISSING_CONTRACT_FIELD" and row.metadata.get("field")
            }
        )
    )


def _variant_coverage(records, requested_fields):
    if "variants" not in requested_fields:
        return "not_applicable"
    return "complete" if records and records[0].get("variants") else "partial"


def _image_coverage(records, requested_fields):
    if not {"image", "image_url", "additional_images"}.intersection(requested_fields):
        return "not_applicable"
    return "complete" if records and records[0].get("image_url") else "partial"


def _integrity(verdict: Verdict):
    if verdict == "blocked":
        return "blocked"
    if verdict == "success":
        return "clean"
    if verdict in {"partial", "review"}:
        return "partial"
    if verdict in {"invalid", "error"}:
        return "defect"
    return "unknown"


def _trust_state(
    verdict: Verdict,
    records: tuple[PublicRecord, ...],
    review_required: bool,
) -> Literal["verified", "partial", "needs_review", "rejected", "blocked", "unknown"]:
    if verdict == "blocked":
        return "blocked"
    if review_required or verdict == "review":
        return "needs_review"
    if verdict == "success":
        return "verified"
    if verdict == "partial":
        return "partial"
    if verdict in {"invalid", "error", "wrong_surface", "empty"} or not records:
        return "rejected"
    return "unknown"
