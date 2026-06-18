from __future__ import annotations

from app.services.extraction_v2.contracts import Evidence, Finding
from app.services.extraction_v2.entities.contracts import EntitySet
from app.services.extraction_v2.validation.identity import validate_identity
from app.services.extraction_v2.validation.offers import validate_offers
from app.services.extraction_v2.validation.output import validate_output
from app.services.extraction_v2.validation.variants import validate_variants


def validate(evidence: tuple[Evidence, ...], entities: EntitySet) -> tuple[Finding, ...]:
    return (
        *validate_identity(evidence, entities),
        *validate_variants(evidence, entities),
        *validate_offers(evidence, entities),
        *validate_output(evidence, entities),
    )
