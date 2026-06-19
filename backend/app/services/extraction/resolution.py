from __future__ import annotations

from app.services.extraction.contracts import (
    Decision,
    DerivedFact,
    Evidence,
    Finding,
    RejectedEvidence,
    ResolutionResult,
)
from app.services.extraction.entities import AssetEntity, EntitySet, OfferEntity, VariantEntity
from app.services.extraction.ids import stable_id
from app.services.config.extraction_rules._images import PRIMARY_IMAGE_REJECT_URL_TOKENS


def resolve(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    findings: tuple[Finding, ...],
) -> ResolutionResult:
    by_id = {ev.evidence_id: ev for ev in evidence}
    decisions: list[Decision] = []
    for product in entities.products:
        for fact, ids in sorted(product.attribute_evidence.items()):
            decisions.append(_resolve_scalar(product.entity_id, fact, ids, by_id, findings))
    for variant in entities.variants:
        decisions.extend(_resolve_variant(variant, by_id, findings))
    for offer in entities.offers:
        decisions.extend(_resolve_offer(offer, by_id, findings))
    for asset in entities.assets:
        decisions.append(_resolve_asset(asset, by_id, findings))
    resolved = {decision.fact_type for decision in decisions if decision.status == "resolved"}
    required = {"product.url", "product.title"}
    return ResolutionResult(
        primary_product_entity_id=entities.products[0].entity_id if len(entities.products) == 1 else None,
        decisions=tuple(decisions),
        derived_facts=_derived(decisions, by_id),
        unresolved_fact_types=tuple(sorted(required - resolved)),
        blocking_finding_ids=tuple(sorted(f.finding_id for f in findings if f.blocking)),
    )


def _resolve_variant(
    variant: VariantEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> tuple[Decision, ...]:
    return tuple(
        _resolve_scalar(variant.entity_id, fact, ids, evidence_by_id, findings)
        for fact, ids in sorted(variant.attribute_evidence.items())
    )


def _resolve_offer(
    offer: OfferEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> tuple[Decision, ...]:
    if not offer.fact_evidence.get("offer.price") or not offer.fact_evidence.get("offer.currency"):
        return ()
    return tuple(
        _resolve_scalar(offer.entity_id, fact, ids, evidence_by_id, findings)
        for fact, ids in sorted(offer.fact_evidence.items())
    )


def _resolve_asset(
    asset: AssetEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> Decision:
    if any(_invalid_primary_asset_url(evidence_by_id[eid].value) for eid in asset.url_evidence_ids if eid in evidence_by_id):
        return Decision(
            decision_id=stable_id("decision", asset.entity_id, "asset.image_url", asset.url_evidence_ids),
            entity_id=asset.entity_id,
            fact_type="asset.image_url",
            accepted_evidence_ids=(),
            rejected=tuple(
                RejectedEvidence(evidence_id=eid, reason="invalid_primary_asset")
                for eid in asset.url_evidence_ids
            ),
            finding_ids=(),
            rule_id="PRIMARY_ASSET_REJECTION",
            status="unresolved",
        )
    return _resolve_scalar(asset.entity_id, "asset.image_url", asset.url_evidence_ids, evidence_by_id, findings)


def _invalid_primary_asset_url(value: object) -> bool:
    text = str(value or "").casefold()
    return any(token in text for token in PRIMARY_IMAGE_REJECT_URL_TOKENS)


def _resolve_scalar(
    entity_id: str,
    fact_type: str,
    ids: tuple[str, ...],
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> Decision:
    candidates = sorted((evidence_by_id[eid] for eid in ids if eid in evidence_by_id), key=_rank)
    blocking = {eid for finding in findings if finding.blocking for eid in finding.evidence_ids}
    admissible = [ev for ev in candidates if ev.evidence_id not in blocking and not _invalid(ev)]
    finding_ids = tuple(f.finding_id for f in findings if set(f.evidence_ids) & set(ids))
    if not admissible:
        return Decision(
            decision_id=stable_id("decision", entity_id, fact_type, ids),
            entity_id=entity_id,
            fact_type=fact_type,
            accepted_evidence_ids=(),
            rejected=tuple(
                RejectedEvidence(
                    evidence_id=ev.evidence_id,
                    reason="blocked_by_finding" if ev.evidence_id in blocking else "invalid_value",
                )
                for ev in candidates
            ),
            finding_ids=finding_ids,
            rule_id="SCALAR_LEXICOGRAPHIC",
            status="unresolved",
        )
    winner = admissible[0]
    return Decision(
        decision_id=stable_id("decision", entity_id, fact_type, winner.evidence_id),
        entity_id=entity_id,
        fact_type=fact_type,
        accepted_evidence_ids=(winner.evidence_id,),
        rejected=tuple(
            RejectedEvidence(
                evidence_id=ev.evidence_id,
                reason="stable_tiebreak" if _rank(ev) == _rank(winner) else "lower_confidence",
            )
            for ev in candidates
            if ev.evidence_id != winner.evidence_id
        ),
        finding_ids=finding_ids,
        rule_id="SCALAR_LEXICOGRAPHIC",
        status="resolved",
    )


def _derived(decisions: list[Decision], by_id: dict[str, Evidence]) -> tuple[DerivedFact, ...]:
    out: list[DerivedFact] = []
    for decision in decisions:
        if decision.fact_type not in {"offer.price", "offer.original_price"} or not decision.accepted_evidence_ids:
            continue
        ev = by_id[decision.accepted_evidence_ids[0]]
        try:
            value = f"{float(str(ev.value).replace(',', '')):.2f}"
        except (TypeError, ValueError):
            continue
        out.append(
            DerivedFact(
                derived_fact_id=stable_id("derived", "NORMALIZE_MONEY_PRECISION", decision.entity_id, decision.fact_type, value),
                entity_id=decision.entity_id,
                fact_type=decision.fact_type,
                value=value,
                input_evidence_ids=decision.accepted_evidence_ids,
                rule_id="NORMALIZE_MONEY_PRECISION",
            )
        )
    return tuple(out)


def _invalid(ev: Evidence) -> bool:
    return bool(set(ev.flags) & {"invalid_decimal", "invalid_currency", "invalid_gtin", "placeholder_text", "tracking_url"})


def _rank(ev: Evidence) -> tuple[int, int, float, str]:
    directness = {"direct": 0, "embedded": 1, "inferred": 2}.get(ev.directness, 3)
    reliability = {
        "jsonld": 0,
        "microdata": 1,
        "js_state": 2,
        "network": 3,
        "opengraph": 4,
        "dom": 5,
        "url": 6,
    }.get(ev.collector_id, 7)
    return directness, reliability, -float(ev.confidence), ev.evidence_id
