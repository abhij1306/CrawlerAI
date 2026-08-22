from __future__ import annotations

from app.core.config import field_mappings
from app.core.config.extraction_price_rules import (
    DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY,
    DETAIL_PRICE_PAGE_CORROBORATION_COLLECTORS,
)
from app.core.shared.field_coerce_price import repair_price_unit
from app.core.shared.ids import stable_id
from app.extraction.contracts import Decision, DerivedFact, Evidence
from app.extraction.entities import EntitySet, OfferEntity


def _price_unit_repairs(
    evidence: tuple[Evidence, ...], entities: EntitySet
) -> dict[str, tuple[object, str, tuple[str, ...]]]:
    by_id = {row.evidence_id: row for row in evidence}
    offer_by_evidence = {
        evidence_id: offer
        for offer in entities.offers
        for ids in offer.fact_evidence.values()
        for evidence_id in ids
    }
    currency_rows_by_offer = _currency_rows_by_offer(entities, by_id)
    product_currency_rows = _currency_rows_by_product(entities, currency_rows_by_offer)
    price_rows = _price_rows(evidence)
    currency_by_evidence = _price_currencies(
        price_rows,
        offer_by_evidence,
        currency_rows_by_offer,
        product_currency_rows,
    )
    peer_values = _peer_price_values(price_rows, currency_by_evidence)
    repairs: dict[str, tuple[object, str, tuple[str, ...]]] = {}
    for row in price_rows:
        repaired = _corroborated_price_repair(
            row,
            price_rows,
            offer_by_evidence,
            currency_by_evidence,
            peer_values,
        )
        if repaired is not None:
            repairs[row.evidence_id] = repaired
    return repairs


def _currency_rows_by_offer(
    entities: EntitySet, evidence_by_id: dict[str, Evidence]
) -> dict[str, tuple[Evidence, ...]]:
    return {
        offer.entity_id: tuple(
            evidence_by_id[evidence_id]
            for evidence_id in offer.fact_evidence.get(
                field_mappings.OFFER_CURRENCY_FACT_TYPE, ()
            )
            if evidence_id in evidence_by_id
            and "invalid_currency" not in evidence_by_id[evidence_id].flags
        )
        for offer in entities.offers
    }


def _currency_rows_by_product(
    entities: EntitySet,
    currency_rows_by_offer: dict[str, tuple[Evidence, ...]],
) -> dict[str, tuple[Evidence, ...]]:
    return {
        product.entity_id: tuple(
            row
            for offer in entities.offers
            if offer.product_entity_id == product.entity_id
            for row in currency_rows_by_offer.get(offer.entity_id, ())
        )
        for product in entities.products
    }


def _price_rows(evidence: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    return tuple(
        row
        for row in evidence
        if row.fact_type
        in {
            field_mappings.OFFER_PRICE_FACT_TYPE,
            field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
        }
    )


def _price_currencies(
    price_rows: tuple[Evidence, ...],
    offer_by_evidence: dict[str, OfferEntity],
    currency_rows_by_offer: dict[str, tuple[Evidence, ...]],
    product_currency_rows: dict[str, tuple[Evidence, ...]],
) -> dict[str, str]:
    currency_by_evidence: dict[str, str] = {}
    for row in price_rows:
        offer = offer_by_evidence.get(row.evidence_id)
        if offer is None:
            continue
        currency = _preferred_price_currency(
            currency_rows_by_offer.get(offer.entity_id, ())
        ) or _preferred_price_currency(
            product_currency_rows.get(offer.product_entity_id, ())
        )
        if currency:
            currency_by_evidence[row.evidence_id] = currency
    return currency_by_evidence


def _peer_price_values(
    price_rows: tuple[Evidence, ...], currency_by_evidence: dict[str, str]
) -> dict[str, object]:
    peer_values: dict[str, object] = {}
    for row in price_rows:
        repaired = repair_price_unit(
            row.value,
            source_key=row.locator.value,
            currency=currency_by_evidence.get(row.evidence_id, ""),
        )
        peer_values[row.evidence_id] = repaired[0] if repaired else row.value
    return peer_values


def _corroborated_price_repair(
    row: Evidence,
    price_rows: tuple[Evidence, ...],
    offer_by_evidence: dict[str, OfferEntity],
    currency_by_evidence: dict[str, str],
    peer_values: dict[str, object],
) -> tuple[object, str, tuple[str, ...]] | None:
    offer = offer_by_evidence.get(row.evidence_id)
    currency = currency_by_evidence.get(row.evidence_id)
    if offer is None or currency is None:
        return None
    peers = _corroborating_price_rows(
        row,
        price_rows,
        offer,
        offer_by_evidence,
    )
    repaired = repair_price_unit(
        row.value,
        source_key=row.locator.value,
        currency=currency,
        corroborating_values=tuple(peer_values[other.evidence_id] for other in peers),
    )
    if repaired is None:
        return None
    value, rule_id = repaired
    return value, rule_id, tuple(other.evidence_id for other in peers)


def _corroborating_price_rows(
    row: Evidence,
    price_rows: tuple[Evidence, ...],
    offer: OfferEntity,
    offer_by_evidence: dict[str, OfferEntity],
) -> tuple[Evidence, ...]:
    return tuple(
        other
        for other in price_rows
        if other.evidence_id != row.evidence_id
        and other.fact_type == row.fact_type
        and (
            (
                (other_offer := offer_by_evidence.get(other.evidence_id)) is not None
                and other_offer.product_entity_id == offer.product_entity_id
                and (
                    other.collector_id != row.collector_id
                    or other_offer.entity_id == offer.entity_id
                )
            )
            or (
                offer_by_evidence.get(other.evidence_id) is None
                and other.collector_id in DETAIL_PRICE_PAGE_CORROBORATION_COLLECTORS
                and "invalid_decimal" not in other.flags
            )
        )
    )


def _price_unit_derived_facts(
    decisions: tuple[Decision, ...],
    evidence_by_id: dict[str, Evidence],
    repairs: dict[str, tuple[object, str, tuple[str, ...]]],
) -> tuple[DerivedFact, ...]:
    facts: list[DerivedFact] = []
    for decision in decisions:
        if not decision.accepted_evidence_ids:
            continue
        evidence_id = decision.accepted_evidence_ids[0]
        repaired = repairs.get(evidence_id)
        evidence = evidence_by_id.get(evidence_id)
        if repaired is None or evidence is None or repaired[0] == evidence.value:
            continue
        value, rule_id, peer_ids = repaired
        facts.append(
            DerivedFact(
                derived_fact_id=stable_id(
                    "derived", rule_id, decision.entity_id, decision.fact_type, value
                ),
                entity_id=decision.entity_id,
                fact_type=decision.fact_type,
                value=value,
                input_evidence_ids=tuple(dict.fromkeys((evidence_id, *peer_ids))),
                input_selected_fact_ids=(stable_id("selected", decision.decision_id),),
                rule_id=rule_id,
            )
        )
    return tuple(facts)


def _preferred_price_currency(rows: tuple[Evidence, ...]) -> str | None:
    priority = {
        collector_id: index
        for index, collector_id in enumerate(DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY)
    }
    valid = tuple(
        row
        for row in rows
        if str(row.value or "").strip() and "invalid_currency" not in row.flags
    )
    if not valid:
        return None
    best_rank = min(priority.get(row.collector_id, len(priority)) for row in valid)
    values = {
        str(row.value).strip().upper()
        for row in valid
        if priority.get(row.collector_id, len(priority)) == best_rank
    }
    return next(iter(values)) if len(values) == 1 else None
