from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation

from app.core.config.field_mappings import (
    ECOMMERCE_DETAIL_FIELD_FACT_TYPES,
    SURFACE_FIELD_REPAIR_TARGETS,
)
from app.extraction.contracts import Evidence, Finding
from app.extraction.entities import EntitySet
from app.extraction.ids import stable_id


def validate(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    requested_fields: tuple[str, ...] = (),
) -> tuple[Finding, ...]:
    return (
        *_validate_identity(evidence, entities),
        *_validate_variants(entities),
        *_validate_offers(evidence, entities),
        *_validate_availability_consistency(evidence, entities),
        *_validate_contract_fields(evidence, requested_fields),
        *_validate_output(entities),
    )


def _validate_contract_fields(
    evidence: tuple[Evidence, ...],
    requested_fields: tuple[str, ...],
) -> tuple[Finding, ...]:
    contract_fields = tuple(
        dict.fromkeys(
            (*SURFACE_FIELD_REPAIR_TARGETS.get("ecommerce_detail", ()), *requested_fields)
        )
    )
    facts = {ev.fact_type for ev in evidence if ev.value not in (None, "", [], {})}
    findings: list[Finding] = []
    for field in contract_fields:
        fact_type = ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(field)
        present = fact_type in facts if fact_type else field == "variants" and any(
            fact.startswith("variant.") for fact in facts
        )
        if present:
            continue
        findings.append(
            _finding(
                "MISSING_CONTRACT_FIELD",
                (),
                (),
                f"No admissible evidence for contract field {field!r}.",
                False,
                metadata={"field": field},
            )
        )
    return tuple(findings)


def _validate_identity(evidence: tuple[Evidence, ...], entities: EntitySet) -> tuple[Finding, ...]:
    if not entities.products:
        ids = tuple(sorted(ev.evidence_id for ev in evidence if ev.fact_type.startswith("product.")))
        return (_finding("MISSING_PRODUCT_IDENTITY", (), ids, "No primary product entity.", True),)
    if len(entities.products) > 1:
        return (
            _finding(
                "PRIMARY_PRODUCT_AMBIGUOUS",
                tuple(p.entity_id for p in entities.products),
                (),
                "Primary product ambiguous.",
                True,
            ),
        )
    return ()


def _validate_variants(entities: EntitySet) -> tuple[Finding, ...]:
    keys = [variant.identity_key for variant in entities.variants]
    if any(count > 1 for count in Counter(keys).values()):
        return (
            _finding(
                "DUPLICATE_VARIANT_IDENTITY",
                tuple(v.entity_id for v in entities.variants),
                (),
                "Duplicate variant identity.",
                True,
            ),
        )
    return ()


def _validate_offers(evidence: tuple[Evidence, ...], entities: EntitySet) -> tuple[Finding, ...]:
    by_id = {ev.evidence_id: ev for ev in evidence}
    out: list[Finding] = []
    for offer in entities.offers:
        has_price = bool(offer.fact_evidence.get("offer.price"))
        has_currency = bool(offer.fact_evidence.get("offer.currency"))
        if has_price and not has_currency:
            out.append(
                _finding(
                    "PRICE_WITHOUT_CURRENCY",
                    (offer.entity_id,),
                    offer.fact_evidence.get("offer.price", ()),
                    "Offer price lacks currency.",
                    False,
                )
            )
        if has_currency and not has_price:
            out.append(
                _finding(
                    "CURRENCY_WITHOUT_PRICE",
                    (offer.entity_id,),
                    offer.fact_evidence.get("offer.currency", ()),
                    "Offer currency lacks price.",
                    False,
                )
            )
        current = _decimal(offer.fact_evidence.get("offer.price", ()), by_id)
        original = _decimal(offer.fact_evidence.get("offer.original_price", ()), by_id)
        if current is not None and original is not None and original < current:
            out.append(
                _finding(
                    "INVALID_ORIGINAL_PRICE",
                    (offer.entity_id,),
                    offer.fact_evidence.get("offer.original_price", ()),
                    "Original price below current price.",
                    True,
                )
            )
    return tuple(out)


def _validate_availability_consistency(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
) -> tuple[Finding, ...]:
    by_id = {ev.evidence_id: ev for ev in evidence}
    parent_offers = [offer for offer in entities.offers if offer.variant_entity_id is None]
    variant_offers = [offer for offer in entities.offers if offer.variant_entity_id is not None]
    if not entities.variants or not parent_offers or len(variant_offers) < len(entities.variants):
        return ()
    child_ids = [
        offer.fact_evidence.get("offer.availability", ())
        for offer in variant_offers
    ]
    if any(not ids for ids in child_ids):
        return ()
    child_values = [str(by_id[ids[0]].value) for ids in child_ids if ids[0] in by_id]
    if len(child_values) != len(variant_offers):
        return ()
    aggregate = "in_stock" if "in_stock" in child_values else "out_of_stock"
    parent_ids = parent_offers[0].fact_evidence.get("offer.availability", ())
    if not parent_ids or parent_ids[0] not in by_id or str(by_id[parent_ids[0]].value) == aggregate:
        return ()
    evidence_ids = tuple(parent_ids) + tuple(eid for ids in child_ids for eid in ids)
    return (
        _finding(
            "PARENT_VARIANT_AVAILABILITY_CONFLICT",
            (parent_offers[0].entity_id,),
            evidence_ids,
            "Parent availability conflicts with the complete variant matrix.",
            False,
        ),
    )


def _validate_output(entities: EntitySet) -> tuple[Finding, ...]:
    if not entities.products:
        return ()
    product = entities.products[0]
    has_title = bool(product.attribute_evidence.get("product.title"))
    has_url = bool(product.attribute_evidence.get("product.url"))
    if not has_title or not has_url:
        ids = tuple(
            sorted(
                set(
                    product.attribute_evidence.get("product.title", ())
                    + product.attribute_evidence.get("product.url", ())
                )
            )
        )
        return (
            _finding(
                "INSUFFICIENT_PRODUCT_KNOWLEDGE",
                (product.entity_id,),
                ids,
                "Product lacks title or URL.",
                False,
            ),
        )
    return ()


def _decimal(ids: tuple[str, ...] | None, by_id: dict[str, Evidence]) -> Decimal | None:
    if not ids:
        return None
    try:
        return Decimal(str(by_id[ids[0]].value))
    except (KeyError, InvalidOperation, ValueError):
        return None


def _finding(
    rule: str,
    entity_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    message: str,
    blocking: bool,
    metadata: dict[str, object] | None = None,
) -> Finding:
    return Finding(
        finding_id=stable_id("finding", rule, entity_ids, evidence_ids),
        rule_id=rule,
        severity="high" if blocking else "medium",
        scope="selected_entity" if entity_ids else "page",
        entity_ids=entity_ids,
        evidence_ids=evidence_ids,
        message=message,
        blocking=blocking,
        metadata=metadata or {},
    )
