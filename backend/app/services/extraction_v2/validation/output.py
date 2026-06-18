from __future__ import annotations

from app.services.extraction_v2.contracts import Evidence, Finding
from app.services.extraction_v2.entities.contracts import EntitySet
from app.services.extraction_v2.validation.identity import finding


def validate_output(evidence: tuple[Evidence, ...], entities: EntitySet) -> tuple[Finding, ...]:
    if not entities.products:
        return ()
    product = entities.products[0]
    has_title = bool(product.attribute_evidence.get("product.title"))
    has_url = bool(product.attribute_evidence.get("product.url"))
    if not has_title or not has_url:
        ids = tuple(sorted(set(product.attribute_evidence.get("product.title", ()) + product.attribute_evidence.get("product.url", ()))))
        return (finding("INSUFFICIENT_PRODUCT_KNOWLEDGE", (product.entity_id,), ids, "Product lacks title or URL.", False),)
    return ()
