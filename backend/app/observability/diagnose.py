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
    PublicationEntry,
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
        if str(getattr(state, "state", "") or "")
        in {"captured_published", "resolved"}
    }
    record_fields = {
        key
        for record in getattr(extraction_result, "records", ()) or ()
        if isinstance(record, dict)
        for key, value in record.items()
        if value not in (None, "", [], {})
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
