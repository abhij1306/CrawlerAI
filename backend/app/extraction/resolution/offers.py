"""Offer resolution: atomic price/currency pairing and parent selection."""

from __future__ import annotations

from collections.abc import Mapping

from app.core.config import field_mappings
from app.core.config.extraction_price_rules import (
    DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY,
)
from app.core.shared.ids import stable_id
from app.extraction.contracts import Decision, Evidence, Finding, RejectedEvidence
from app.extraction.entities import EntitySet, OfferEntity
from app.extraction.resolution.decisions import _invalidity_reason, _resolve_scalar
from app.extraction.resolution.ranking import rank


def _offer_rank(offer: OfferEntity) -> tuple[int, int, int, str]:
    facts = dict(offer.fact_evidence or {})
    commercial = (
        "offer.price",
        "offer.currency",
        "offer.availability",
        "offer.stock_quantity",
    )
    return (
        int(
            bool(facts.get("offer.availability"))
            or bool(facts.get("offer.stock_quantity"))
        ),
        sum(bool(facts.get(field)) for field in commercial),
        sum(len(tuple(ids or ())) for ids in facts.values()),
        offer.entity_id,
    )


def _resolve_offer(
    offer: OfferEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
    *,
    preferred_evidence_ids: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[Decision, ...]:
    preferences = dict(preferred_evidence_ids or {})
    atomic = _offer_atomic_price_currency_preferences(offer, evidence_by_id, findings)
    if atomic is None:
        blocked = {
            field_mappings.OFFER_PRICE_FACT_TYPE,
            field_mappings.OFFER_CURRENCY_FACT_TYPE,
        }
        return tuple(
            _offer_atomic_unresolved_decision(
                offer, fact, ids, evidence_by_id, findings
            )
            if fact in blocked
            else _resolve_scalar(
                offer.entity_id,
                fact,
                ids,
                evidence_by_id,
                findings,
                preferred_evidence_ids=preferences.get(fact, ()),
            )
            for fact, ids in sorted(offer.fact_evidence.items())
        )
    preferences.update(atomic)
    return tuple(
        _resolve_scalar(
            offer.entity_id,
            fact,
            ids,
            evidence_by_id,
            findings,
            preferred_evidence_ids=preferences.get(fact, ()),
        )
        for fact, ids in sorted(offer.fact_evidence.items())
    )


def _offer_atomic_price_currency_preferences(
    offer: OfferEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> dict[str, tuple[str, ...]] | None:
    price_fact = field_mappings.OFFER_PRICE_FACT_TYPE
    currency_fact = field_mappings.OFFER_CURRENCY_FACT_TYPE
    if (
        price_fact not in offer.fact_evidence
        or currency_fact not in offer.fact_evidence
    ):
        return {}
    blocking = {
        eid for finding in findings if finding.blocking for eid in finding.evidence_ids
    }
    prices = _admissible_offer_evidence(
        offer.fact_evidence.get(price_fact, ()), evidence_by_id, blocking=blocking
    )
    currencies = _admissible_offer_evidence(
        offer.fact_evidence.get(currency_fact, ()), evidence_by_id, blocking=blocking
    )
    if not prices or not currencies:
        return {}
    pairs = [
        (price, currency)
        for price in prices
        for currency in currencies
        if _offer_evidence_compatible(price, currency)
    ]
    if not pairs:
        return None
    price, currency = min(pairs, key=lambda pair: (rank(pair[0]), rank(pair[1])))
    return {
        price_fact: (price.evidence_id,),
        currency_fact: (currency.evidence_id,),
    }


def _admissible_offer_evidence(
    evidence_ids: tuple[str, ...],
    evidence_by_id: dict[str, Evidence],
    *,
    blocking: set[str],
) -> tuple[Evidence, ...]:
    return tuple(
        row
        for evidence_id in evidence_ids
        if evidence_id in evidence_by_id
        for row in (evidence_by_id[evidence_id],)
        if row.evidence_id not in blocking and _invalidity_reason(row) is None
    )


def _offer_evidence_compatible(price: Evidence, currency: Evidence) -> bool:
    if price.group_id and price.group_id == currency.group_id:
        return True
    if (
        price.parent_subject_id
        and price.parent_subject_id == currency.parent_subject_id
        and price.relation_type == currency.relation_type
    ):
        return True
    return (
        price.artifact_id == currency.artifact_id
        and price.collector_id == currency.collector_id
        and price.subject_id == currency.subject_id
    )


def _offer_atomic_unresolved_decision(
    offer: OfferEntity,
    fact_type: str,
    ids: tuple[str, ...],
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> Decision:
    candidates = tuple(evidence_by_id[eid] for eid in ids if eid in evidence_by_id)
    return Decision(
        decision_id=stable_id("decision", offer.entity_id, fact_type, "atomic_group"),
        entity_id=offer.entity_id,
        fact_type=fact_type,
        accepted_evidence_ids=(),
        rejected=tuple(
            RejectedEvidence(
                evidence_id=row.evidence_id,
                reason="offer_atomic_group_incompatible",
            )
            for row in candidates
        ),
        finding_ids=tuple(
            f.finding_id for f in findings if set(f.evidence_ids) & set(ids)
        ),
        rule_id="OFFER_ATOMIC_PRICE_CURRENCY",
        status="unresolved",
    )


def _preferred_parent_offer_id(
    entities: EntitySet,
    decisions: list[Decision],
    evidence_by_id: dict[str, Evidence],
) -> str | None:
    resolved = {
        (decision.entity_id, decision.fact_type): decision
        for decision in decisions
        if decision.status == "resolved" and decision.accepted_evidence_ids
    }
    source_priority = {
        collector_id: index
        for index, collector_id in enumerate(DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY)
    }

    def score(offer: OfferEntity) -> tuple[int, int, int, int, int, str]:
        price = resolved.get((offer.entity_id, field_mappings.OFFER_PRICE_FACT_TYPE))
        currency = resolved.get(
            (offer.entity_id, field_mappings.OFFER_CURRENCY_FACT_TYPE)
        )
        availability = resolved.get(
            (offer.entity_id, field_mappings.OFFER_AVAILABILITY_FACT_TYPE)
        )
        pair = tuple(
            evidence_by_id[decision.accepted_evidence_ids[0]]
            for decision in (price, currency)
            if decision is not None
            and decision.accepted_evidence_ids[0] in evidence_by_id
        )
        collectors = {row.collector_id for row in pair}
        complete = price is not None and currency is not None
        source_rank = max(
            (
                source_priority.get(row.collector_id, len(source_priority))
                for row in pair
            ),
            default=len(source_priority) + 1,
        )
        resolved_fact_count = sum(
            (offer.entity_id, fact_type) in resolved
            for fact_type in offer.fact_evidence
        )
        return (
            0 if complete else 1,
            0 if len(collectors) == 1 and pair else 1,
            source_rank,
            0 if availability is not None else 1,
            -resolved_fact_count,
            offer.entity_id,
        )

    parents = tuple(
        offer for offer in entities.offers if offer.variant_entity_id is None
    )
    return min(parents, key=score).entity_id if parents else None
