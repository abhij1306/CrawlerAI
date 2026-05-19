from __future__ import annotations

from app.services.config import ucp_audit as config
from app.services.ucp_audit.types import (
    AgentViewDelta,
    UCPComplianceReport,
    UCPDimensionScore,
    UCPFinding,
)


def build_compliance_report(
    *,
    domain: str,
    audit_id: str,
    dimension_scores: list[UCPDimensionScore],
    agent_view_samples: list[AgentViewDelta] | None = None,
) -> UCPComplianceReport:
    weighted = sum(item.score * item.weight for item in dimension_scores)
    overall = int(weighted)
    gate_applied = False
    discovery = next(
        (item for item in dimension_scores if item.dimension_id == config.D_UCP1_ID),
        None,
    )
    if discovery is None:
        raise ValueError(f"Missing required dimension score: {config.D_UCP1_ID}")
    if discovery.score == 0:
        overall = min(overall, config.D_UCP1_GATE_MAX_SCORE)
        gate_applied = True
    return UCPComplianceReport(
        domain=domain,
        audit_id=audit_id,
        overall_score=overall,
        dimension_scores=dimension_scores,
        all_findings=[
            finding
            for dimension in dimension_scores
            for finding in dimension.findings or []
        ],
        d_ucp1_gate_applied=gate_applied,
        agent_view_samples=list(agent_view_samples or []),
    )


def dimension_from_agent_delta(delta: AgentViewDelta) -> UCPDimensionScore:
    finding = (
        UCPFinding(
            code=config.FINDING_AGENT_DELTA_LOW_FIDELITY,
            dimension_id=config.D_UCP7_ID,
            severity=config.UCP_FINDING_BLOCKING,
        )
        if delta.fidelity_score < config.AGENT_DELTA_BLOCKING_THRESHOLD
        else None
    )
    score = int(delta.fidelity_score * 100)
    return UCPDimensionScore(
        dimension_id=config.D_UCP7_ID,
        score=score,
        status=_status(score),
        findings=[finding] if finding is not None else [],
        weight=config.DIMENSION_WEIGHTS[config.D_UCP7_ID],
    )


def _status(score: int) -> str:
    if score >= 80:
        return config.UCP_STATUS_PASS
    if score >= 50:
        return config.UCP_STATUS_WARNING
    return config.UCP_STATUS_FAIL
