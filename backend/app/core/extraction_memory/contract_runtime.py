"""Frozen contract preferences for resolver-owned extraction ranking."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.core.config import field_mappings
from app.core.config.extraction_memory import (
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    EXTRACTION_RELEASE_VERSION,
)
from app.core.extraction_memory.templates import (
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
    templates = [
        row
        for row in snapshot.get("templates", [])
        if isinstance(row, dict)
        and str(row.get("status") or "").strip().lower()
        != EXTRACTION_MEMORY_STATUS_SUSPENDED
        and not bool(row.get("sentinel_suspended"))
    ]
    exact = next(
        (row for row in templates if row.get("fingerprint") == fingerprint), None
    )
    route = normalize_route(url, surface) if url else ""
    route_matches = (
        [row for row in templates if row.get("route_pattern") == route] if route else []
    )

    matched: dict[str, Any] | None = exact
    if exact is not None and route_matches:
        matched = _merge_template_contracts(exact, route_matches)
    elif route_matches:
        matched = _merge_template_contracts(route_matches[0], route_matches[1:])

    # Manual extraction preferences are domain + surface defaults. Templates
    # remain in the snapshot for provenance and automatic route matching, but an
    # operator choice must apply to every future URL on the same surface.
    operator_templates: list[dict[str, Any]] = []
    for template in templates:
        operator_contracts = [
            contract
            for contract in template.get("contracts", [])
            if contract.get("selection_origin") == "operator"
        ]
        if operator_contracts:
            operator_template = dict(template)
            operator_template["contracts"] = operator_contracts
            operator_templates.append(operator_template)

    if not operator_templates:
        return matched
    if matched is None:
        matched = {
            "fingerprint": fingerprint,
            "route_pattern": route,
            "template_key": "domain-surface-preferences",
            "contracts": [],
        }
    return _merge_template_contracts(matched, operator_templates)


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
            next(
                (
                    row
                    for evidence_id in decision.accepted_evidence_ids
                    if (row := evidence_by_id.get(evidence_id)) is not None
                    and _source_descriptor(row) == selected_source
                ),
                None,
            )
            if decision
            else None
        )
        applied = bool(
            selected and decision and decision.rule_id == "CONTRACT_PREFERRED_SOURCE"
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
            if current is None or selection_priority(contract) > selection_priority(
                current
            ):
                contracts_by_field[field] = contract
    merged = dict(exact)
    merged["contracts"] = list(contracts_by_field.values())
    return merged


def selection_priority(contract: dict[str, Any]) -> int:
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


def select_active_recipe(
    snapshot: dict[str, Any],
    *,
    surface: str,
    url: str,
    template_signature: str = "",
) -> dict[str, Any] | None:
    """Select one executable-recipe release entry before discovery runs.

    Reads the unified frozen release payload produced by ``build_release_payload``
    (``schema_version == EXTRACTION_RELEASE_VERSION``). A template participates in
    recipe replay only when it carries an ``executable_recipe`` block — the
    ``extraction_recipe.v2`` payload — kept distinct from the selector/contract
    ``compiled_recipe`` block that drives the deterministic floors.
    """
    if (
        snapshot.get("schema_version") != EXTRACTION_RELEASE_VERSION
        or snapshot.get("surface") != surface
    ):
        return None
    route = _normalized_recipe_route(normalize_route(url, surface))
    templates = [
        row
        for row in snapshot.get("templates", ())
        if isinstance(row, dict)
        and isinstance(row.get("executable_recipe"), dict)
        and str(row.get("status") or "active") != EXTRACTION_MEMORY_STATUS_SUSPENDED
        and not bool(row.get("sentinel_suspended"))
    ]
    if template_signature:
        exact = next(
            (
                row
                for row in templates
                if str(row.get("template_signature") or "") == template_signature
            ),
            None,
        )
        if exact is not None:
            return exact
    return next(
        (
            row
            for row in templates
            if _normalized_recipe_route(str(row.get("route_pattern") or "/")) == route
        ),
        None,
    )


def _normalized_recipe_route(value: str) -> str:
    return re.sub(r"\{[^/{}]+\}", "{id}", str(value or "/"))
