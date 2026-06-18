from __future__ import annotations

from app.services.extraction_v2.contracts import DerivedFact, Evidence, Finding, ResolutionResult
from app.services.extraction_v2.entities.contracts import EntitySet
from app.services.extraction_v2.ids import stable_id
from app.services.extraction_v2.resolution.assets import resolve_asset
from app.services.extraction_v2.resolution.identity import primary_product_id
from app.services.extraction_v2.resolution.offers import resolve_offer
from app.services.extraction_v2.resolution.scalar import resolve_scalar
from app.services.extraction_v2.resolution.variants import resolve_variant


def resolve(evidence: tuple[Evidence, ...], entities: EntitySet, findings: tuple[Finding, ...]) -> ResolutionResult:
    by_id = {ev.evidence_id: ev for ev in evidence}
    decisions = []
    for product in entities.products:
        for fact, ids in sorted(product.attribute_evidence.items()):
            decisions.append(resolve_scalar(product.entity_id, fact, ids, by_id, findings))
    for variant in entities.variants:
        decisions.extend(resolve_variant(variant, by_id, findings))
    for offer in entities.offers:
        decisions.extend(resolve_offer(offer, by_id, findings))
    for asset in entities.assets:
        decisions.append(resolve_asset(asset, by_id, findings))
    resolved = {decision.fact_type for decision in decisions if decision.status == "resolved"}
    required = {"product.url", "product.title"}
    return ResolutionResult(
        primary_product_entity_id=primary_product_id(entities),
        decisions=tuple(decisions),
        derived_facts=_derived(decisions, by_id),
        unresolved_fact_types=tuple(sorted(required - resolved)),
        blocking_finding_ids=tuple(sorted(f.finding_id for f in findings if f.blocking)),
    )


def _derived(decisions, by_id: dict[str, Evidence]) -> tuple[DerivedFact, ...]:
    out: list[DerivedFact] = []
    for decision in decisions:
        if decision.fact_type not in {"offer.price", "offer.original_price"} or not decision.accepted_evidence_ids:
            continue
        ev = by_id[decision.accepted_evidence_ids[0]]
        try:
            value = f"{float(str(ev.value).replace(',', '')):.2f}"
        except (TypeError, ValueError):
            continue
        out.append(DerivedFact(derived_fact_id=stable_id("derived", "NORMALIZE_MONEY_PRECISION", decision.entity_id, decision.fact_type, value), entity_id=decision.entity_id, fact_type=decision.fact_type, value=value, input_evidence_ids=decision.accepted_evidence_ids, rule_id="NORMALIZE_MONEY_PRECISION"))
    return tuple(out)
