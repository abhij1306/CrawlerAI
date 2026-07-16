"""Build a self-contained, bounded ``diagnose.json`` for one URL result.

Operator priority #1: a wrong or missing field (price, currency, availability,
a dropped variant) is root-caused from this single artifact alone — never from
raw HTML or source. The payload is therefore self-referential: every field
carries its winning evidence, the rejected candidates with reasons, the
publication-policy disposition, and the collector/stage outcomes that produced
it.

It reuses the existing extraction vocabulary only — ``FieldEvidenceState.state``,
``Decision`` / ``RejectedEvidence``, ``SourceLocator``, publication reason
codes, evidence disposition statuses, and the collector/stage outcome enum — so
there is one set of terms to learn. Values are length-bounded so the artifact
stays small.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from app.acquisition.acquirer import PageEvidence
from app.core.config.diagnose import (
    DIAGNOSE_COLLECTORS_LIMIT,
    DIAGNOSE_CONTRACTS_LIMIT,
    DIAGNOSE_ESCALATION_ATTEMPT_LIMIT,
    DIAGNOSE_EVIDENCE_DISPOSITIONS_LIMIT,
    DIAGNOSE_FIELDS_LIMIT,
    DIAGNOSE_FINDINGS_LIMIT,
    DIAGNOSE_NETWORK_PROVENANCE_LIMIT,
    DIAGNOSE_PREVIEW_LIMIT,
    DIAGNOSE_REJECTED_PER_FIELD_LIMIT,
    DIAGNOSE_SCHEMA_VERSION,
    DIAGNOSE_STAGES_LIMIT,
    DIAGNOSE_VARIANT_DROPS_LIMIT,
)
from app.core.listing_cards import ListingCardDiagnostics
from app.core.config import field_mappings
from app.core.config.extraction_rules import (
    DETAIL_CAPTURE_NOT_FOUND_OUTCOME,
    DETAIL_NOT_FOUND_HTTP_STATUS_CODES,
)
from app.extraction.contracts import (
    Decision,
    DiagnosticSummary,
    Evidence,
    ExecutionManifestContext,
    ExtractionResult,
    FailureClassification,
    FieldEvidenceState,
    PublicationEntry,
    SourceLocator,
)

SCHEMA_VERSION = DIAGNOSE_SCHEMA_VERSION
_PREVIEW_LIMIT = DIAGNOSE_PREVIEW_LIMIT
_FIELDS_LIMIT = DIAGNOSE_FIELDS_LIMIT
_REJECTED_PER_FIELD_LIMIT = DIAGNOSE_REJECTED_PER_FIELD_LIMIT
_VARIANT_DROPS_LIMIT = DIAGNOSE_VARIANT_DROPS_LIMIT
_COLLECTORS_LIMIT = DIAGNOSE_COLLECTORS_LIMIT
_STAGES_LIMIT = DIAGNOSE_STAGES_LIMIT
_CONTRACTS_LIMIT = DIAGNOSE_CONTRACTS_LIMIT
_FINDINGS_LIMIT = DIAGNOSE_FINDINGS_LIMIT
_EVIDENCE_DISPOSITIONS_LIMIT = DIAGNOSE_EVIDENCE_DISPOSITIONS_LIMIT


def build_diagnosis(
    *,
    acquisition_result: Any,
    extraction_result: ExtractionResult,
    rejected_public_fields: Mapping[str, object] | None = None,
    variant_drops: Sequence[Mapping[str, object]] | None = None,
    record_count: int | None = None,
    listing_verdict: str | None = None,
) -> dict[str, object]:
    rejected_public = {
        str(key): value for key, value in dict(rejected_public_fields or {}).items()
    }
    evidence_by_id = {row.evidence_id: row for row in extraction_result.evidence}
    projection_by_field = _projection_entries_by_public_field(extraction_result)

    fields_total = len(extraction_result.field_states)
    fields_section, fields_truncated = _bounded(
        extraction_result.field_states, _FIELDS_LIMIT
    )
    drops_total = len(variant_drops or ())
    drops_section, drops_truncated = _bounded(
        list(variant_drops or ()), _VARIANT_DROPS_LIMIT
    )
    collectors_total = len(extraction_result.collector_outcomes)
    collectors_section, collectors_truncated = _bounded(
        extraction_result.collector_outcomes, _COLLECTORS_LIMIT
    )
    stages_total = len(extraction_result.stage_outcomes)
    stages_section, stages_truncated = _bounded(
        extraction_result.stage_outcomes, _STAGES_LIMIT
    )
    contracts_total = len(extraction_result.contract_outcomes)
    contract_section, contracts_truncated = _bounded(
        extraction_result.contract_outcomes, _CONTRACTS_LIMIT
    )
    findings_total = len(extraction_result.findings)
    findings_section, findings_truncated = _bounded(
        extraction_result.findings, _FINDINGS_LIMIT
    )
    evidence_dispositions = tuple(
        getattr(extraction_result, "evidence_dispositions", ()) or ()
    )
    dispositions_total = len(evidence_dispositions)
    dispositions_section, dispositions_truncated = _bounded(
        evidence_dispositions,
        _EVIDENCE_DISPOSITIONS_LIMIT,
    )

    truncated: dict[str, dict[str, int]] = {}
    if fields_truncated:
        truncated["fields"] = {"included": len(fields_section), "total": fields_total}
    if drops_truncated:
        truncated["variant_drops"] = {
            "included": len(drops_section),
            "total": drops_total,
        }
    if collectors_truncated:
        truncated["collectors"] = {
            "included": len(collectors_section),
            "total": collectors_total,
        }
    if stages_truncated:
        truncated["stages"] = {"included": len(stages_section), "total": stages_total}
    if contracts_truncated:
        truncated["contract_outcomes"] = {
            "included": len(contract_section),
            "total": contracts_total,
        }
    if findings_truncated:
        truncated["findings"] = {
            "included": len(findings_section),
            "total": findings_total,
        }
    if dispositions_truncated:
        truncated["evidence_dispositions"] = {
            "included": len(dispositions_section),
            "total": dispositions_total,
        }

    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "verdict": extraction_result.verdict,
        "transport_outcome": getattr(extraction_result, "transport_outcome", "unknown"),
        "data_integrity": extraction_result.data_integrity,
        "manifest": _manifest_context(extraction_result).model_dump(mode="json"),
        "diagnostics": _diagnostic_summary(extraction_result).model_dump(mode="json"),
        "recipe": _recipe_section(extraction_result),
        "failure_classifications": [
            row.model_dump(mode="json")
            for row in _failure_classifications(extraction_result)
        ],
        "acquisition": _acquisition_section(
            acquisition_result,
            capture_outcome=_known_capture_outcome(
                getattr(extraction_result, "transport_outcome", "")
            ),
        ),
        "discovery": _discovery_section(
            acquisition_result,
            extraction_result=extraction_result,
            record_count=record_count,
            listing_verdict=listing_verdict,
        ),
        "metrics": extraction_result.metrics.model_dump(mode="json"),
        "fields": [
            _field_section(
                state,
                publication_entry=projection_by_field.get(state.field),
                decision=_decisions_by_public_field(extraction_result.decisions).get(
                    state.field
                ),
                evidence_by_id=evidence_by_id,
                publication_policy=rejected_public.get(state.field),
            )
            for state in fields_section
        ],
        "variants": {
            "dropped": [dict(drop) for drop in drops_section],
        },
        "collectors": [
            outcome.model_dump(mode="json") for outcome in collectors_section
        ],
        "stages": [outcome.model_dump(mode="json") for outcome in stages_section],
        "findings": [finding.model_dump(mode="json") for finding in findings_section],
        "evidence_dispositions": {
            "total": dispositions_total,
            "by_status": dict(Counter(row.status for row in evidence_dispositions)),
            "examples": [row.model_dump(mode="json") for row in dispositions_section],
        },
        # Per-field record of which frozen contract (if any) selected the winning
        # source, so a learned extraction is explainable from diagnose.json alone.
        # ``None`` when no contracts were applied keeps the "not applicable" signal
        # distinct from "applied, but every field fell back".
        "contract_outcomes": (
            [outcome.model_dump(mode="json") for outcome in contract_section]
            if extraction_result.contract_outcomes
            else None
        ),
    }
    if truncated:
        payload["truncated"] = truncated
    return payload


def _bounded(items: Sequence[Any], limit: int) -> tuple[list[Any], bool]:
    rows = list(items)
    if len(rows) <= limit:
        return rows, False
    return rows[:limit], True


def _known_capture_outcome(value: object) -> str | None:
    text = str(value or "").strip()
    return text if text and text != "unknown" else None


def _manifest_context(extraction_result: object) -> ExecutionManifestContext:
    value = getattr(extraction_result, "manifest_context", None)
    return (
        value
        if isinstance(value, ExecutionManifestContext)
        else ExecutionManifestContext()
    )


def _diagnostic_summary(extraction_result: object) -> DiagnosticSummary:
    value = getattr(extraction_result, "diagnostics", None)
    return value if isinstance(value, DiagnosticSummary) else DiagnosticSummary()


def _recipe_section(extraction_result: ExtractionResult) -> dict[str, object]:
    """Expose the one recipe path that caused this result without raw values."""

    execution = getattr(extraction_result, "recipe_execution", None)
    stages, _ = _bounded(
        getattr(extraction_result, "stage_outcomes", ()), _STAGES_LIMIT
    )
    return {
        "selected": any(
            row.stage == "recipe_select" and row.outcome == "ran" for row in stages
        ),
        "execution": (
            {
                "recipe_id": execution.recipe_id,
                "failure_code": execution.failure_code,
                "detail": _preview(execution.detail) if execution.detail else None,
                "record_count": len(execution.records),
                "binding_outcomes": [
                    {
                        "binding_id": outcome.binding_id,
                        "status": outcome.status,
                        "source_path": outcome.source_path,
                        "detail": _preview(outcome.detail) if outcome.detail else None,
                    }
                    for outcome in execution.outcomes
                ],
            }
            if execution is not None
            else None
        ),
        "discovery_stages": [
            {
                "stage": row.stage,
                "outcome": row.outcome,
                "detail": _preview(row.detail) if row.detail else None,
            }
            for row in stages
            if row.stage
            in {
                "recipe_select",
                "recipe_discovery",
                "model_recipe_compile",
                "recipe_execute",
                "candidate_recipe_execute",
                "model_recipe_proposal",
            }
        ],
    }


def _failure_classifications(
    extraction_result: object,
) -> tuple[FailureClassification, ...]:
    value = getattr(extraction_result, "failure_classifications", ())
    return tuple(row for row in value or () if isinstance(row, FailureClassification))


def _acquisition_section(
    acquisition_result: Any, *, capture_outcome: str | None = None
) -> dict[str, object]:
    browser = _mapping(getattr(acquisition_result, "browser_diagnostics", {}))
    diagnostics = _mapping(getattr(acquisition_result, "acquisition_diagnostics", {}))
    result = _mapping(diagnostics.get("result"))
    page_evidence = PageEvidence.from_acquisition_result(acquisition_result)
    blocked = page_evidence.indicates_block
    return {
        "final_url": str(getattr(acquisition_result, "final_url", "") or ""),
        "method": str(getattr(acquisition_result, "method", "") or ""),
        "status_code": getattr(acquisition_result, "status_code", None),
        "blocked": blocked,
        "capture_outcome": capture_outcome
        or _acquisition_capture_outcome(acquisition_result, blocked),
        "platform_family": getattr(acquisition_result, "platform_family", None),
        "browser_outcome": browser.get("browser_outcome"),
        "failure_reason": browser.get("failure_reason") or result.get("failure_reason"),
    }


def _acquisition_capture_outcome(acquisition_result: Any, blocked: bool) -> str:
    if blocked:
        return "blocked"
    status_code = getattr(acquisition_result, "status_code", None)
    diagnostics = _mapping(getattr(acquisition_result, "acquisition_diagnostics", {}))
    source_capabilities = _mapping(diagnostics.get("source_capabilities"))
    if detail_outcome := source_capabilities.get("detail_outcome"):
        return str(detail_outcome)
    if status_code in DETAIL_NOT_FOUND_HTTP_STATUS_CODES:
        return DETAIL_CAPTURE_NOT_FOUND_OUTCOME
    if isinstance(status_code, int) and status_code >= 500:
        return "error"
    return "ok"


def _discovery_section(
    acquisition_result: Any,
    *,
    extraction_result: ExtractionResult,
    record_count: int | None,
    listing_verdict: str | None,
) -> dict[str, object]:
    browser = _mapping(getattr(acquisition_result, "browser_diagnostics", {}))
    discovery = _mapping(browser.get("listing_discovery"))
    card_diagnostics = ListingCardDiagnostics.from_mapping(
        discovery.get("listing_card_diagnostics")
    )
    acquisition_diagnostics = _mapping(
        getattr(acquisition_result, "acquisition_diagnostics", {})
    )
    readiness = _readiness_summary(browser, discovery)
    records = getattr(extraction_result, "records", ()) or ()
    authoritative_record_count = (
        max(0, int(record_count)) if record_count is not None else len(records)
    )
    return {
        "listing_verdict": str(
            listing_verdict or getattr(extraction_result, "verdict", "") or ""
        ),
        "record_count": authoritative_record_count,
        **card_diagnostics.as_dict(),
        "readiness": readiness,
        "escalation": _bounded_escalation(acquisition_diagnostics),
        "network": _network_summary(acquisition_result, browser),
    }


def _readiness_summary(
    browser: Mapping[str, object], discovery: Mapping[str, object]
) -> dict[str, object]:
    listing_readiness = _mapping(browser.get("listing_readiness"))
    terminal_state = str(discovery.get("readiness_terminal_state") or "").strip()
    if listing_readiness.get("status") in {"timed_out", "timeout"} and not bool(
        discovery.get("is_ready")
    ):
        terminal_state = "timed_out"
    return {
        "terminal_state": terminal_state or "not_observed",
        "is_ready": bool(discovery.get("is_ready")),
        "ready_empty": bool(discovery.get("ready_empty")),
        "shell_detected": bool(discovery.get("shell_detected")),
        "probe_count": len(browser.get("readiness_probes") or ())
        if isinstance(browser.get("readiness_probes"), (list, tuple))
        else 0,
        "last_stage": discovery.get("stage"),
    }


def _bounded_escalation(diagnostics: Mapping[str, object]) -> dict[str, object]:
    escalation = _mapping(diagnostics.get("escalation"))
    raw_requests = escalation.get("capability_requests")
    requests = [
        {
            "rung": row.get("rung"),
            "attempt": row.get("attempt"),
            "max_attempts": row.get("max_attempts"),
            "reason": _preview(row.get("reason")),
            "required_artifacts": [
                _preview(value) for value in row.get("required_artifacts", ())
            ]
            if isinstance(row.get("required_artifacts"), (list, tuple))
            else [],
            "capture_network": _preview(row.get("capture_network")),
        }
        for row in (
            list(raw_requests)[:DIAGNOSE_ESCALATION_ATTEMPT_LIMIT]
            if isinstance(raw_requests, (list, tuple))
            else []
        )
        if isinstance(row, Mapping)
    ]
    return {
        "rung": escalation.get("rung"),
        "attempt": escalation.get("attempt"),
        "max_attempts": escalation.get("max_attempts"),
        "capability_requests": requests,
        "truncated": bool(
            isinstance(raw_requests, (list, tuple))
            and len(raw_requests) > DIAGNOSE_ESCALATION_ATTEMPT_LIMIT
        ),
    }


def _network_summary(
    acquisition_result: Any, browser: Mapping[str, object]
) -> dict[str, object]:
    payloads = list(getattr(acquisition_result, "network_payloads", ()) or ())
    provenance = []
    for index, payload in enumerate(payloads[:DIAGNOSE_NETWORK_PROVENANCE_LIMIT]):
        if not isinstance(payload, Mapping):
            continue
        provenance.append(
            {
                "payload_index": index,
                "endpoint_type": _preview(payload.get("endpoint_type")),
                "status": payload.get("status"),
                "content_type": _preview(payload.get("content_type")),
                "body_kind": type(payload.get("body")).__name__,
            }
        )
    capture_count = browser.get("network_payload_count")
    return {
        "capture_count": int(capture_count)
        if isinstance(capture_count, (int, float))
        else len(payloads),
        "payload_count": len(payloads),
        "provenance": provenance,
        "truncated": len(payloads) > DIAGNOSE_NETWORK_PROVENANCE_LIMIT,
    }


def _field_section(
    state: FieldEvidenceState,
    *,
    publication_entry: PublicationEntry | None,
    decision: Decision | None,
    evidence_by_id: Mapping[str, Evidence],
    publication_policy: object,
) -> dict[str, object]:
    section: dict[str, object] = {
        "field": state.field,
        "status": state.state,
    }
    if state.reason_codes:
        section["reason_codes"] = list(state.reason_codes)
    winner = _winner(publication_entry, decision, evidence_by_id)
    if winner is not None:
        section["winner"] = winner
    rejected = _rejected(decision, evidence_by_id)
    if rejected:
        section["rejected"] = rejected
    if publication_policy not in (None, "", [], {}):
        section["publication_policy"] = publication_policy
    return section


def _winner(
    publication_entry: PublicationEntry | None,
    decision: Decision | None,
    evidence_by_id: Mapping[str, Evidence],
) -> dict[str, object] | None:
    if publication_entry is not None and publication_entry.disposition == "publish":
        row: dict[str, object] = {
            "value": _preview(publication_entry.value),
            "entity_id": publication_entry.entity_id,
            "path": publication_entry.path,
            "rule_id": publication_entry.rule_id,
            "evidence_ids": list(publication_entry.evidence_ids),
        }
        if publication_entry.parent_entity_id:
            row["parent_entity_id"] = publication_entry.parent_entity_id
        if publication_entry.selected_fact_id:
            row["selected_fact_id"] = publication_entry.selected_fact_id
        if publication_entry.derived_fact_id:
            row["derived_fact_id"] = publication_entry.derived_fact_id
        if publication_entry.evidence_ids:
            evidence = evidence_by_id.get(publication_entry.evidence_ids[0])
            if evidence is not None:
                row["collector_id"] = evidence.collector_id
                row["locator"] = _locator(evidence.locator)
        return {key: value for key, value in row.items() if value not in (None, "", [])}
    if decision is None or not decision.accepted_evidence_ids:
        return None
    evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
    if evidence is None:
        return {"rule_id": decision.rule_id}
    return {
        "collector_id": evidence.collector_id,
        "locator": _locator(evidence.locator),
        "value": _preview(evidence.value),
        "rule_id": decision.rule_id,
    }


def _rejected(
    decision: Decision | None,
    evidence_by_id: Mapping[str, Evidence],
) -> list[dict[str, object]]:
    if decision is None:
        return []
    rows: list[dict[str, object]] = []
    rejected_iter = list(decision.rejected)[:_REJECTED_PER_FIELD_LIMIT]
    for rejected in rejected_iter:
        evidence = evidence_by_id.get(rejected.evidence_id)
        row: dict[str, object] = {"reason": rejected.reason}
        if evidence is not None:
            row["collector_id"] = evidence.collector_id
            row["locator"] = _locator(evidence.locator)
            row["value_preview"] = _preview(evidence.value)
        rows.append(row)
    if len(decision.rejected) > _REJECTED_PER_FIELD_LIMIT:
        rows.append(
            {
                "reason": "truncated",
                "omitted": len(decision.rejected) - _REJECTED_PER_FIELD_LIMIT,
            }
        )
    return rows


def _locator(locator: SourceLocator) -> dict[str, object]:
    data: dict[str, object] = {"kind": locator.kind, "value": _preview(locator.value)}
    if locator.preview:
        data["preview"] = _preview(locator.preview)
    return data


def _decisions_by_public_field(
    decisions: Sequence[Decision],
) -> dict[str, Decision]:
    # Field-state fields are public field names (price, currency, sku, ...);
    # decision fact_types are dotted (offer.price, product.sku). Map by the EXACT
    # fact_type behind each public field — never the trailing segment — so a
    # ``variant.sku`` decision can't masquerade as the product-level ``sku``
    # winner. Keep the first resolved decision per field for determinism.
    fact_to_field = {
        fact: field
        for field, fact in field_mappings.ECOMMERCE_PUBLIC_FIELD_FACT_TYPES.items()
    }
    by_field: dict[str, Decision] = {}
    for decision in decisions:
        field = fact_to_field.get(decision.fact_type)
        if field is None:
            continue
        existing = by_field.get(field)
        if existing is None or (
            existing.status != "resolved" and decision.status == "resolved"
        ):
            by_field[field] = decision
    return by_field


def _projection_entries_by_public_field(
    extraction_result: ExtractionResult,
) -> dict[str, PublicationEntry]:
    authorized_fields = {
        state.field
        for state in getattr(extraction_result, "field_states", ()) or ()
        if str(getattr(state, "state", "") or "") in {"captured_published", "resolved"}
    }
    record_fields = {
        key
        for record in getattr(extraction_result, "records", ()) or ()
        for key, value in _record_items(record)
        if value not in (None, "", [], {}) and not str(key).startswith("_")
    }
    projection = getattr(extraction_result, "publication", None)
    entries = tuple(getattr(projection, "entries", ()) or ())
    by_field: dict[str, PublicationEntry] = {}
    for entry in entries:
        if not isinstance(entry, PublicationEntry) or entry.disposition != "publish":
            continue
        field = _public_field_from_projection_path(entry.path)
        if (
            field
            and field in authorized_fields
            and field in record_fields
            and field not in by_field
        ):
            by_field[field] = entry
    return by_field


def _record_items(record: object) -> tuple[tuple[str, object], ...]:
    if isinstance(record, dict):
        return tuple(record.items())
    if hasattr(record, "model_dump"):
        return tuple(record.model_dump().items())
    return ()


def _public_field_from_projection_path(path: str) -> str | None:
    text = str(path or "")
    if text.startswith("record."):
        return text.rsplit(".", 1)[-1]
    if text.startswith("asset[") and text.endswith(".url"):
        return "image_url"
    return None


def _preview(value: object, *, limit: int = _PREVIEW_LIMIT) -> object:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
