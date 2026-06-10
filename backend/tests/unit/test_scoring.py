from __future__ import annotations

import pytest

from app.services.config.aid_score import (
    D_AID1_ID,
    D_AID2_ID,
    D_AID3_ID,
    D_AID4_ID,
    D_AID5_ID,
    D_AID6_ID,
    DIMENSION_WEIGHTS,
)
from app.services.ucp_audit.scoring import build_compliance_report
from app.services.ucp_audit.types import UCPDimensionScore


def dimension(dimension_id: str, score: int) -> UCPDimensionScore:
    return UCPDimensionScore(
        dimension_id=dimension_id,
        score=score,
        status="pass",
        findings=[],
        weight=DIMENSION_WEIGHTS[dimension_id],
    )


@pytest.mark.unit
def test_dimension_weights_sum_to_one() -> None:
    assert round(sum(DIMENSION_WEIGHTS.values()), 6) == pytest.approx(1.0)


@pytest.mark.unit
def test_d_aid1_zero_caps_overall_score() -> None:
    report = build_compliance_report(
        domain="example.com",
        audit_id="audit-1",
        dimension_scores=[
            dimension(D_AID1_ID, 0),
            dimension(D_AID2_ID, 90),
            dimension(D_AID3_ID, 90),
            dimension(D_AID4_ID, 90),
            dimension(D_AID5_ID, 90),
            dimension(D_AID6_ID, 90),
        ],
        ucp_contract={},
    )

    assert report.overall_score <= 30
    assert report.d_ucp1_gate_applied is True


@pytest.mark.unit
def test_d_aid1_pass_uses_weighted_average() -> None:
    report = build_compliance_report(
        domain="example.com",
        audit_id="audit-1",
        dimension_scores=[
            dimension(D_AID1_ID, 100),
            dimension(D_AID2_ID, 80),
            dimension(D_AID3_ID, 80),
            dimension(D_AID4_ID, 80),
            dimension(D_AID5_ID, 80),
            dimension(D_AID6_ID, 80),
        ],
        ucp_contract={},
    )

    expected = int(
        sum(item.score * DIMENSION_WEIGHTS[item.dimension_id] for item in report.dimension_scores)
    )
    assert report.overall_score == expected
    assert report.d_ucp1_gate_applied is False
    assert report.d_ucp3_gate_applied is False


@pytest.mark.unit
def test_d_aid3_zero_does_not_cap_overall_score() -> None:
    report = build_compliance_report(
        domain="example.com",
        audit_id="audit-1",
        dimension_scores=[
            dimension(D_AID1_ID, 100),
            dimension(D_AID2_ID, 90),
            dimension(D_AID3_ID, 0),
            dimension(D_AID4_ID, 90),
            dimension(D_AID5_ID, 90),
            dimension(D_AID6_ID, 90),
        ],
        ucp_contract={},
    )

    assert report.overall_score == int(
        sum(item.score * DIMENSION_WEIGHTS[item.dimension_id] for item in report.dimension_scores)
    )
    assert report.d_ucp3_gate_applied is False
