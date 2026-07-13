from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.extraction.contracts import (
    CommerceDetailProjection,
    DerivedFact,
    EvidenceDisposition,
    PublicationEntry,
    ResolutionEnvelope,
    SelectedFact,
)
from app.extraction.surfaces import Surface

pytestmark = pytest.mark.unit


def test_publication_value_requires_one_fact_source() -> None:
    with pytest.raises(ValidationError, match="published entries require"):
        PublicationEntry(path="record.price", entity_id="product:1")

    with pytest.raises(ValidationError, match="exactly one"):
        PublicationEntry(
            path="record.price",
            entity_id="product:1",
            value="19.99",
        )

    with pytest.raises(ValidationError, match="multiple"):
        PublicationEntry(
            path="record.price",
            entity_id="product:1",
            value="19.99",
            selected_fact_id="selected:price",
            derived_fact_id="derived:price",
        )


def test_resolution_envelope_keeps_surface_specific_projection() -> None:
    projection = CommerceDetailProjection(record_entity_id="product:1")
    envelope = ResolutionEnvelope(
        surface=Surface.ECOMMERCE_DETAIL,
        publication=projection,
    )

    assert isinstance(envelope.publication, CommerceDetailProjection)
    assert envelope.publication.record_entity_id == "product:1"


def test_selected_and_derived_facts_keep_atomic_provenance() -> None:
    selected = SelectedFact(
        selected_fact_id="selected:price",
        decision_id="decision:price",
        entity_id="offer:1",
        fact_type="offer.price",
        value="19.99",
        evidence_ids=("evidence:price",),
        rule_id="SCALAR_LEXICOGRAPHIC",
    )
    derived = DerivedFact(
        derived_fact_id="derived:price",
        entity_id="offer:1",
        fact_type="offer.price",
        value="19.99",
        input_evidence_ids=("evidence:price",),
        input_selected_fact_ids=(selected.selected_fact_id,),
        rule_id="NORMALIZE_MONEY_PRECISION",
    )

    assert derived.input_selected_fact_ids == ("selected:price",)
    assert derived.input_evidence_ids == ("evidence:price",)


def test_evidence_disposition_is_terminal_and_typed() -> None:
    disposition = EvidenceDisposition(
        evidence_id="evidence:price",
        entity_id="offer:1",
        status="accepted",
        reason_code="selected",
        selected_fact_id="selected:price",
    )

    assert disposition.status == "accepted"
    with pytest.raises(ValidationError, match="Input should be") as exc_info:
        EvidenceDisposition(
            evidence_id="evidence:price",
            entity_id="offer:1",
            status="dropped",  # type: ignore[arg-type]
            reason_code="unknown",
            decision_id="decision:price",
            selected_fact_id="selected:price",
        )
    assert exc_info.value.errors()[0]["loc"] == ("status",)
