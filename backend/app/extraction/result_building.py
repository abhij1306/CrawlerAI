from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import typing
from typing import Any

from app.core.config.extraction_rules._detail import (
    DETAIL_TERMINAL_SOURCE_UNAVAILABLE_OUTCOMES,
    DETAIL_SHELL_TITLE_FLAG,
    DETAIL_SHELL_TITLE_KEYS,
)
from app.core.config import field_mappings
from app.core.config.cascade import CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
from app.core.config.variant_policy import CHILD_JOIN_FAILED_RULE_ID
from app.core.config.variant_policy import DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
from app.core.records.field_policy import canonical_fields_for_surface
from app.core.records.detail_outcome import normalized_detail_outcome
from app.core.shared.text_coerce import slug_tokens
from app.extraction.contracts import (
    Decision,
    EvidenceDisposition,
    EntityGraph,
    Evidence,
    ExtractionMetrics,
    ExtractionRequest,
    FieldEvidenceState,
    Finding,
    PublicationProjection,
    PublicRecord,
    ResolutionResult,
    RetryRequest,
    SelectedFact,
    TargetSelection,
)
from app.extraction.entities import EntitySet
from app.extraction.field_states import FieldStateName, field_state
from app.core.shared.ids import stable_id
from app.extraction.surfaces import Surface, SurfaceSpec


def decisions(resolution: Any) -> tuple[Decision, ...]:
    if isinstance(resolution, ResolutionResult):
        return resolution.decisions
    return tuple(resolution or ())


def selected_facts(
    decision_rows: tuple[Decision, ...], evidence: tuple[Evidence, ...]
) -> tuple[SelectedFact, ...]:
    """Build direct resolved truth. Inheritance remains derived truth."""

    evidence_by_id = {row.evidence_id: row for row in evidence}
    facts: list[SelectedFact] = []
    for decision in decision_rows:
        if (
            decision.status != "resolved"
            or len(decision.accepted_evidence_ids) != 1
            or decision.rule_id == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
        ):
            continue
        accepted = evidence_by_id.get(decision.accepted_evidence_ids[0])
        if accepted is None:
            continue
        facts.append(
            SelectedFact(
                selected_fact_id=stable_id("selected", decision.decision_id),
                decision_id=decision.decision_id,
                entity_id=decision.entity_id,
                fact_type=decision.fact_type,
                value=accepted.value,
                evidence_ids=decision.accepted_evidence_ids,
                rule_id=decision.rule_id,
            )
        )
    return tuple(facts)


def assert_resolution_accounting(
    evidence: tuple[Evidence, ...],
    decisions: tuple[Decision, ...],
    selected_rows: tuple[SelectedFact, ...],
    dispositions: tuple[EvidenceDisposition, ...],
) -> None:
    """Fail closed when resolution accounting stops being exact."""

    evidence_ids = [row.evidence_id for row in evidence]
    disposition_ids = [row.evidence_id for row in dispositions]
    if Counter(evidence_ids) != Counter(disposition_ids):
        raise RuntimeError("every evidence row must have exactly one disposition")
    evidence_by_id = {row.evidence_id: row for row in evidence}
    decisions_by_id = {row.decision_id: row for row in decisions}
    for selected in selected_rows:
        decision = decisions_by_id.get(selected.decision_id)
        if decision is None:
            raise RuntimeError("selected fact references a missing decision")
        if selected.evidence_ids != decision.accepted_evidence_ids:
            raise RuntimeError(
                "selected fact evidence does not match accepted evidence"
            )
        if len(selected.evidence_ids) != 1:
            raise RuntimeError(
                "selected facts must represent one direct evidence value"
            )
        accepted = evidence_by_id.get(selected.evidence_ids[0])
        if accepted is None:
            raise RuntimeError("selected fact references missing evidence")
        if selected.value != accepted.value:
            raise RuntimeError("selected fact value diverges from accepted evidence")


def evidence_dispositions(
    evidence: tuple[Evidence, ...],
    decision_rows: tuple[Decision, ...],
    selected_rows: tuple[SelectedFact, ...],
    target: TargetSelection | None = None,
) -> tuple[EvidenceDisposition, ...]:
    """Assign exactly one terminal accounting state to every evidence row."""

    selected_by_evidence = {
        evidence_id: row for row in selected_rows for evidence_id in row.evidence_ids
    }
    accepted_by_evidence: dict[str, Decision] = {}
    rejected_by_evidence: dict[str, tuple[Decision, str]] = {}
    for decision in decision_rows:
        for evidence_id in decision.accepted_evidence_ids:
            accepted_by_evidence.setdefault(evidence_id, decision)
        for rejected in decision.rejected:
            rejected_by_evidence.setdefault(
                rejected.evidence_id, (decision, rejected.reason)
            )
    return tuple(
        _evidence_disposition(
            row,
            accepted_by_evidence.get(row.evidence_id),
            rejected_by_evidence.get(row.evidence_id),
            selected_by_evidence.get(row.evidence_id),
            target,
        )
        for row in evidence
    )


def _evidence_disposition(
    evidence: Evidence,
    accepted: Decision | None,
    rejected: tuple[Decision, str] | None,
    selected: SelectedFact | None,
    target: TargetSelection | None,
) -> EvidenceDisposition:
    if accepted is not None:
        return EvidenceDisposition(
            evidence_id=evidence.evidence_id,
            entity_id=accepted.entity_id,
            status="conflicted" if accepted.status == "conflicted" else "accepted",
            reason_code=accepted.rule_id,
            decision_id=accepted.decision_id,
            selected_fact_id=selected.selected_fact_id if selected else None,
        )
    if rejected is not None:
        decision, reason = rejected
        invalid = reason not in {"lower_confidence", "stable_tiebreak"}
        return EvidenceDisposition(
            evidence_id=evidence.evidence_id,
            entity_id=decision.entity_id,
            status="rejected_invalid" if invalid else "rejected_lower_rank",
            reason_code=reason,
            decision_id=decision.decision_id,
        )
    if target is not None and target.status in {"ambiguous", "missing"}:
        return EvidenceDisposition(
            evidence_id=evidence.evidence_id,
            entity_id=evidence.subject_id,
            status="unowned",
            reason_code=f"target_{target.status}",
        )
    if (
        target is not None
        and target.status == "resolved"
        and target.root_entity_ids
        and evidence.subject_id
        and evidence.subject_id not in set(target.root_entity_ids)
    ):
        return EvidenceDisposition(
            evidence_id=evidence.evidence_id,
            entity_id=evidence.subject_id,
            status="outside_selected_target",
            reason_code="outside_selected_target",
        )
    return EvidenceDisposition(
        evidence_id=evidence.evidence_id,
        status="diagnostic_only",
        reason_code="not_considered_by_current_resolver",
    )


def field_evidence_states(
    records: tuple[PublicRecord, ...],
    evidence: tuple[Evidence, ...],
    decision_rows: tuple[Decision, ...],
    request: ExtractionRequest,
    *,
    primary_product_entity_id: str | None = None,
    primary_offer_entity_id: str | None = None,
) -> tuple[FieldEvidenceState, ...]:
    record = records[0] if records else None
    public_to_fact = field_mappings.ECOMMERCE_PUBLIC_FIELD_FACT_TYPES
    requested = {
        "image_url" if field == "image" else field for field in request.requested_fields
    }
    fields = tuple(dict.fromkeys((*public_to_fact, *sorted(requested))))
    affected = set(_unavailable_field_families(request))
    terminal_unavailable = _terminal_source_unavailable(request)
    by_fact = {
        fact: tuple(row for row in evidence if row.fact_type == fact)
        for fact in set(public_to_fact.values())
    }
    decisions_by_fact = {
        fact: tuple(row for row in decision_rows if row.fact_type == fact)
        for fact in set(public_to_fact.values())
    }
    return tuple(
        _legacy_field_evidence_state(
            field,
            record=record,
            public_to_fact=public_to_fact,
            by_fact=by_fact,
            decisions_by_fact=decisions_by_fact,
            affected=affected,
            terminal_unavailable=terminal_unavailable,
            primary_product_entity_id=primary_product_entity_id,
            primary_offer_entity_id=primary_offer_entity_id,
        )
        for field in fields
    )


def _legacy_field_evidence_state(
    field: str,
    *,
    record: PublicRecord | None,
    public_to_fact: dict[str, str],
    by_fact: dict[str, tuple[Evidence, ...]],
    decisions_by_fact: dict[str, tuple[Decision, ...]],
    affected: set[str],
    terminal_unavailable: bool,
    primary_product_entity_id: str | None,
    primary_offer_entity_id: str | None,
) -> FieldEvidenceState:
    fact = public_to_fact.get(field)
    rows = by_fact.get(fact, ()) if fact else ()
    target_entity_id = (
        primary_offer_entity_id
        if fact
        in {
            field_mappings.OFFER_PRICE_FACT_TYPE,
            field_mappings.OFFER_CURRENCY_FACT_TYPE,
            field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
        }
        else primary_product_entity_id
    )
    relevant_decisions = tuple(
        row
        for row in (decisions_by_fact.get(fact, ()) if fact else ())
        if target_entity_id is None or row.entity_id == target_entity_id
    )
    present = bool(record and record.get(field) not in (None, "", [], {}, ()))
    state, reasons = _legacy_field_state_name(
        field,
        present=present,
        rows=rows,
        relevant_decisions=relevant_decisions,
        affected=affected,
        terminal_unavailable=terminal_unavailable,
    )
    return field_state(
        field=field,
        state=state,
        evidence_ids=(row.evidence_id for row in rows),
        reason_codes=reasons,
    )


def _legacy_field_state_name(
    field: str,
    *,
    present: bool,
    rows: tuple[Evidence, ...],
    relevant_decisions: tuple[Decision, ...],
    affected: set[str],
    terminal_unavailable: bool,
) -> tuple[FieldStateName, tuple[str, ...]]:
    if present:
        return "captured_and_resolved", ()
    if (
        terminal_unavailable
        or field in affected
        or (field == "image_url" and "images" in affected)
    ):
        return "source_unavailable", ("product_data_source_unavailable",)
    if any(row.status == "conflicted" for row in relevant_decisions):
        reasons = {
            item.reason
            for row in relevant_decisions
            if row.status == "conflicted"
            for item in row.rejected
        }
        return "captured_conflicting", tuple(sorted(reasons))
    if any(
        row.status == "resolved" and row.accepted_evidence_ids
        for row in relevant_decisions
    ):
        return "captured_but_rejected", ("withheld_after_resolution",)
    if rows:
        return "captured_but_rejected", _legacy_rejection_reasons(
            rows, relevant_decisions
        )
    return "not_present_in_captured_sources", ()


def _legacy_rejection_reasons(
    rows: tuple[Evidence, ...], decisions: tuple[Decision, ...]
) -> tuple[str, ...]:
    row_ids = {row.evidence_id for row in rows}
    rejection_reasons = {
        item.reason
        for decision in decisions
        for item in decision.rejected
        if item.evidence_id in row_ids and item.reason
    }
    return tuple(
        sorted(rejection_reasons | {flag for row in rows for flag in row.flags})
    )


@dataclass(frozen=True, slots=True)
class _FieldStateContext:
    """Precomputed lookups shared by every per-field state derivation."""

    requested: frozenset[str]
    surface_fields: frozenset[str]
    contract_required: frozenset[str]
    disposition_by_id: dict[str, EvidenceDisposition]
    join_failed_evidence_ids: frozenset[str]
    unavailable_families: frozenset[str]
    terminal_unavailable: bool
    fact_by_field: dict[str, str]
    fields: tuple[str, ...]


def _bucket_projection_entries(
    projection: PublicationProjection,
) -> tuple[dict[str, list], dict[str, list]]:
    entries_by_field: dict[str, list] = {}
    variant_entries_by_field: dict[str, list] = {}
    for entry in projection.entries:
        if entry.path.startswith("asset[") and entry.path.endswith(".url"):
            entries_by_field.setdefault("image_url", []).append(entry)
        elif entry.path.startswith("variant["):
            # Variant facts live under ``variants.*`` and must never mark the parent
            # (``record.*``) as published. Flattening both to the same field name
            # is the observability defect behind results 68/90, where a published
            # variant price marked page-level ``price`` as ``captured_published``
            # even though ``record.price`` was absent.
            variant_entries_by_field.setdefault(
                entry.path.rsplit(".", 1)[-1], []
            ).append(entry)
        else:
            entries_by_field.setdefault(entry.path.rsplit(".", 1)[-1], []).append(entry)
    return entries_by_field, variant_entries_by_field


def _field_state_fact_map(surface: str) -> dict[str, str]:
    fact_by_field = {
        **field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES,
        "title": "job.title" if surface.startswith("job_") else "product.title",
        "url": "job.url" if surface.startswith("job_") else "product.url",
        "company": "job.company",
        "location": "job.location",
        "apply_url": "job.apply_url",
        "job_id": "job.id",
        "job_type": "job.type",
        "posted_date": "job.posted_date",
        "image_url": "asset.image_url",
    }
    for fact_type in field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES.values():
        field = fact_type.rsplit(".", 1)[-1]
        fact_by_field.setdefault(field, fact_type)
    return fact_by_field


def _terminal_source_unavailable(request: ExtractionRequest) -> bool:
    source_capabilities = dict(request.capture.acquisition_diagnostics or {}).get(
        "source_capabilities"
    )
    detail_outcome = (
        str(source_capabilities.get("detail_outcome") or "").strip()
        if isinstance(source_capabilities, dict)
        else ""
    ) or normalized_detail_outcome(
        http_status=request.capture.http_status,
        blocked=bool(request.capture.blocked),
        acquisition_outcome=request.capture.acquisition_outcome,
    )
    return (
        request.surface.value == "ecommerce_detail"
        and detail_outcome in DETAIL_TERMINAL_SOURCE_UNAVAILABLE_OUTCOMES
    )


def _unavailable_field_families(request: ExtractionRequest) -> frozenset[str]:
    source_capabilities = dict(request.capture.acquisition_diagnostics or {}).get(
        "source_capabilities"
    )
    return frozenset(
        source_capabilities.get("affected_field_families", ())
        if isinstance(source_capabilities, dict)
        else ()
    )


def _build_field_state_context(
    evidence: tuple[Evidence, ...],
    dispositions: tuple[EvidenceDisposition, ...],
    request: ExtractionRequest,
    findings: tuple[Finding, ...],
    entries_by_field: dict[str, list],
) -> _FieldStateContext:
    requested = frozenset(
        "image_url" if field == "image" else field for field in request.requested_fields
    )
    surface_fields = frozenset(
        "url" if field == "canonical_url" else field
        for field in canonical_fields_for_surface(request.surface.value)
    )
    contract_required = frozenset(
        field_mappings.SURFACE_FIELD_REPAIR_TARGETS.get(request.surface.value, ())
    )
    disposition_by_id = {row.evidence_id: row for row in dispositions}
    join_failed_evidence_ids = frozenset(
        evidence_id
        for finding in findings
        if finding.rule_id == CHILD_JOIN_FAILED_RULE_ID
        for evidence_id in finding.evidence_ids
    )
    fact_by_field = _field_state_fact_map(request.surface.value)
    field_by_fact = {
        fact_type: field for field, fact_type in fact_by_field.items() if fact_type
    }
    evidence_fields = {
        field_by_fact[row.fact_type]
        for row in evidence
        if row.fact_type in field_by_fact
    }
    fields = tuple(
        sorted(
            surface_fields
            | contract_required
            | requested
            | set(entries_by_field)
            | evidence_fields
        )
    )
    return _FieldStateContext(
        requested=requested,
        surface_fields=surface_fields,
        contract_required=contract_required,
        disposition_by_id=disposition_by_id,
        join_failed_evidence_ids=join_failed_evidence_ids,
        unavailable_families=_unavailable_field_families(request),
        terminal_unavailable=_terminal_source_unavailable(request),
        fact_by_field=fact_by_field,
        fields=fields,
    )


def _unpublished_field_state(
    field: str,
    *,
    ctx: _FieldStateContext,
    evidence: tuple[Evidence, ...],
) -> tuple[FieldStateName, tuple[str, ...]]:
    """State for a field with no publication entry, from raw evidence."""
    fact_type = ctx.fact_by_field.get(field, field)
    candidates = tuple(row for row in evidence if row.fact_type == fact_type)
    evidence_ids = tuple(row.evidence_id for row in candidates)
    candidate_dispositions = tuple(
        ctx.disposition_by_id[row.evidence_id]
        for row in candidates
        if row.evidence_id in ctx.disposition_by_id
    )
    return (
        _unpublished_state_name(
            field,
            ctx=ctx,
            candidates=candidates,
            candidate_dispositions=candidate_dispositions,
        ),
        evidence_ids,
    )


def _unpublished_state_name(
    field: str,
    *,
    ctx: _FieldStateContext,
    candidates: tuple[Evidence, ...],
    candidate_dispositions: tuple[EvidenceDisposition, ...],
) -> FieldStateName:
    if field in ctx.unavailable_families or (
        field == "image_url" and "images" in ctx.unavailable_families
    ):
        return "source_unavailable"
    if any(row.evidence_id in ctx.join_failed_evidence_ids for row in candidates):
        return "join_failed"
    if any(row.status == "unowned" for row in candidate_dispositions):
        return "captured_unowned"
    if any(row.status == "conflicted" for row in candidate_dispositions):
        return "captured_conflicting"
    if candidates:
        return "captured_but_rejected"
    if field in ctx.requested or field in ctx.contract_required:
        return "not_present_in_captured_sources"
    return "not_requested"


def _published_disposition_state(entries: list) -> FieldStateName | None:
    """Publication-entry disposition ladder: publish > suppress > review."""
    if any(entry.disposition == "publish" for entry in entries):
        return "captured_published"
    if any(entry.disposition == "suppress" for entry in entries):
        return "captured_suppressed"
    if any(entry.disposition == "review" for entry in entries):
        return "captured_conflicting"
    return None


def _record_field_state(
    field: str,
    *,
    ctx: _FieldStateContext,
    entries: list,
    variant_entity_ids: tuple[str, ...],
    evidence: tuple[Evidence, ...],
) -> FieldEvidenceState:
    evidence_ids = tuple(
        dict.fromkeys(
            evidence_id for entry in entries for evidence_id in entry.evidence_ids
        )
    )
    state, evidence_ids = _record_state_and_evidence_ids(
        field,
        ctx=ctx,
        entries=entries,
        variant_entity_ids=variant_entity_ids,
        evidence=evidence,
        evidence_ids=evidence_ids,
    )
    disposition_reason_codes = tuple(
        row.reason_code
        for evidence_id in evidence_ids
        if (row := ctx.disposition_by_id.get(evidence_id)) is not None
        and row.reason_code
    )
    state_reason_codes = (
        ("product_data_source_unavailable",) if state == "source_unavailable" else ()
    )
    return field_state(
        field=field,
        state=state,
        evidence_ids=evidence_ids,
        reason_codes=(
            *(entry.reason_code for entry in entries if entry.reason_code),
            *(code for code in disposition_reason_codes if code),
            *state_reason_codes,
        ),
    )


def _record_state_and_evidence_ids(
    field: str,
    *,
    ctx: _FieldStateContext,
    entries: list,
    variant_entity_ids: tuple[str, ...],
    evidence: tuple[Evidence, ...],
    evidence_ids: tuple[str, ...],
) -> tuple[FieldStateName, tuple[str, ...]]:
    if ctx.terminal_unavailable and field in (
        ctx.requested | ctx.contract_required | ctx.surface_fields
    ):
        return "source_unavailable", evidence_ids
    if field == "variants" and variant_entity_ids:
        return "captured_published", evidence_ids
    disposition_state = _published_disposition_state(entries)
    if disposition_state is not None:
        return disposition_state, evidence_ids
    return _unpublished_field_state(field, ctx=ctx, evidence=evidence)


def _variant_field_states(
    variant_entries_by_field: dict[str, list],
) -> list[FieldEvidenceState]:
    states: list[FieldEvidenceState] = []
    for field in sorted(variant_entries_by_field):
        variant_entries = variant_entries_by_field[field]
        variant_state: FieldStateName
        if any(entry.disposition == "publish" for entry in variant_entries):
            variant_state = "captured_published"
        elif any(entry.disposition == "suppress" for entry in variant_entries):
            variant_state = "captured_suppressed"
        elif any(entry.disposition == "review" for entry in variant_entries):
            variant_state = "captured_conflicting"
        else:
            continue
        states.append(
            field_state(
                field=f"variants.{field}",
                state=variant_state,
                evidence_ids=(
                    evidence_id
                    for entry in variant_entries
                    for evidence_id in entry.evidence_ids
                ),
                reason_codes=tuple(
                    entry.reason_code for entry in variant_entries if entry.reason_code
                ),
            )
        )
    return states


def projection_field_states(
    projection: PublicationProjection,
    evidence: tuple[Evidence, ...],
    dispositions: tuple[EvidenceDisposition, ...],
    request: ExtractionRequest,
    findings: tuple[Finding, ...] = (),
) -> tuple[FieldEvidenceState, ...]:
    """Derive field state from evidence and publication policy, never records."""

    entries_by_field, variant_entries_by_field = _bucket_projection_entries(projection)
    ctx = _build_field_state_context(
        evidence,
        dispositions,
        request,
        findings,
        entries_by_field,
    )
    variant_entity_ids = tuple(getattr(projection, "variant_entity_ids", ()) or ())
    states = [
        _record_field_state(
            field,
            ctx=ctx,
            entries=entries_by_field.get(field, []),
            variant_entity_ids=variant_entity_ids,
            evidence=evidence,
        )
        for field in ctx.fields
    ]
    states.extend(_variant_field_states(variant_entries_by_field))
    return tuple(states)


def data_integrity_status(
    verdict: str,
    field_states: tuple[FieldEvidenceState, ...],
    findings: tuple[Finding, ...] = (),
) -> typing.Literal["clean", "partial", "defect", "blocked", "unknown", "divergent"]:
    if any(row.rule_id == "PUBLIC_RESOLUTION_DIVERGENCE" for row in findings):
        return "divergent"
    if verdict == "blocked":
        return "blocked"
    if any(row.state == "captured_conflicting" for row in field_states):
        return "defect"
    if verdict in {"success"}:
        return "clean"
    if verdict in {"partial", "review"}:
        return "partial"
    if verdict in {"invalid", "error"}:
        return "defect"
    return "unknown"


def retry_request(
    verdict: str,
    records: tuple[PublicRecord, ...],
    request: ExtractionRequest,
    evidence: tuple[Evidence, ...] = (),
) -> RetryRequest | None:
    job_retry = _job_retry_request(verdict, records, request, evidence)
    if job_retry is not None:
        return job_retry
    shell_detected = any(is_shell_record(record) for record in records) or any(
        DETAIL_SHELL_TITLE_FLAG in row.flags for row in evidence
    )
    if verdict == "error" and shell_detected:
        return RetryRequest(
            required=not request.capture.browser_attempted,
            reason="http_shell",
            required_artifacts=("rendered_html",),
        )
    if _empty_listing_needs_browser(verdict, records, request):
        return RetryRequest(
            required=True,
            reason="empty_extraction",
            required_artifacts=("rendered_html",),
        )
    if _detail_variants_need_browser(records, request, evidence):
        return RetryRequest(
            required=True,
            reason="explicit_variants_missing",
            required_artifacts=("rendered_html", "network_payloads"),
        )
    if request.surface.value == "ecommerce_detail":
        return _commerce_dynamic_content_retry(verdict, records, request)
    return None


def _empty_listing_needs_browser(
    verdict: str,
    records: tuple[PublicRecord, ...],
    request: ExtractionRequest,
) -> bool:
    return bool(
        request.surface.value == "ecommerce_listing"
        and verdict == "empty"
        and not records
        and not request.capture.browser_attempted
    )


def _detail_variants_need_browser(
    records: tuple[PublicRecord, ...],
    request: ExtractionRequest,
    evidence: tuple[Evidence, ...],
) -> bool:
    if request.surface.value != "ecommerce_detail" or request.capture.browser_attempted:
        return False
    if _explicit_variant_dom_cues(evidence) and _variant_controls_incomplete(
        records, evidence
    ):
        return True
    return "variants" in request.requested_fields and _variants_missing_or_incomplete(
        records
    )


def _commerce_dynamic_content_retry(
    verdict: str,
    records: tuple[PublicRecord, ...],
    request: ExtractionRequest,
) -> RetryRequest | None:
    requested_core_fields = {
        "image_url" if field == "image" else field
        for field in request.requested_fields
        if field in field_mappings.ECOMMERCE_DETAIL_REQUESTED_CORE_FIELDS
    }
    if (
        verdict in {"error", "partial", "review"}
        and not request.capture.browser_attempted
        and (not request.requested_fields or requested_core_fields or not records)
    ):
        record = records[0] if records else PublicRecord()
        target_core_fields = requested_core_fields or set(
            field_mappings.SURFACE_BROWSER_RETRY_TARGETS.get("ecommerce_detail", ())
        )
        missing_core_fields = tuple(
            field
            for field in target_core_fields
            if record.get(field) in (None, "", [], {}, ())
        )
        if missing_core_fields or not records:
            return RetryRequest(
                required=True,
                reason="dynamic_content_missing",
                required_artifacts=("rendered_html", "network_payloads"),
            )
    return None


_JOB_SURFACES = frozenset({Surface.JOB_DETAIL.value, Surface.JOB_LISTING.value})


def _job_retry_request(
    verdict: str,
    records: tuple[PublicRecord, ...],
    request: ExtractionRequest,
    evidence: tuple[Evidence, ...],
) -> RetryRequest | None:
    """Surface-agnostic escalation for job surfaces.

    An empty or shell job page requests the rendered document; when the
    structured JSON-LD signal is also missing, network payloads are added so the
    ladder climbs the network floor. ``max_attempts`` is the configured cap; a
    request is still emitted after a browser attempt (retry/stage.py stops it).
    """
    if request.surface.value not in _JOB_SURFACES:
        return None
    shell = any(is_shell_record(record) for record in records) or any(
        DETAIL_SHELL_TITLE_FLAG in row.flags for row in evidence
    )
    if not ((verdict in {"empty", "error"} and not records) or shell):
        return None
    required_artifacts: tuple[str, ...] = ("rendered_html",)
    if not any(row.collector_id == "job_jsonld" for row in evidence):
        required_artifacts = ("rendered_html", "network_payloads")
    return RetryRequest(
        required=True,
        reason="http_shell" if shell else "empty_extraction",
        required_artifacts=required_artifacts,
        max_attempts=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP,
    )


def _explicit_variant_dom_cues(evidence: tuple[Evidence, ...]) -> bool:
    return any(
        row.collector_id == "dom" and row.fact_type.startswith("option.")
        for row in evidence
    )


def _variants_missing_or_incomplete(records: tuple[PublicRecord, ...]) -> bool:
    if not records:
        return True
    variants = tuple(records[0].get("variants") or ())
    if not variants:
        return True
    return any(
        not isinstance(variant, dict)
        or all(
            variant.get(field) in (None, "", [], {}, ())
            for field in ("variant_id", "sku", "size", "color", "style")
        )
        for variant in variants
    )


def _variant_controls_incomplete(
    records: tuple[PublicRecord, ...], evidence: tuple[Evidence, ...]
) -> bool:
    variants = tuple(records[0].get("variants") or ()) if records else ()
    axes = {
        row.fact_type.removeprefix("option.")
        for row in evidence
        if row.collector_id == "dom" and row.fact_type.startswith("option.")
    }
    if not variants:
        return True
    return any(
        any(variant.get(axis) in (None, "", [], {}, ()) for variant in variants)
        for axis in axes
    )


def is_shell_record(record: PublicRecord | None) -> bool:
    title = " ".join(slug_tokens(record.get("title"))) if record else ""
    return bool(title and title in DETAIL_SHELL_TITLE_KEYS)


def entity_graph(
    graph_state: Any,
    evidence: tuple[Evidence, ...],
    spec: SurfaceSpec,
) -> EntityGraph:
    if isinstance(graph_state, EntitySet):
        return EntityGraph(
            root_entity_ids=tuple(
                product.entity_id for product in graph_state.products
            ),
            entity_counts={
                "product": len(graph_state.products),
                "variant": len(graph_state.variants),
                "offer": len(graph_state.offers),
                "asset": len(graph_state.assets),
                "option": sum(
                    len(axis.values)
                    for catalog in graph_state.option_catalogs
                    for axis in catalog.axes
                ),
            },
        )
    roots = tuple(graph_state or ())
    return EntityGraph(
        root_entity_ids=roots,
        entity_counts={
            spec.root_entity: len(roots),
            "evidence_subject": len(
                {row.subject_id for row in evidence if row.subject_id}
            ),
        },
    )


def metrics(
    evidence: tuple[Evidence, ...],
    graph: EntityGraph,
    target: TargetSelection,
    findings: tuple[Finding, ...],
    decision_rows: tuple[Decision, ...],
    records: tuple[PublicRecord, ...],
    verdict: str,
    *,
    collector_count: int = 0,
    resolve_duration_ms: float = 0.0,
    publish_duration_ms: float = 0.0,
) -> ExtractionMetrics:
    lineage_fields = sum(len(dict(record.get("_lineage") or {})) for record in records)
    public_fields = sum(
        sum(not str(key).startswith("_") for key in record.model_dump(mode="python"))
        for record in records
    )
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
        evidence_count=len(evidence),
        entity_counts=graph.entity_counts,
        finding_counts_by_severity=dict(
            Counter(finding.severity for finding in findings)
        ),
        decision_counts_by_status=dict(
            Counter(decision.status for decision in decision_rows)
        ),
        selected_root_ids=target.root_entity_ids,
        variant_count=sum(len(record.get("variants") or []) for record in records),
        public_lineage_coverage=(
            lineage_fields / public_fields if public_fields else 0.0
        ),
        completeness_score=completeness_score,
        verdict=verdict,
        resolve_duration_ms=resolve_duration_ms,
        publish_duration_ms=publish_duration_ms,
    )
