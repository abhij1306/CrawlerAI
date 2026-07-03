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
    SourceLocator,
)

SCHEMA_VERSION = "diagnose.v2"
_PREVIEW_LIMIT = 120
_FIELDS_LIMIT = 100
_REJECTED_PER_FIELD_LIMIT = 10
_VARIANT_DROPS_LIMIT = 200
_COLLECTORS_LIMIT = 50
_STAGES_LIMIT = 50
_CONTRACTS_LIMIT = 100
_FINDINGS_LIMIT = 100
_EVIDENCE_DISPOSITIONS_LIMIT = 500


def build_diagnosis(
    *,
    acquisition_result: Any,
    extraction_result: ExtractionResult,
    rejected_public_fields: Mapping[str, object] | None = None,
    variant_drops: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    rejected_public = {
        str(key): value for key, value in dict(rejected_public_fields or {}).items()
    }
    evidence_by_id = {row.evidence_id: row for row in extraction_result.evidence}
    decision_by_field = _decisions_by_public_field(extraction_result.decisions)

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
        "transport_outcome": extraction_result.transport_outcome,
        "data_integrity": extraction_result.data_integrity,
        "manifest": _manifest_context(extraction_result).model_dump(mode="json"),
        "diagnostics": _diagnostic_summary(extraction_result).model_dump(mode="json"),
        "failure_classifications": [
            row.model_dump(mode="json")
            for row in _failure_classifications(extraction_result)
        ],
        "acquisition": _acquisition_section(acquisition_result),
        "metrics": extraction_result.metrics.model_dump(mode="json"),
        "fields": [
            _field_section(
                state,
                decision=decision_by_field.get(state.field),
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


def _failure_classifications(
    extraction_result: object,
) -> tuple[FailureClassification, ...]:
    value = getattr(extraction_result, "failure_classifications", ())
    return tuple(row for row in value or () if isinstance(row, FailureClassification))


def _acquisition_section(acquisition_result: Any) -> dict[str, object]:
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
        "capture_outcome": _acquisition_capture_outcome(acquisition_result, blocked),
        "platform_family": getattr(acquisition_result, "platform_family", None),
        "browser_outcome": browser.get("browser_outcome"),
        "failure_reason": browser.get("failure_reason") or result.get("failure_reason"),
    }


def _acquisition_capture_outcome(acquisition_result: Any, blocked: bool) -> str:
    if blocked:
        return "blocked"
    status_code = getattr(acquisition_result, "status_code", None)
    if status_code in DETAIL_NOT_FOUND_HTTP_STATUS_CODES:
        return DETAIL_CAPTURE_NOT_FOUND_OUTCOME
    if isinstance(status_code, int) and status_code >= 500:
        return "error"
    return "ok"


def _field_section(
    state: FieldEvidenceState,
    *,
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
    winner = _winner(decision, evidence_by_id)
    if winner is not None:
        section["winner"] = winner
    rejected = _rejected(decision, evidence_by_id)
    if rejected:
        section["rejected"] = rejected
    if publication_policy not in (None, "", [], {}):
        section["publication_policy"] = publication_policy
    return section


def _winner(
    decision: Decision | None,
    evidence_by_id: Mapping[str, Evidence],
) -> dict[str, object] | None:
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


def _preview(value: object, *, limit: int = _PREVIEW_LIMIT) -> object:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
