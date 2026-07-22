"""Resolve orchestration: decisions, derived facts, variants, assets."""
from __future__ import annotations

from collections.abc import Mapping

from app.core.config import field_mappings
from app.core.config.extraction_rules import PRODUCT_ASSET_IDENTITY_FACT_TYPES
from app.core.records.url_identity import conflicting_product_asset_urls
from app.core.shared.ids import stable_id
from app.core.shared.url_utils import low_resolution_asset_urls
from app.extraction.contracts import (
    Decision,
    DerivedFact,
    Evidence,
    Finding,
    ResolutionResult,
    VariantDecision,
)
from app.extraction.entities import EntitySet
from app.extraction.resolution.assets import (
    normalize_asset_url,
    resolve_product_assets,
)
from app.extraction.resolution.decisions import (
    _asset_publication_facts,
    _resolve_asset,
    _resolve_scalar,
    _url_mismatched_product_subjects,
)
from app.extraction.resolution.derived import _derived
from app.extraction.resolution.lineage import _resolved_product_url
from app.extraction.resolution.offers import (
    _preferred_parent_offer_id,
    _resolve_offer,
)
from app.extraction.resolution.price_units import (
    _price_unit_derived_facts,
    _price_unit_repairs,
)
from app.extraction.resolution.variant_rollup import (
    _inherit_variant_offer_facts,
    _parent_derived_from_variants,
    _reconcile_variant_prices,
)
from app.extraction.resolution.variants import (
    _resolve_variant,
    _resolve_variants,
)


def _product_scalar_decisions(
    entities: EntitySet,
    evidence: tuple[Evidence, ...],
    by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
    preferences: Mapping[str, tuple[str, ...]],
) -> list[Decision]:
    rejected_product_subjects = _url_mismatched_product_subjects(evidence)
    rows: list[Decision] = []
    for product in entities.products:
        for fact, ids in sorted(product.attribute_evidence.items()):
            eligible_ids = tuple(
                evidence_id
                for evidence_id in ids
                if by_id[evidence_id].subject_id not in rejected_product_subjects
            )
            rows.append(
                _resolve_scalar(
                    product.entity_id,
                    fact,
                    eligible_ids,
                    by_id,
                    findings,
                    preferred_evidence_ids=preferences.get(fact, ()),
                )
            )
    return rows


def _offer_decisions(
    entities: EntitySet,
    by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
    preferences: Mapping[str, tuple[str, ...]],
) -> list[Decision]:
    rows: list[Decision] = []
    for offer in entities.offers:
        rows.extend(
            _resolve_offer(
                offer,
                by_id,
                findings,
                preferred_evidence_ids=(
                    preferences if offer.variant_entity_id is None else {}
                ),
            )
        )
    return rows


def _entity_decisions(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
    preferences: Mapping[str, tuple[str, ...]],
) -> list[Decision]:
    """Product-scalar, variant, and offer decisions (asset decisions come later)."""
    rows = _product_scalar_decisions(entities, evidence, by_id, findings, preferences)
    for variant in entities.variants:
        rows.extend(_resolve_variant(variant, by_id, findings))
    rows.extend(_offer_decisions(entities, by_id, findings, preferences))
    return rows


def _primary_entity_ids(
    entities: EntitySet,
    decisions: list[Decision],
    by_id: dict[str, Evidence],
) -> tuple[str | None, str | None]:
    primary_product_entity_id = (
        entities.products[0].entity_id if len(entities.products) == 1 else None
    )
    primary_offer_entity_id = _preferred_parent_offer_id(entities, decisions, by_id)
    if (
        primary_offer_entity_id is None
        and primary_product_entity_id
        and entities.variants
    ):
        primary_offer_entity_id = stable_id(
            "offer", primary_product_entity_id, "variant_aggregate"
        )
    return primary_product_entity_id, primary_offer_entity_id


def _asset_url_policies(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    by_id: dict[str, Evidence],
) -> tuple[frozenset[str], frozenset[str]]:
    asset_urls = tuple(
        str(by_id[evidence_id].value)
        for asset in entities.assets
        for evidence_id in asset.url_evidence_ids
        if evidence_id in by_id
    )
    conflicting_urls = frozenset(
        normalize_asset_url(value)
        for value in conflicting_product_asset_urls(
            tuple(
                ev.value
                for ev in evidence
                if ev.fact_type in PRODUCT_ASSET_IDENTITY_FACT_TYPES
            ),
            asset_urls,
        )
    )
    low_resolution_urls = frozenset(
        normalize_asset_url(value) for value in low_resolution_asset_urls(asset_urls)
    )
    return conflicting_urls, low_resolution_urls


def _base_derived_facts(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    decisions: list[Decision],
    by_id: dict[str, Evidence],
    primary_offer_entity_id: str | None,
) -> tuple[DerivedFact, ...]:
    """Derived facts from scalar decisions, price units, and variant offer inheritance."""
    derived_facts = _derived(
        decisions,
        by_id,
        page_url=_resolved_product_url(decisions, by_id),
    )
    derived_facts = (
        *derived_facts,
        *_price_unit_derived_facts(
            tuple(decisions),
            by_id,
            _price_unit_repairs(evidence, entities),
        ),
    )
    return (
        *derived_facts,
        *_inherit_variant_offer_facts(
            entities,
            tuple(decisions),
            derived_facts,
            primary_offer_entity_id=primary_offer_entity_id,
            evidence_by_id=by_id,
        ),
    )


def _variant_decision_pipeline(
    entities: EntitySet,
    decisions: list[Decision],
    derived_facts: tuple[DerivedFact, ...],
    *,
    primary_offer_entity_id: str | None,
    primary_product_entity_id: str | None,
    by_id: dict[str, Evidence],
) -> tuple[tuple[VariantDecision, ...], tuple[DerivedFact, ...]]:
    """Resolve variants, reconcile prices, and roll parent facts up from survivors."""
    variant_decisions = _resolve_variants(entities, decisions, derived_facts, by_id)
    variant_decisions, reconciliation_facts = _reconcile_variant_prices(
        variant_decisions,
        primary_offer_entity_id=primary_offer_entity_id,
        decisions=tuple(decisions),
        derived_facts=derived_facts,
        evidence_by_id=by_id,
    )
    parent_facts = _parent_derived_from_variants(
        primary_offer_entity_id=primary_offer_entity_id,
        primary_product_entity_id=primary_product_entity_id,
        variant_decisions=variant_decisions,
        expected_variant_count=len(entities.variants),
        selected_variant_ids=frozenset(
            variant.entity_id for variant in entities.variants if variant.selected
        ),
        existing_fact_keys=frozenset(
            (
                *(
                    (row.entity_id, row.fact_type)
                    for row in decisions
                    if row.status == "resolved"
                ),
                *(
                    (row.entity_id, row.fact_type)
                    for row in (*derived_facts, *reconciliation_facts)
                ),
            )
        ),
    )
    return variant_decisions, (*derived_facts, *reconciliation_facts, *parent_facts)


def resolve(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    findings: tuple[Finding, ...],
    *,
    contract_preferences: Mapping[str, tuple[str, ...]] | None = None,
) -> ResolutionResult:
    preferences = contract_preferences or {}
    by_id = {ev.evidence_id: ev for ev in evidence}
    decisions = _entity_decisions(evidence, entities, by_id, findings, preferences)
    primary_product_entity_id, primary_offer_entity_id = _primary_entity_ids(
        entities, decisions, by_id
    )
    for asset in entities.assets:
        decisions.append(_resolve_asset(asset, by_id, findings))
    conflicting_urls, low_resolution_urls = _asset_url_policies(
        evidence, entities, by_id
    )
    derived_facts = _base_derived_facts(
        evidence, entities, decisions, by_id, primary_offer_entity_id
    )
    variant_decisions, derived_facts = _variant_decision_pipeline(
        entities,
        decisions,
        derived_facts,
        primary_offer_entity_id=primary_offer_entity_id,
        primary_product_entity_id=primary_product_entity_id,
        by_id=by_id,
    )
    asset_decisions = resolve_product_assets(
        entities.assets,
        by_id,
        conflicting_urls,
        low_resolution_urls,
        variants=entities.variants,
        variant_decisions=variant_decisions,
    )
    derived_facts = (
        *derived_facts,
        *_asset_publication_facts(asset_decisions, tuple(decisions)),
    )
    resolved = {
        decision.fact_type for decision in decisions if decision.status == "resolved"
    }
    required = {"product.url", field_mappings.PRODUCT_TITLE_FACT_TYPE}
    return ResolutionResult(
        primary_product_entity_id=primary_product_entity_id,
        primary_offer_entity_id=primary_offer_entity_id,
        decisions=tuple(decisions),
        asset_decisions=asset_decisions,
        variant_decisions=variant_decisions,
        derived_facts=derived_facts,
        unresolved_fact_types=tuple(sorted(required - resolved)),
        blocking_finding_ids=tuple(
            sorted(f.finding_id for f in findings if f.blocking)
        ),
    )
