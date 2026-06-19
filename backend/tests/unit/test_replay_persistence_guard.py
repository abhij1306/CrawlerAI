from __future__ import annotations

import pytest

from app.services.pipeline.extraction_loop import _success_has_replay_lineage
from app.services.pipeline.persistence import build_extraction_decision_payload


pytestmark = pytest.mark.unit


def test_success_guard_requires_replay_evidence_decisions_and_lineage() -> None:
    acquisition_result = type(
        "AcquisitionResult",
        (),
        {
            "artifacts": {
                "extraction_replay": {
                    "evidence": [{"evidence_id": "ev_1"}],
                    "decisions": [{"decision_id": "dec_1"}],
                }
            }
        },
    )()

    assert _success_has_replay_lineage(
        acquisition_result,
        [{"title": "Trail Shoe", "_lineage": {"title": {"decision_id": "dec_1"}}}],
    )
    assert not _success_has_replay_lineage(
        acquisition_result,
        [{"title": "Trail Shoe"}],
    )
    acquisition_result.artifacts["extraction_replay"]["decisions"] = []
    assert not _success_has_replay_lineage(
        acquisition_result,
        [{"title": "Trail Shoe", "_lineage": {"title": {"decision_id": "dec_1"}}}],
    )


def test_extraction_decision_payload_contains_replay_counts() -> None:
    payload = build_extraction_decision_payload(
        verdict="success",
        persisted_count=1,
        records=[{"title": "Trail Shoe", "_lineage": {"title": {"decision_id": "dec_1"}}}],
        replay={
            "surface": "ecommerce_detail",
            "verdict": "success",
            "evidence": [{"evidence_id": "ev_1"}],
            "decisions": [{"decision_id": "dec_1"}],
            "findings": [],
        },
    )

    assert payload["replay"] == {
        "surface": "ecommerce_detail",
        "verdict": "success",
        "evidence_count": 1,
        "decision_count": 1,
        "finding_count": 0,
    }
