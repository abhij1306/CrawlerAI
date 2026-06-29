from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.extraction.contracts import (
    CollectorOutcome,
    Decision,
    Evidence,
    ExtractionMetrics,
    ExtractionResult,
    FieldEvidenceState,
    RejectedEvidence,
    SourceLocator,
    StageOutcome,
)
from app.extraction.surfaces import Surface
from app.observability.diagnose import SCHEMA_VERSION, build_diagnosis

pytestmark = pytest.mark.unit


def _evidence(evidence_id: str, *, value: object, collector_id: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bundle_id="bundle-1",
        artifact_id="artifact-1",
        collector_id=collector_id,
        collector_version="1",
        fact_type="offer.price",
        raw_value=value,
        value=value,
        locator=SourceLocator(
            kind="json_pointer", value="/offers/0/price", preview="$19.99"
        ),
        directness="direct",
        confidence=0.9,
        subject_id="offer-1",
    )


def _acquisition() -> SimpleNamespace:
    return SimpleNamespace(
        final_url="https://example.test/p",
        method="httpx",
        status_code=200,
        blocked=False,
        platform_family="shopify",
        browser_diagnostics={
            "browser_outcome": "not_attempted",
            "failure_reason": None,
        },
        acquisition_diagnostics={"result": {"failure_reason": "rate_limited"}},
    )


def _result(**overrides: object) -> ExtractionResult:
    base: dict[str, object] = {
        "surface": Surface.ECOMMERCE_DETAIL,
        "records": (),
        "verdict": "success",
    }
    base.update(overrides)
    return ExtractionResult(**base)  # type: ignore[arg-type]


def test_build_diagnosis_emits_schema_and_top_level_sections() -> None:
    result = _result(
        verdict="partial",
        data_integrity="partial",
        metrics=ExtractionMetrics(evidence_count=2, collector_count=1),
    )

    diagnosis = build_diagnosis(
        acquisition_result=_acquisition(),
        extraction_result=result,
    )

    assert diagnosis["schema_version"] == SCHEMA_VERSION
    assert diagnosis["verdict"] == "partial"
    assert diagnosis["data_integrity"] == "partial"
    assert diagnosis["metrics"]["evidence_count"] == 2
    assert diagnosis["contract_outcomes"] is None
    assert diagnosis["variants"] == {"dropped": []}


def test_acquisition_section_summarizes_transport() -> None:
    diagnosis = build_diagnosis(
        acquisition_result=_acquisition(),
        extraction_result=_result(),
    )

    acquisition = diagnosis["acquisition"]
    assert acquisition["final_url"] == "https://example.test/p"
    assert acquisition["method"] == "httpx"
    assert acquisition["status_code"] == 200
    assert acquisition["blocked"] is False
    assert acquisition["platform_family"] == "shopify"
    assert acquisition["browser_outcome"] == "not_attempted"
    # falls back to acquisition_diagnostics.result when browser reason is empty
    assert acquisition["failure_reason"] == "rate_limited"


def test_field_section_carries_winner_and_rejected_with_evidence() -> None:
    winner = _evidence("ev-win", value="19.99", collector_id="jsonld")
    loser = _evidence("ev-lose", value="0.00", collector_id="regex")
    decision = Decision(
        decision_id="d1",
        entity_id="offer-1",
        fact_type="offer.price",
        accepted_evidence_ids=("ev-win",),
        rejected=(RejectedEvidence(evidence_id="ev-lose", reason="lower_priority"),),
        finding_ids=(),
        rule_id="OFFER_PRICE",
        status="resolved",
    )
    result = _result(
        evidence=(winner, loser),
        decisions=(decision,),
        field_states=(
            FieldEvidenceState(field="price", state="captured_and_resolved"),
        ),
    )

    diagnosis = build_diagnosis(
        acquisition_result=_acquisition(),
        extraction_result=result,
    )

    field = diagnosis["fields"][0]
    assert field["field"] == "price"
    assert field["status"] == "captured_and_resolved"
    assert field["winner"]["collector_id"] == "jsonld"
    assert field["winner"]["value"] == "19.99"
    assert field["winner"]["rule_id"] == "OFFER_PRICE"
    assert field["rejected"][0]["reason"] == "lower_priority"
    assert field["rejected"][0]["collector_id"] == "regex"


def test_field_section_includes_firewall_reason_and_reason_codes() -> None:
    result = _result(
        field_states=(
            FieldEvidenceState(
                field="currency",
                state="captured_but_rejected",
                reason_codes=("ambiguous_currency",),
            ),
        ),
    )

    diagnosis = build_diagnosis(
        acquisition_result=_acquisition(),
        extraction_result=result,
        rejected_public_fields={"currency": "FAILED_ISO_4217"},
    )

    field = diagnosis["fields"][0]
    assert field["reason_codes"] == ["ambiguous_currency"]
    assert field["firewall"] == "FAILED_ISO_4217"
    assert "winner" not in field


def test_decisions_mapped_by_trailing_segment_prefers_resolved() -> None:
    winner = _evidence("ev-win", value="42.00", collector_id="jsonld")
    unresolved = Decision(
        decision_id="d-unresolved",
        entity_id="offer-1",
        fact_type="offer.price",
        accepted_evidence_ids=(),
        rejected=(),
        finding_ids=(),
        rule_id="OFFER_PRICE",
        status="unresolved",
    )
    resolved = Decision(
        decision_id="d-resolved",
        entity_id="offer-1",
        fact_type="offer.price",
        accepted_evidence_ids=("ev-win",),
        rejected=(),
        finding_ids=(),
        rule_id="OFFER_PRICE",
        status="resolved",
    )
    result = _result(
        evidence=(winner,),
        # unresolved first; resolved must still win the mapping
        decisions=(unresolved, resolved),
        field_states=(
            FieldEvidenceState(field="price", state="captured_and_resolved"),
        ),
    )

    diagnosis = build_diagnosis(
        acquisition_result=_acquisition(),
        extraction_result=result,
    )

    assert diagnosis["fields"][0]["winner"]["value"] == "42.00"


def test_variant_drops_and_outcomes_passed_through() -> None:
    result = _result(
        collector_outcomes=(
            CollectorOutcome(
                collector_id="jsonld", outcome="produced_evidence", evidence_count=3
            ),
        ),
        stage_outcomes=(StageOutcome(stage="collect", outcome="ran"),),
    )

    diagnosis = build_diagnosis(
        acquisition_result=_acquisition(),
        extraction_result=result,
        variant_drops=[
            {"row": "SKU-1", "stage": "firewall", "rule": "PRICE", "reason": "no_price"}
        ],
    )

    assert diagnosis["variants"]["dropped"][0]["row"] == "SKU-1"
    assert diagnosis["collectors"][0]["collector_id"] == "jsonld"
    assert diagnosis["collectors"][0]["evidence_count"] == 3
    assert diagnosis["stages"][0]["stage"] == "collect"


def test_long_values_are_preview_truncated() -> None:
    long_value = "x" * 500
    winner = _evidence("ev-win", value=long_value, collector_id="jsonld")
    decision = Decision(
        decision_id="d1",
        entity_id="offer-1",
        fact_type="offer.price",
        accepted_evidence_ids=("ev-win",),
        rejected=(),
        finding_ids=(),
        rule_id="OFFER_PRICE",
        status="resolved",
    )
    result = _result(
        evidence=(winner,),
        decisions=(decision,),
        field_states=(
            FieldEvidenceState(field="price", state="captured_and_resolved"),
        ),
    )

    diagnosis = build_diagnosis(
        acquisition_result=_acquisition(),
        extraction_result=result,
    )

    preview = diagnosis["fields"][0]["winner"]["value"]
    assert len(preview) <= 120
    assert preview.endswith("…")
