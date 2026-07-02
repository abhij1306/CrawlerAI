from __future__ import annotations

from app.core.config import field_mappings
from app.core.config.extraction_price_rules import (
    DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY,
    DETAIL_PRICE_PAGE_CORROBORATION_COLLECTORS,
)
from app.core.shared.field_coerce_price import repair_price_unit
from app.core.shared.ids import stable_id
from app.extraction.contracts import Decision, DerivedFact, Evidence
from app.extraction.entities import EntitySet


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
    currency_rows_by_offer = {
        offer.entity_id: tuple(
            by_id[evidence_id]
            for evidence_id in offer.fact_evidence.get(
                field_mappings.OFFER_CURRENCY_FACT_TYPE, ()
            )
            if evidence_id in by_id
            and "invalid_currency" not in by_id[evidence_id].flags
        )
        for offer in entities.offers
    }
    product_currency_rows = {
        product.entity_id: tuple(
            row
            for offer in entities.offers
            if offer.product_entity_id == product.entity_id
            for row in currency_rows_by_offer.get(offer.entity_id, ())
        )
        for product in entities.products
    }
    price_rows = tuple(
        row
        for row in evidence
        if row.fact_type
        in {
            field_mappings.OFFER_PRICE_FACT_TYPE,
            field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
        }
    )
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
    peer_values: dict[str, object] = {}
    for row in price_rows:
        repaired = repair_price_unit(
            row.value,
            source_key=row.locator.value,
            currency=currency_by_evidence.get(row.evidence_id, ""),
        )
        peer_values[row.evidence_id] = repaired[0] if repaired else row.value
    repairs: dict[str, tuple[object, str, tuple[str, ...]]] = {}
    for row in price_rows:
        offer = offer_by_evidence.get(row.evidence_id)
        currency = currency_by_evidence.get(row.evidence_id)
        if offer is None or currency is None:
            continue
        peers = tuple(
            other
            for other in price_rows
            if other.evidence_id != row.evidence_id
            and other.fact_type == row.fact_type
            and (
                (
                    (other_offer := offer_by_evidence.get(other.evidence_id))
                    is not None
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
        repaired = repair_price_unit(
            row.value,
            source_key=row.locator.value,
            currency=currency,
            corroborating_values=tuple(
                peer_values[other.evidence_id] for other in peers
            ),
        )
        if repaired is not None:
            value, rule_id = repaired
            repairs[row.evidence_id] = (
                value,
                rule_id,
                tuple(other.evidence_id for other in peers),
            )
    return repairs


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
