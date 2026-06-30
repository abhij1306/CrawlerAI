from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.extraction.contracts import (
    CommerceDetailProjection,
    Decision,
    DerivedFact,
    Evidence,
    EvidenceDisposition,
    PublicationEntry,
    RejectedEvidence,
    ResolutionEnvelope,
    SelectedFact,
    SourceLocator,
    TargetSelection,
)
from app.extraction.result_building import (
    assert_resolution_accounting,
    evidence_dispositions,
    selected_facts,
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


def test_current_resolution_adapter_conserves_every_evidence_row() -> None:
    evidence = tuple(
        _evidence(f"evidence:{index}", value)
        for index, value in enumerate(("A", "B", "C"))
    )
    decision = Decision(
        decision_id="decision:title",
        entity_id="product:1",
        fact_type="product.title",
        accepted_evidence_ids=("evidence:0",),
        rejected=(
            RejectedEvidence(evidence_id="evidence:1", reason="lower_confidence"),
        ),
        finding_ids=(),
        rule_id="SCALAR_LEXICOGRAPHIC",
        status="resolved",
    )

    facts = selected_facts((decision,), evidence)
    dispositions = evidence_dispositions(evidence, (decision,), facts)

    assert {row.evidence_id for row in dispositions} == {
        row.evidence_id for row in evidence
    }
    assert len(dispositions) == len(evidence)
    assert [row.status for row in dispositions] == [
        "accepted",
        "rejected_lower_rank",
        "diagnostic_only",
    ]
    assert facts[0].value == evidence[0].value


def test_evidence_disposition_marks_outside_selected_target() -> None:
    evidence = (
        _evidence("evidence:1", "Selected", subject_id="card:1"),
        _evidence("evidence:2", "Other", subject_id="card:2"),
    )
    decision = Decision(
        decision_id="decision:title",
        entity_id="card:1",
        fact_type="product.title",
        accepted_evidence_ids=("evidence:1",),
        rejected=(),
        finding_ids=(),
        rule_id="SCALAR_LEXICOGRAPHIC",
        status="resolved",
    )

    dispositions = evidence_dispositions(
        evidence,
        (decision,),
        selected_facts((decision,), evidence),
        TargetSelection(
            status="resolved",
            root_entity_ids=("card:1",),
            selected_root_entity_id="card:1",
        ),
    )

    assert {row.evidence_id: row.status for row in dispositions} == {
        "evidence:1": "accepted",
        "evidence:2": "outside_selected_target",
    }


def test_evidence_disposition_marks_unowned_when_target_unresolved() -> None:
    evidence = (_evidence("evidence:1", "Unknown", subject_id="card:1"),)

    dispositions = evidence_dispositions(
        evidence,
        (),
        (),
        TargetSelection(status="ambiguous", root_entity_ids=("card:1", "card:2")),
    )

    assert dispositions[0].status == "unowned"
    assert dispositions[0].reason_code == "target_ambiguous"


def test_resolution_accounting_rejects_missing_disposition() -> None:
    evidence = (_evidence("evidence:1", "Selected"),)

    with pytest.raises(RuntimeError, match="exactly one disposition"):
        assert_resolution_accounting(evidence, (), (), ())


def test_resolution_accounting_rejects_selected_fact_value_divergence() -> None:
    evidence = (_evidence("evidence:1", "Selected"),)
    decision = Decision(
        decision_id="decision:title",
        entity_id="product:1",
        fact_type="product.title",
        accepted_evidence_ids=("evidence:1",),
        rejected=(),
        finding_ids=(),
        rule_id="SCALAR_LEXICOGRAPHIC",
        status="resolved",
    )
    selected = SelectedFact(
        selected_fact_id="selected:title",
        decision_id="decision:title",
        entity_id="product:1",
        fact_type="product.title",
        value="Different",
        evidence_ids=("evidence:1",),
        rule_id="SCALAR_LEXICOGRAPHIC",
    )
    dispositions = evidence_dispositions(evidence, (decision,), (selected,))

    with pytest.raises(RuntimeError, match="diverges from accepted evidence"):
        assert_resolution_accounting(evidence, (decision,), (selected,), dispositions)


def _evidence(
    evidence_id: str, value: str, *, subject_id: str = "product:source"
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bundle_id="bundle:1",
        artifact_id="artifact:1",
        collector_id="jsonld",
        collector_version="1",
        fact_type="product.title",
        raw_value=value,
        value=value,
        locator=SourceLocator(kind="json_pointer", value=f"/{evidence_id}"),
        directness="embedded",
        confidence=0.9,
        subject_id=subject_id,
    )
