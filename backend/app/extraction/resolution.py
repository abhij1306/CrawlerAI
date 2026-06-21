from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.extraction.contracts import (
    AssetDecision,
    Decision,
    DerivedFact,
    Evidence,
    Finding,
    RejectedEvidence,
    ResolutionResult,
)
from app.core.config.variant_policy import (
    DETAIL_PARENT_INHERITED_OFFER_FIELDS,
    DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID,
)
from app.core.shared.url_utils import is_utility_image_url
from app.extraction.entities import AssetEntity, EntitySet, OfferEntity, VariantEntity
from app.extraction.ids import stable_id


def resolve(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    findings: tuple[Finding, ...],
) -> ResolutionResult:
    by_id = {ev.evidence_id: ev for ev in evidence}
    decisions: list[Decision] = []
    for product in entities.products:
        for fact, ids in sorted(product.attribute_evidence.items()):
            decisions.append(
                _resolve_scalar(product.entity_id, fact, ids, by_id, findings)
            )
    for variant in entities.variants:
        decisions.extend(_resolve_variant(variant, by_id, findings))
    for offer in entities.offers:
        decisions.extend(_resolve_offer(offer, by_id, findings))
    decisions.extend(_inherit_variant_offer_decisions(entities, decisions))
    for asset in entities.assets:
        decisions.append(_resolve_asset(asset, by_id, findings))
    resolved = {
        decision.fact_type for decision in decisions if decision.status == "resolved"
    }
    required = {"product.url", "product.title"}
    return ResolutionResult(
        primary_product_entity_id=entities.products[0].entity_id
        if len(entities.products) == 1
        else None,
        decisions=tuple(decisions),
        asset_decisions=_resolve_product_assets(entities.assets, by_id),
        derived_facts=_derived(decisions, by_id),
        unresolved_fact_types=tuple(sorted(required - resolved)),
        blocking_finding_ids=tuple(
            sorted(f.finding_id for f in findings if f.blocking)
        ),
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


def _resolve_offer(offer: OfferEntity, evidence_by_id: dict[str, Evidence], findings: tuple[Finding, ...]) -> tuple[Decision, ...]:
    incomplete_parent = offer.variant_entity_id is None and not (offer.fact_evidence.get("offer.price") and offer.fact_evidence.get("offer.currency"))
    blocked = {"offer.price", "offer.currency", "offer.original_price"} if incomplete_parent else set()
    return tuple(
        _resolve_scalar(offer.entity_id, fact, ids, evidence_by_id, findings)
        for fact, ids in sorted(offer.fact_evidence.items())
        if fact not in blocked
    )


def _inherit_variant_offer_decisions(entities: EntitySet, decisions: list[Decision]) -> tuple[Decision, ...]:
    facts = tuple(f"offer.{field}" for field in DETAIL_PARENT_INHERITED_OFFER_FIELDS)
    resolved = {(item.entity_id, item.fact_type): item for item in decisions if item.status == "resolved"}
    parents = [offer for offer in entities.offers if offer.variant_entity_id is None]
    parent = max(parents, key=lambda offer: (sum((offer.entity_id, fact) in resolved for fact in facts), offer.entity_id), default=None)
    if parent is None:
        return ()
    direct = {(offer.variant_entity_id, fact) for offer in entities.offers if offer.variant_entity_id for fact in facts if (offer.entity_id, fact) in resolved}
    return tuple(
        resolved[(parent.entity_id, fact)].model_copy(update={"decision_id": stable_id("decision", variant.entity_id, fact, "parent_inheritance"), "entity_id": variant.entity_id, "rejected": (), "rule_id": DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID})
        for variant in entities.variants
        for fact in facts
        if (variant.option_values or variant.identity_key.startswith(("sku:", "gtin:")))
        and (variant.entity_id, fact) not in direct
        and (parent.entity_id, fact) in resolved
    )


def _resolve_asset(
    asset: AssetEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> Decision:
    if any(
        _invalid_primary_asset_url(evidence_by_id[eid].value)
        for eid in asset.url_evidence_ids
        if eid in evidence_by_id
    ):
        return Decision(
            decision_id=stable_id(
                "decision", asset.entity_id, "asset.image_url", asset.url_evidence_ids
            ),
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
    return _resolve_scalar(
        asset.entity_id,
        "asset.image_url",
        asset.url_evidence_ids,
        evidence_by_id,
        findings,
    )


def _invalid_primary_asset_url(value: object) -> bool:
    return is_utility_image_url(value)


def _resolve_product_assets(
    assets: tuple[AssetEntity, ...],
    evidence_by_id: dict[str, Evidence],
) -> tuple[AssetDecision, ...]:
    ranked = [
        (rank, asset, accepted)
        for asset in assets
        if asset.variant_entity_id is None
        for accepted in [_accepted_asset_evidence(asset, evidence_by_id)]
        for rank in [_asset_rank(asset, accepted, evidence_by_id)]
    ]
    valid = [
        (rank, asset, accepted)
        for rank, asset, accepted in ranked
        if accepted and not _invalid_primary_asset_url(asset.url)
    ]
    valid.sort(key=lambda item: item[0])
    decisions: list[AssetDecision] = []
    seen: set[str] = set()
    for index, (_rank_value, asset, accepted) in enumerate(valid):
        if asset.identity_key in seen:
            continue
        seen.add(asset.identity_key)
        decisions.append(
            AssetDecision(
                asset_entity_id=asset.entity_id,
                url=asset.url,
                accepted_evidence_ids=(accepted.evidence_id,),
                role="primary" if not decisions else "additional",
                rank=index,
                rule_id=(
                    "PRODUCT_ASSET_PRIMARY"
                    if not decisions
                    else "PRODUCT_ASSET_ADDITIONAL"
                ),
            )
        )
    rejected = [
        AssetDecision(
            asset_entity_id=asset.entity_id,
            url=asset.url,
            accepted_evidence_ids=(),
            role="rejected",
            rank=len(valid) + index,
            rule_id="PRODUCT_ASSET_REJECT",
            rejection_reasons=("invalid_primary_asset",),
        )
        for index, (_rank_value, asset, accepted) in enumerate(ranked)
        if accepted and _invalid_primary_asset_url(asset.url)
    ]
    return tuple(decisions + rejected)


def _accepted_asset_evidence(
    asset: AssetEntity,
    evidence_by_id: dict[str, Evidence],
) -> Evidence | None:
    candidates = [
        evidence_by_id[eid] for eid in asset.url_evidence_ids if eid in evidence_by_id
    ]
    if not candidates:
        return None
    return sorted(candidates, key=_rank)[0]


def _asset_rank(
    asset: AssetEntity,
    accepted: Evidence | None,
    evidence_by_id: dict[str, Evidence],
) -> tuple[int, int, tuple[int, int, float, str] | tuple[int, int, int, float, str], str]:
    if accepted is None:
        return (99, 99, (99, 99, 0.0, ""), asset.entity_id)
    role = _asset_role_rank(asset.url)
    source_order = min(
        (
            _asset_source_order(evidence_by_id[eid])
            for eid in asset.url_evidence_ids
            if eid in evidence_by_id
        ),
        default=99,
    )
    source_rank = min(
        (_rank(evidence_by_id[eid]) for eid in asset.url_evidence_ids if eid in evidence_by_id),
        default=_rank(accepted),
    )
    return role, source_order, source_rank, asset.entity_id


def _asset_role_rank(url: str) -> int:
    text = str(url or "").casefold()
    if any(token in text for token in ("main", "primary", "hero", "pdp")):
        return 0
    if any(token in text for token in ("product", "detail", "gallery", "diagram")):
        return 1
    return 2


def _asset_source_order(ev: Evidence) -> int:
    for token in reversed(str(ev.locator.value or "").replace("[", "/").replace("]", "").split("/")):
        if token.isdigit():
            return int(token)
    return 99


def _resolve_scalar(
    entity_id: str,
    fact_type: str,
    ids: tuple[str, ...],
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> Decision:
    candidates = sorted((evidence_by_id[eid] for eid in ids if eid in evidence_by_id), key=_rank)
    blocking = {eid for finding in findings if finding.blocking for eid in finding.evidence_ids}
    admissible = [
        ev for ev in candidates if ev.evidence_id not in blocking and not _invalid(ev)
    ]
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
                    reason="blocked_by_finding"
                    if ev.evidence_id in blocking
                    else "invalid_value",
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
                reason="stable_tiebreak"
                if _rank(ev) == _rank(winner)
                else "lower_confidence",
            )
            for ev in candidates
            if ev.evidence_id != winner.evidence_id
        ),
        finding_ids=finding_ids,
        rule_id=(
            "TITLE_URL_REVIEW_ONLY"
            if fact_type == "product.title" and "url_derived_title" in winner.flags
            else "TITLE_SEMANTIC_RANKING"
            if fact_type == "product.title"
            else "SCALAR_LEXICOGRAPHIC"
        ),
        status="resolved",
    )


def _derived(
    decisions: list[Decision], by_id: dict[str, Evidence]
) -> tuple[DerivedFact, ...]:
    out: list[DerivedFact] = []
    for decision in decisions:
        if (
            decision.fact_type not in {"offer.price", "offer.original_price"}
            or not decision.accepted_evidence_ids
        ):
            continue
        ev = by_id[decision.accepted_evidence_ids[0]]
        try:
            value = f"{float(str(ev.value).replace(',', '')):.2f}"
        except (TypeError, ValueError):
            continue
        rule_id = decision.rule_id if decision.rule_id == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID else "NORMALIZE_MONEY_PRECISION"
        out.append(
            DerivedFact(
                derived_fact_id=stable_id(
                    "derived", rule_id, decision.entity_id, decision.fact_type, value
                ),
                entity_id=decision.entity_id,
                fact_type=decision.fact_type,
                value=value,
                input_evidence_ids=decision.accepted_evidence_ids,
                rule_id=rule_id,
            )
        )
    return tuple(out)


def _invalid(ev: Evidence) -> bool:
    if ev.fact_type in {"offer.price", "offer.original_price"} and _non_positive_money(
        ev.value
    ):
        return True
    return bool(
        set(ev.flags)
        & {
            "code_only_title",
            "filename_title",
            "generic_title",
            "invalid_decimal",
            "invalid_currency",
            "invalid_gtin",
            "placeholder_text",
            "tracking_url",
            "truncated_title",
        }
    )


def _non_positive_money(value: object) -> bool:
    try:
        return Decimal(str(value)) <= 0
    except (InvalidOperation, ValueError):
        return False


def _rank(
    ev: Evidence,
) -> tuple[int, int, float, str] | tuple[int, int, int, float, str]:
    directness = {"direct": 0, "embedded": 1, "inferred": 2}.get(ev.directness, 3)
    reliability = {
        "jsonld": 0,
        "microdata": 1,
        "js_state": 2,
        "network": 3,
        "opengraph": 4,
        "dom": 5,
        "css_recipe": 5,
        "url": 6,
    }.get(ev.collector_id, 7)
    if ev.fact_type == "product.title":
        if "shell_title" in ev.flags:
            return -1, 0, reliability, -float(ev.confidence), ev.evidence_id
        pollution = int("seo_title_pollution" in ev.flags)
        url_disagreement = int("title_url_mismatch" in ev.flags)
        return (
            pollution,
            url_disagreement,
            reliability,
            -float(ev.confidence),
            ev.evidence_id,
        )
    return directness, reliability, -float(ev.confidence), ev.evidence_id
