from __future__ import annotations

from collections import Counter

from app.services.extraction_v2.contracts import Evidence, Finding
from app.services.extraction_v2.entities.contracts import EntitySet
from app.services.extraction_v2.validation.identity import finding


def validate_variants(evidence: tuple[Evidence, ...], entities: EntitySet) -> tuple[Finding, ...]:
    keys = [variant.identity_key for variant in entities.variants]
    if any(count > 1 for count in Counter(keys).values()):
        return (finding("DUPLICATE_VARIANT_IDENTITY", tuple(v.entity_id for v in entities.variants), (), "Duplicate variant identity.", True),)
    return ()
