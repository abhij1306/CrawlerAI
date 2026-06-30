"""Frozen contract preferences for resolver-owned extraction ranking."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.config import field_mappings
from app.core.knowledge_graph.templates import (
    normalize_route,
    normalize_source_pattern,
    source_pattern,
)
from app.extraction.contracts import ContractOutcome, ResolutionResult

if TYPE_CHECKING:
    from app.extraction.contracts import Evidence


def match_template(
    snapshot: dict[str, Any], fingerprint: str, surface: str, url: str = ""
) -> dict[str, Any] | None:
    if not snapshot or snapshot.get("surface") != surface:
        return None
    templates = snapshot.get("templates", [])
    exact = next(
        (row for row in templates if row.get("fingerprint") == fingerprint), None
    )
    route = normalize_route(url, surface) if url else ""
    if not route:
        return exact
    route_matches = [row for row in templates if row.get("route_pattern") == route]
    if exact is not None and route_matches:
        return _merge_template_contracts(exact, route_matches)
    if route_matches:
        return route_matches[0]
    return exact


def contract_preferences(
    snapshot: dict[str, Any],
    fingerprint: str,
    surface: str,
    evidence: tuple[Evidence, ...],
    requested_fields: frozenset[str],
    user_controlled_fields: frozenset[str],
    *,
    url: str = "",
) -> dict[str, tuple[str, ...]]:
    """Return source-matching IDs; Resolve still owns eligibility and ranking."""

    template = match_template(snapshot, fingerprint, surface, url)
    if not template:
        return {}
    preferences: dict[str, tuple[str, ...]] = {}
    for contract in template.get("contracts", []):
        fact_type = _contract_fact_type(contract)
        if not _contract_applies(
            fact_type,
            requested_fields=requested_fields,
            user_controlled_fields=user_controlled_fields,
        ):
            continue
        selected_source = normalize_source_pattern(
            str(contract.get("selected_source") or "")
        )
        if not selected_source:
            continue
        matches = tuple(
            row.evidence_id
            for row in evidence
            if row.fact_type == fact_type and _source_descriptor(row) == selected_source
        )
        if matches:
            preferences[fact_type] = matches
    return preferences


def resolved_contract_outcomes(
    snapshot: dict[str, Any],
    fingerprint: str,
    surface: str,
    evidence: tuple[Evidence, ...],
    resolution: ResolutionResult,
    requested_fields: frozenset[str],
    user_controlled_fields: frozenset[str],
    *,
    url: str = "",
) -> tuple[ContractOutcome, ...]:
    """Report in-resolver contract ranking. Never mutate resolved truth."""

    template = match_template(snapshot, fingerprint, surface, url)
    if not template:
        return ()
    evidence_by_id = {row.evidence_id: row for row in evidence}
    target_ids = {
        value
        for value in (
            resolution.primary_product_entity_id,
            resolution.primary_offer_entity_id,
        )
        if value
    }
    decisions = {
        row.fact_type: row
        for row in resolution.decisions
        if row.entity_id in target_ids
    }
    outcomes: list[ContractOutcome] = []
    for contract in template.get("contracts", []):
        fact_type = _contract_fact_type(contract)
        if not _contract_applies(
            fact_type,
            requested_fields=requested_fields,
            user_controlled_fields=user_controlled_fields,
        ):
            continue
        selected_source = normalize_source_pattern(
            str(contract.get("selected_source") or "")
        )
        if not selected_source:
            continue
        decision = decisions.get(fact_type)
        selected = (
            evidence_by_id.get(decision.accepted_evidence_ids[0])
            if decision and decision.accepted_evidence_ids
            else None
        )
        applied = bool(
            selected
            and _source_descriptor(selected) == selected_source
            and decision
            and decision.rule_id == "CONTRACT_PREFERRED_SOURCE"
        )
        outcomes.append(
            ContractOutcome(
                field=fact_type,
                outcome="hit" if applied else "fallback" if decision else "miss",
                selected_source=str(contract.get("selected_source") or ""),
                selection_origin=str(contract.get("selection_origin") or "generic"),
                applied=applied,
                detail=(
                    "selected inside resolver-owned candidate set"
                    if applied
                    else "preferred source unavailable or inadmissible; used generic ranking"
                    if decision
                    else "field unresolved"
                ),
            )
        )
    return tuple(outcomes)


def _contract_fact_type(contract: dict[str, Any]) -> str:
    field = str(contract.get("canonical_field") or "")
    return field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(field, field)


def _contract_applies(
    fact_type: str,
    *,
    requested_fields: frozenset[str],
    user_controlled_fields: frozenset[str],
) -> bool:
    aliases = _requested_aliases(fact_type)
    return bool(requested_fields.intersection(aliases)) and not bool(
        user_controlled_fields.intersection(aliases)
    )


def _source_descriptor(evidence: Evidence) -> str:
    return source_pattern(
        evidence.collector_id,
        evidence.locator.value if evidence.locator else "",
    )


def _merge_template_contracts(
    exact: dict[str, Any], route_matches: list[dict[str, Any]]
) -> dict[str, Any]:
    contracts_by_field: dict[str, dict[str, Any]] = {}
    for template in [exact, *route_matches]:
        for contract in template.get("contracts", []):
            field = str(contract.get("canonical_field") or "")
            current = contracts_by_field.get(field)
            if current is None or _selection_priority(contract) > _selection_priority(
                current
            ):
                contracts_by_field[field] = contract
    merged = dict(exact)
    merged["contracts"] = list(contracts_by_field.values())
    return merged


def _selection_priority(contract: dict[str, Any]) -> int:
    return {"llm_proposed": 0, "generic": 1, "operator": 2}.get(
        str(contract.get("selection_origin") or "generic"), 1
    )


def _requested_aliases(fact_type: str) -> frozenset[str]:
    aliases = {fact_type}
    for (
        requested_field,
        mapped_fact_type,
    ) in field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES.items():
        if mapped_fact_type == fact_type:
            aliases.add(requested_field)
    return frozenset(aliases)
