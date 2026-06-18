from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.services.extraction_v2.contracts import Evidence, Finding
from app.services.extraction_v2.entities.contracts import EntitySet
from app.services.extraction_v2.validation.identity import finding


def validate_offers(evidence: tuple[Evidence, ...], entities: EntitySet) -> tuple[Finding, ...]:
    by_id = {ev.evidence_id: ev for ev in evidence}
    out: list[Finding] = []
    for offer in entities.offers:
        has_price = bool(offer.fact_evidence.get("offer.price"))
        has_currency = bool(offer.fact_evidence.get("offer.currency"))
        if has_price and not has_currency:
            out.append(finding("PRICE_WITHOUT_CURRENCY", (offer.entity_id,), offer.fact_evidence.get("offer.price", ()), "Offer price lacks currency.", True))
        if has_currency and not has_price:
            out.append(finding("CURRENCY_WITHOUT_PRICE", (offer.entity_id,), offer.fact_evidence.get("offer.currency", ()), "Offer currency lacks price.", True))
        current = _decimal(offer.fact_evidence.get("offer.price", ()), by_id)
        original = _decimal(offer.fact_evidence.get("offer.original_price", ()), by_id)
        if current is not None and original is not None and original < current:
            out.append(finding("INVALID_ORIGINAL_PRICE", (offer.entity_id,), offer.fact_evidence.get("offer.original_price", ()), "Original price below current price.", True))
    return tuple(out)


def _decimal(ids: tuple[str, ...] | None, by_id: dict[str, Evidence]) -> Decimal | None:
    if not ids:
        return None
    try:
        return Decimal(str(by_id[ids[0]].value))
    except (KeyError, InvalidOperation, ValueError):
        return None
