"""Common extraction orchestration: Harvest → Resolve → Publish."""

from __future__ import annotations

from time import perf_counter
from typing import Literal, cast

from app.core.config.extraction_rules import (
    DETAIL_NOT_FOUND_HTTP_STATUS_CODES,
    DETAIL_SHELL_FINDING_RULE_ID,
)
from app.core.extraction_memory.contract_runtime import match_template
from app.extraction.adapters import adapter_for, harvest_compiled_recipe
from app.extraction.contracts import (
    DiagnosticSummary,
    EntityGraph,
    Evidence,
    ExecutionManifestContext,
    ExtractionRequest,
    ExtractionResult,
    FailureClassification,
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
    compiled_template = _compiled_recipe_template(request)
    extractor_tier: Literal["deterministic", "recipe"] = "deterministic"
    if compiled_template is not None:
        harvest = harvest_compiled_recipe(request)
        if any(row.collector_id == "css_recipe" for row in harvest.evidence):
            extractor_tier = "recipe"
        else:
            harvest = adapter.harvest(request)
    else:
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
    failures = _failure_classifications(
        request,
        verdict=verdict,
        records=records,
        target=resolution.target,
        findings=findings,
        evidence=harvest.evidence,
    )
    field_states = resolution.field_states
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
        transport_outcome=request.capture.acquisition_outcome,
        data_integrity=data_integrity_status(verdict, field_states, findings),
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
        manifest_context=_manifest_context(request, compiled_template),
        failure_classifications=failures,
        diagnostics=_diagnostic_summary(
            verdict=verdict,
            records=records,
            evidence=harvest.evidence,
            stage_outcomes=tuple(stage_outcomes),
            field_states=field_states,
            failures=failures,
            extractor_tier=extractor_tier,
        ),
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
    compiled_recipe = template.get("compiled_recipe")
    if not isinstance(compiled_recipe, dict):
        return None
    selector_rules = compiled_recipe.get("selector_rules")
    if not isinstance(selector_rules, list) or not selector_rules:
        return None
    return template


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
        manifest_context=request.manifest_context,
        failure_classifications=failures,
        diagnostics=_diagnostic_summary(
            verdict="blocked",
            records=(),
            evidence=evidence,
            stage_outcomes=(_stage_outcome("harvest", len(evidence)),),
            field_states=states,
            failures=failures,
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
) -> tuple[FailureClassification, ...]:
    if records:
        return ()
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
    extractor_tier: Literal["deterministic", "recipe"] = "deterministic",
) -> DiagnosticSummary:
    missing = tuple(
        row.field
        for row in field_states
        if row.state in {"not_present_in_captured_sources", "source_unavailable"}
    )
    trust_state = cast(
        Literal[
            "verified",
            "partial",
            "needs_review",
            "rejected",
            "blocked",
            "unknown",
        ],
        "verified"
        if verdict == "success"
        else "partial"
        if verdict == "partial"
        else "needs_review"
        if verdict == "review"
        else "blocked"
        if verdict == "blocked"
        else "rejected"
        if verdict in {"invalid", "error", "wrong_surface", "empty"} or not records
        else "unknown",
    )
    return DiagnosticSummary(
        decision_path=tuple(row.stage for row in stage_outcomes),
        extractor_tier="blocked" if verdict == "blocked" else extractor_tier,
        trust_state=trust_state,
        missing_critical_fields=missing,
        failure_codes=tuple(row.code for row in failures),
        evidence_count=len(evidence),
        review_required=verdict == "review",
    )
