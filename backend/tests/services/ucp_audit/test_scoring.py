from __future__ import annotations

from app.services.config.ucp_audit import (
    D_UCP1_ID,
    D_UCP2_ID,
    D_UCP3_ID,
    D_UCP4_ID,
    D_UCP5_ID,
    D_UCP6_ID,
    D_UCP7_ID,
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


def test_dimension_weights_sum_to_one() -> None:
    assert round(sum(DIMENSION_WEIGHTS.values()), 6) == 1.0


def test_d_ucp1_zero_caps_overall_score() -> None:
    report = build_compliance_report(
        domain="example.com",
        audit_id="audit-1",
        dimension_scores=[
            dimension(D_UCP1_ID, 0),
            dimension(D_UCP2_ID, 90),
            dimension(D_UCP3_ID, 90),
            dimension(D_UCP4_ID, 90),
            dimension(D_UCP5_ID, 90),
            dimension(D_UCP6_ID, 90),
            dimension(D_UCP7_ID, 90),
        ],
    )

    assert report.overall_score <= 30
    assert report.d_ucp1_gate_applied is True


def test_d_ucp1_pass_uses_weighted_average() -> None:
    report = build_compliance_report(
        domain="example.com",
        audit_id="audit-1",
        dimension_scores=[
            dimension(D_UCP1_ID, 100),
            dimension(D_UCP2_ID, 80),
            dimension(D_UCP3_ID, 80),
            dimension(D_UCP4_ID, 80),
            dimension(D_UCP5_ID, 80),
            dimension(D_UCP6_ID, 80),
            dimension(D_UCP7_ID, 80),
        ],
    )

    expected = int(
        sum(item.score * DIMENSION_WEIGHTS[item.dimension_id] for item in report.dimension_scores)
    )
    assert report.overall_score == expected
    assert report.d_ucp1_gate_applied is False
