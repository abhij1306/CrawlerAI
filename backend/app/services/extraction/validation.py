from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation

from app.services.extraction.contracts import Evidence, Finding
from app.services.extraction.entities import EntitySet
from app.services.extraction.ids import stable_id


def validate(evidence: tuple[Evidence, ...], entities: EntitySet) -> tuple[Finding, ...]:
    return (
        *_validate_identity(evidence, entities),
        *_validate_variants(entities),
        *_validate_offers(evidence, entities),
        *_validate_output(entities),
    )


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
                    True,
                )
            )
        if has_currency and not has_price:
            out.append(
                _finding(
                    "CURRENCY_WITHOUT_PRICE",
                    (offer.entity_id,),
                    offer.fact_evidence.get("offer.currency", ()),
                    "Offer currency lacks price.",
                    True,
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
) -> Finding:
    return Finding(
        finding_id=stable_id("finding", rule, entity_ids, evidence_ids),
        rule_id=rule,
        severity="high" if blocking else "medium",
        entity_ids=entity_ids,
        evidence_ids=evidence_ids,
        message=message,
        blocking=blocking,
    )
