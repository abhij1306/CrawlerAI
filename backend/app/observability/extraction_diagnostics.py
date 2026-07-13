"""Observe-only extraction diagnostics, causal states, and counts."""

from __future__ import annotations

from typing import Literal, TypedDict, cast

from app.acquisition.browser_block_detection import classify_blocked_page
from app.core.config import field_mappings
from app.core.config.extraction_rules import (
    DETAIL_SHELL_FINDING_RULE_ID,
    DETAIL_SHELL_MEANINGFUL_RECORD_FIELDS,
    DETAIL_SHELL_TITLE_KEYS,
)
from app.core.domain_utils import normalize_domain
from app.core.extraction_memory.recipe_contracts import (
    DiscoveryResult,
    RecipeExecutionResult,
    RecipeFailureCode,
)
from app.core.records.detail_outcome import normalized_detail_outcome
from app.core.shared.text_coerce import slug_tokens
from app.extraction.contracts import (
    CollectorOutcome,
    CommerceDetailRecord,
    DiagnosticSummary,
    EntityGraph,
    ExtractionMetrics,
    ExtractionRequest,
    FieldEvidenceState,
    Finding,
    PublicRecord,
    StageOutcome,
    Verdict,
)
from app.extraction.model_runtime import ModelRecipeProposalResult
from app.extraction.surfaces import Surface, listing_schema

_EMPTY_VALUES: tuple[object, ...] = (None, "", [], {}, ())

FieldStateName = Literal[
    "captured_and_resolved",
    "captured_but_rejected",
    "captured_conflicting",
    "capture_incomplete",
    "collector_missed",
    "join_failed",
    "interaction_required",
    "source_unavailable",
    "not_present_in_captured_sources",
    "output_divergent",
    "not_captured",
    "captured_published",
    "captured_suppressed",
    "captured_unowned",
    "not_present_in_source",
    "not_requested",
]


class _ModelMetrics(TypedDict):
    universal_representation_build_count: int
    universal_model_invocation_count: int
    universal_model_latency_ms: float
    universal_model_service_failure_count: int
    universal_model_ungrounded_rejection_count: int
    universal_model_ungrounded_rejection_rate: float
    universal_model_cost_usd: float
    universal_model_cost_per_1000_pages: float
    universal_model_input_tokens: int
    universal_model_output_tokens: int


def _completeness_score(findings: tuple[Finding, ...]) -> float:
    return next(
        (
            float(row.metadata.get("score", 0.0))
            for row in findings
            if row.rule_id == "RECORD_COMPLETENESS"
        ),
        0.0,
    )


def is_shell_record(record: PublicRecord | None) -> bool:
    title = " ".join(slug_tokens(record.get("title"))) if record else ""
    return bool(title and title in DETAIL_SHELL_TITLE_KEYS)


def metrics(
    records: tuple[PublicRecord, ...],
    graph: EntityGraph,
    verdict: Verdict,
    *,
    findings: tuple[Finding, ...] = (),
    model: ModelRecipeProposalResult | None,
    collector_count: int = 0,
) -> ExtractionMetrics:
    public_fields = sum(_public_field_count(record) for record in records)
    lineage_fields = sum(len(dict(record.get("_lineage") or {})) for record in records)
    return ExtractionMetrics(
        collector_count=collector_count,
        entity_counts=graph.entity_counts,
        variant_count=sum(len(record.get("variants") or ()) for record in records),
        public_lineage_coverage=(
            lineage_fields / public_fields if public_fields else 0.0
        ),
        completeness_score=_completeness_score(findings),
        verdict=verdict,
        **_model_metrics(model),
    )


def _resolved_bindings(execution: RecipeExecutionResult):
    return {
        row.binding_id.removeprefix("field."): row
        for row in execution.outcomes
        if row.status == "resolved" and row.binding_id.startswith("field.")
    }


def _affected_field_families(request: ExtractionRequest) -> set[str]:
    capabilities = dict(request.capture.acquisition_diagnostics or {}).get(
        "source_capabilities"
    )
    if not isinstance(capabilities, dict):
        return set()
    return set(capabilities.get("affected_field_families", ()))


def is_semantic_detail_shell(
    request: ExtractionRequest,
    records: tuple[PublicRecord, ...],
    findings: tuple[Finding, ...],
) -> bool:
    if request.surface is not Surface.ECOMMERCE_DETAIL:
        return False
    record = records[0] if records else None
    if _record_or_finding_is_shell(record, findings):
        return True
    if record is None and _captured_document_is_shell(request):
        return True
    return _redirected_thin_record(request, record)


def _redirected_thin_record(request, record) -> bool:
    if record is None:
        return False
    thin = not any(
        record.get(field) not in _EMPTY_VALUES
        for field in DETAIL_SHELL_MEANINGFUL_RECORD_FIELDS
    )
    return bool(
        thin
        and normalize_domain(request.capture.requested_url)
        != normalize_domain(request.capture.final_url)
    )


def _model_metrics(model: ModelRecipeProposalResult | None) -> _ModelMetrics:
    predictions = model.prediction_count if model else 0
    rejected = model.ungrounded_rejection_count if model else 0
    cost = model.cost_usd if model else 0.0
    return {
        "universal_representation_build_count": int(
            bool(model and model.representation_built)
        ),
        "universal_model_invocation_count": int(bool(model and model.invoked)),
        "universal_model_latency_ms": model.latency_ms if model else 0.0,
        "universal_model_service_failure_count": int(
            bool(model and model.failure_code == "model_service_failure")
        ),
        "universal_model_ungrounded_rejection_count": rejected,
        "universal_model_ungrounded_rejection_rate": (
            rejected / predictions if predictions else 0.0
        ),
        "universal_model_cost_usd": cost,
        "universal_model_cost_per_1000_pages": cost * 1000,
        "universal_model_input_tokens": model.input_tokens if model else 0,
        "universal_model_output_tokens": model.output_tokens if model else 0,
    }


def _published_fields(records: tuple[PublicRecord, ...]) -> set[str]:
    return {
        key
        for record in records
        for key, value in record.model_dump(mode="python").items()
        if not key.startswith("_") and value not in _EMPTY_VALUES
    }


def variant_coverage(records, requested_fields):
    if "variants" not in requested_fields:
        return "not_applicable"
    return "complete" if records and records[0].get("variants") else "partial"


def _record_or_finding_is_shell(record, findings) -> bool:
    return bool(
        (record is not None and is_shell_record(record))
        or any(row.rule_id == DETAIL_SHELL_FINDING_RULE_ID for row in findings)
    )


def _public_field_count(record: PublicRecord) -> int:
    return sum(not str(key).startswith("_") for key in record.model_dump(mode="python"))


def trust_state(
    verdict: Verdict,
    records: tuple[PublicRecord, ...],
    review: bool,
) -> Literal["verified", "partial", "needs_review", "rejected", "blocked", "unknown"]:
    if verdict == "blocked":
        return "blocked"
    if review or verdict == "review":
        return "needs_review"
    if verdict == "success":
        return "verified"
    if verdict == "partial":
        return "partial"
    if verdict in {"invalid", "error", "wrong_surface", "empty"} or not records:
        return "rejected"
    return "unknown"


def integrity(verdict: Verdict):
    if verdict == "blocked":
        return "blocked"
    if verdict == "success":
        return "clean"
    if verdict in {"partial", "review"}:
        return "partial"
    if verdict in {"invalid", "error"}:
        return "defect"
    return "unknown"


def image_coverage(records, requested_fields):
    if not {"image", "image_url", "additional_images"}.intersection(requested_fields):
        return "not_applicable"
    return "complete" if records and records[0].get("image_url") else "partial"


def capture_outcome(
    request: ExtractionRequest,
    findings: tuple[Finding, ...],
    records: tuple[PublicRecord, ...],
) -> str:
    if request.surface is not Surface.ECOMMERCE_DETAIL:
        return request.capture.acquisition_outcome or "unknown"
    browser = dict(request.capture.acquisition_diagnostics or {}).get(
        "browser_diagnostics"
    )
    browser_outcome = (
        str(browser.get("browser_outcome") or "") if isinstance(browser, dict) else None
    )
    return normalized_detail_outcome(
        http_status=request.capture.http_status,
        blocked=request.capture.blocked,
        acquisition_outcome=request.capture.acquisition_outcome,
        browser_outcome=browser_outcome,
        semantic_shell=is_semantic_detail_shell(request, records, findings),
    )


def field_states(
    request: ExtractionRequest,
    records: tuple[PublicRecord, ...],
    execution: RecipeExecutionResult,
) -> tuple[FieldEvidenceState, ...]:
    resolved = _resolved_bindings(execution)
    published = _published_fields(records)
    affected = _affected_field_families(request)
    fields = (
        set(field_mappings.ECOMMERCE_PUBLIC_FIELD_FACT_TYPES)
        | {"variants", "variant_count"}
        | published
    )
    return tuple(
        _field_state(request, field, published, affected, resolved)
        for field in sorted(fields)
    )


def missing_fields(findings: tuple[Finding, ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(row.metadata.get("field"))
                for row in findings
                if row.rule_id == "MISSING_CONTRACT_FIELD" and row.metadata.get("field")
            }
        )
    )


def _captured_document_is_shell(request: ExtractionRequest) -> bool:
    artifact = next(
        (
            row
            for row in request.capture.artifacts
            if row.artifact_type in {"rendered_html", "http_html"}
        ),
        None,
    )
    if artifact is None:
        return False
    try:
        document = request.artifact_reader.document_store.html(artifact.artifact_id)
    except (KeyError, ValueError):
        return False
    classification = classify_blocked_page(
        document.html(), request.capture.http_status or 200
    )
    if classification.blocked or classification.outcome in {
        "challenge_page",
        "low_content_shell",
    }:
        return True
    title_node = document.css_first("h1") or document.css_first("title")
    return bool(
        title_node is not None
        and is_shell_record(
            CommerceDetailRecord(
                url=request.capture.final_url,
                title=title_node.content_text(),
            )
        )
    )


def _field_state(request, field, published, affected, resolved) -> FieldEvidenceState:
    unavailable = field in affected or field == "image_url" and "images" in affected
    state: FieldStateName
    if field in published:
        state = "captured_published"
    elif field == "variants" and field not in request.requested_fields:
        state = "not_requested"
    elif unavailable:
        state = "source_unavailable"
    else:
        state = "not_present_in_captured_sources"
    reasons = (
        (resolved[field].binding_id,)
        if field in resolved
        else ("product_data_source_unavailable",)
        if unavailable
        else ()
    )
    return FieldEvidenceState(field=field, state=state, reason_codes=reasons)


def model_stage(model: ModelRecipeProposalResult) -> StageOutcome:
    outcomes = {"no_match", "failed", "timed_out", "budget_limited"}
    if model.proposals:
        outcome = "produced_evidence"
    elif model.outcome in outcomes:
        outcome = model.outcome
    else:
        outcome = "skipped"
    return StageOutcome(
        stage="model_recipe_proposal",
        outcome=cast(
            Literal[
                "produced_evidence",
                "no_match",
                "failed",
                "timed_out",
                "budget_limited",
                "skipped",
            ],
            outcome,
        ),
        detail=model.detail,
    )


def _execution_diagnostics(
    request, records, findings, verdict, review, candidate, stages, model
):
    model_outcome, terminal_state = _model_diagnostic_state(model)
    return DiagnosticSummary(
        decision_path=tuple(row.stage for row in stages),
        extractor_tier="candidate_recipe" if candidate is not None else "recipe",
        trust_state=trust_state(verdict, records, review),
        missing_critical_fields=missing_fields(findings),
        review_required=review,
        model_invoked=bool(model and model.invoked),
        model_artifact_id=model.artifact.artifact_id
        if model and model.artifact
        else None,
        model_artifact_version=(
            model.artifact.artifact_version if model and model.artifact else None
        ),
        model_outcome=model_outcome,
        model_terminal_state=terminal_state,
        variant_coverage=variant_coverage(records, request.requested_fields),
        additional_image_coverage=image_coverage(records, request.requested_fields),
    )


def _failure_diagnostics(taxonomy, terminal_outcome, template, stages, model):
    return DiagnosticSummary(
        decision_path=tuple(row.stage for row in stages),
        extractor_tier="recipe" if template is not None else "candidate_recipe",
        trust_state="needs_review"
        if terminal_outcome == "semantic_shell"
        else "rejected",
        failure_codes=(taxonomy,),
        review_required=terminal_outcome == "semantic_shell",
        model_invoked=bool(model and model.invoked),
        model_artifact_id=model.artifact.artifact_id
        if model and model.artifact
        else None,
        model_artifact_version=(
            model.artifact.artifact_version if model and model.artifact else None
        ),
        model_outcome=model.outcome if model else "not_considered",
        model_terminal_state=(
            model.terminal_state if model and model.terminal_state else "not_considered"
        ),
    )


def _model_diagnostic_state(model):
    if model and model.proposals:
        return "produced_proposals", "invoked_produced_proposals"
    if model is None:
        return "not_considered", "not_considered"
    return model.outcome, model.terminal_state or "not_considered"


def _failure_message(execution, discovery):
    if execution and execution.detail:
        return execution.detail
    if discovery and discovery.detail:
        return discovery.detail
    return "No executable recipe produced a valid record."


def _failure_field_states(request, terminal_outcome):
    if terminal_outcome != "semantic_shell":
        return ()
    fields = {
        "image_url" if field == "image" else field for field in request.requested_fields
    }
    return tuple(
        FieldEvidenceState(
            field=field,
            state="source_unavailable",
            reason_codes=("semantic_shell",),
        )
        for field in sorted(fields)
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


def _recipe_reader_outcomes(recipe, execution):
    sources = {
        binding.source
        for binding in (
            recipe.record_root,
            *recipe.identity,
            *sum(recipe.fields.values(), ()),
        )
    }
    resolved = sum(row.status == "resolved" for row in execution.outcomes)
    return tuple(
        CollectorOutcome(
            collector_id=f"recipe_reader:{source}",
            outcome="produced_evidence",
            evidence_count=resolved,
        )
        for source in sorted(sources)
    )


def _discovery_collector_outcomes(discovery):
    if discovery is None:
        return ()
    return tuple(
        CollectorOutcome.model_validate(row) for row in discovery.collector_diagnostics
    )


def discovery_stage(stage: str, discovery: DiscoveryResult) -> StageOutcome:
    return StageOutcome(
        stage=stage,
        outcome="ran" if discovery.candidate else "no_match",
        detail=discovery.failure_code or discovery.detail,
    )


def execution_stage(stage: str, execution: RecipeExecutionResult) -> StageOutcome:
    return StageOutcome(
        stage=stage,
        outcome="ran" if execution.records else "failed",
        detail=execution.failure_code or execution.detail,
    )
