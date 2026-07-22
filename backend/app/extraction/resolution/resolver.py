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
    Evidence,
    Finding,
    ResolutionResult,
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



def resolve(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    findings: tuple[Finding, ...],
    *,
    contract_preferences: Mapping[str, tuple[str, ...]] | None = None,
) -> ResolutionResult:
    preferences = contract_preferences or {}
    by_id = {ev.evidence_id: ev for ev in evidence}
    decisions: list[Decision] = []
    rejected_product_subjects = _url_mismatched_product_subjects(evidence)
    for product in entities.products:
        for fact, ids in sorted(product.attribute_evidence.items()):
            eligible_ids = tuple(
                evidence_id
                for evidence_id in ids
                if by_id[evidence_id].subject_id not in rejected_product_subjects
            )
            decisions.append(
                _resolve_scalar(
                    product.entity_id,
                    fact,
                    eligible_ids,
                    by_id,
                    findings,
                    preferred_evidence_ids=preferences.get(fact, ()),
                )
            )
    for variant in entities.variants:
        decisions.extend(_resolve_variant(variant, by_id, findings))
    for offer in entities.offers:
        decisions.extend(
            _resolve_offer(
                offer,
                by_id,
                findings,
                preferred_evidence_ids=(
                    preferences if offer.variant_entity_id is None else {}
                ),
            )
        )
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
    for asset in entities.assets:
        decisions.append(_resolve_asset(asset, by_id, findings))
    resolved = {
        decision.fact_type for decision in decisions if decision.status == "resolved"
    }
    required = {"product.url", field_mappings.PRODUCT_TITLE_FACT_TYPE}
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
    derived_facts = (
        *derived_facts,
        *_inherit_variant_offer_facts(
            entities,
            tuple(decisions),
            derived_facts,
            primary_offer_entity_id=primary_offer_entity_id,
            evidence_by_id=by_id,
        ),
    )
    variant_decisions = _resolve_variants(entities, decisions, derived_facts, by_id)
    variant_decisions, reconciliation_facts = _reconcile_variant_prices(
        variant_decisions,
        primary_offer_entity_id=primary_offer_entity_id,
        decisions=tuple(decisions),
        derived_facts=derived_facts,
        evidence_by_id=by_id,
    )
    derived_facts = (
        *derived_facts,
        *reconciliation_facts,
        *_parent_derived_from_variants(
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
        ),
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
