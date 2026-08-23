from __future__ import annotations

from typing import TYPE_CHECKING
import uuid

from app.core.config import extraction_memory as cfg
from app.core.extraction_memory.templates import (
    normalize_source_pattern,
    source_pattern,
)

if TYPE_CHECKING:
    from app.extraction.contracts import Evidence, ExtractionResult, FieldEvidenceState


def observed_field_sources(result: ExtractionResult) -> dict[str, list[str]]:
    if result.verdict not in cfg.EXTRACTION_CONTRACT_OBSERVABLE_VERDICTS:
        return {}
    if not result.records:
        return {}
    evidence_by_id = {row.evidence_id: row for row in result.evidence}
    winner_ids = {
        row.accepted_evidence_ids[0]
        for row in result.decisions
        if row.status == "resolved" and row.accepted_evidence_ids
    }
    observed_sources: dict[str, list[str]] = {}
    for state in result.field_states:
        source = _published_field_source(
            state,
            evidence_by_id=evidence_by_id,
            winner_ids=winner_ids,
        )
        if source is not None:
            observed_sources[source[0]] = [source[1]]
    return observed_sources


def _published_field_source(
    state: FieldEvidenceState,
    *,
    evidence_by_id: dict[str, Evidence],
    winner_ids: set[str],
) -> tuple[str, str] | None:
    if state.state not in {
        "captured_published",
        "captured_and_resolved",
    }:
        return None
    if state.field.startswith("variants."):
        return None
    evidence_ids = list(state.evidence_ids)
    winner_id = next(
        (evidence_id for evidence_id in evidence_ids if evidence_id in winner_ids),
        next(iter(evidence_ids), None),
    )
    evidence = evidence_by_id.get(winner_id) if winner_id else None
    if evidence is None:
        return None
    source = normalize_source_pattern(
        source_pattern(evidence.collector_id, evidence.locator.value)
    )
    return (evidence.fact_type, source) if source else None


def merge_observed_contracts(
    existing_payload: dict,
    *,
    template_id: uuid.UUID,
    surface: str,
    observed_sources: dict[str, list[str]],
) -> dict:
    contracts = [
        dict(row)
        for row in existing_payload.get("contracts", [])
        if isinstance(row, dict)
    ]
    contracts_by_field = {
        str(row.get("canonical_field") or ""): row for row in contracts
    }
    for canonical_field, sources in observed_sources.items():
        contract = contracts_by_field.get(canonical_field)
        if contract is None:
            contract = _new_observed_contract(
                template_id=template_id,
                surface=surface,
                canonical_field=canonical_field,
                selected_source=sources[0],
            )
            contracts.append(contract)
            contracts_by_field[canonical_field] = contract
        merge_observed_sources(contract, sources)
    return {"contracts": contracts}


def _new_observed_contract(
    *,
    template_id: uuid.UUID,
    surface: str,
    canonical_field: str,
    selected_source: str,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "template_id": str(template_id),
        "surface": surface,
        "canonical_field": canonical_field,
        "candidates": [],
        "latest_values": [],
        "success_count": 0,
        "rejection_count": 0,
        "resolver_rule": cfg.EXTRACTION_CONTRACT_RESOLVER_OBSERVED,
        "selected_source": selected_source,
        "selection_origin": cfg.EXTRACTION_CONTRACT_SELECTION_ORIGIN_GENERIC,
        "selection_history": [
            {
                "selected_source": selected_source,
                "source": cfg.EXTRACTION_CONTRACT_OBSERVATION_SOURCE,
            }
        ],
        "status": cfg.EXTRACTION_MEMORY_STATUS_ACTIVE,
    }


def merge_observed_sources(contract: dict, sources: list[str]) -> None:
    canonical_sources = [
        source for row in sources if (source := _normalized_source(row))
    ]
    candidates = _candidates_by_source(contract)
    for source in canonical_sources:
        candidate = candidates.setdefault(
            source, {"source": source, "success_count": 0}
        )
        candidate["success_count"] = _success_count(candidate) + 1
    current_source = _normalized_source(contract.get("selected_source"))
    if current_source:
        contract["selected_source"] = current_source
    if current_source and current_source not in canonical_sources:
        contract["rejection_count"] = int(contract.get("rejection_count") or 0) + 1
    contract["success_count"] = int(contract.get("success_count") or 0) + 1
    ordered = sorted(
        candidates.values(),
        key=lambda row: (-_success_count(row), str(row.get("source"))),
    )
    contract["candidates"] = _limited(ordered, candidates.get(current_source))
    _promote_observed_source(contract, candidates, ordered, current_source)


def _candidates_by_source(contract: dict) -> dict[str, dict]:
    candidates: dict[str, dict] = {}
    for row in contract.get("candidates", []):
        if not isinstance(row, dict):
            continue
        source = _normalized_source(row.get("source"))
        if source:
            candidates[source] = dict(row, source=source)
    return candidates


def _limited(ordered: list[dict], selected: dict | None) -> list[dict]:
    limited = ordered[: cfg.EXTRACTION_CONTRACT_CANDIDATE_LIMIT]
    if selected is not None and selected not in limited:
        limited[-1:] = [selected]
    return limited


def _promote_observed_source(
    contract: dict,
    candidates: dict[str, dict],
    ordered: list[dict],
    current_source: str,
) -> None:
    if not ordered or str(contract.get("selection_origin") or "") != (
        cfg.EXTRACTION_CONTRACT_SELECTION_ORIGIN_GENERIC
    ):
        return
    best_source = str(ordered[0].get("source") or "")
    current_count = _success_count(candidates.get(current_source) or {})
    selected_source = (
        current_source if current_count == _success_count(ordered[0]) else best_source
    )
    if selected_source == current_source:
        return
    contract["selected_source"] = selected_source
    history = list(contract.get("selection_history") or [])
    entry = {
        "selected_source": selected_source,
        "source": cfg.EXTRACTION_CONTRACT_OBSERVATION_SOURCE,
    }
    history.append(entry)
    contract["selection_history"] = history[-cfg.EXTRACTION_CONTRACT_HISTORY_LIMIT :]


def _success_count(candidate: dict) -> int:
    return int(candidate.get("success_count") or 0)


def _normalized_source(value: object) -> str:
    return normalize_source_pattern(str(value or ""))
