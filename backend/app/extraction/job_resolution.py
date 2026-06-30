from __future__ import annotations

from app.extraction.contracts import (
    Decision,
    Evidence,
    RejectedEvidence,
)
from app.core.shared.ids import stable_id


def resolve_job_detail(evidence_rows: list[Evidence]) -> list[Decision]:
    return _resolve_by_fact(evidence_rows)


def resolve_job_listing(evidence_rows: list[Evidence]) -> list[Decision]:
    decisions: list[Decision] = []
    by_subject: dict[str, list[Evidence]] = {}
    for row in evidence_rows:
        if row.subject_id:
            by_subject.setdefault(row.subject_id, []).append(row)
    for subject_id, rows in by_subject.items():
        for fact_type in sorted({row.fact_type for row in rows}):
            decisions.append(
                _decision(
                    subject_id,
                    fact_type,
                    [row for row in rows if row.fact_type == fact_type],
                    rule_id="job_listing_highest_confidence_v1",
                )
            )
    return decisions


def _resolve_by_fact(evidence_rows: list[Evidence]) -> list[Decision]:
    by_fact: dict[str, list[Evidence]] = {}
    for row in evidence_rows:
        by_fact.setdefault(row.fact_type, []).append(row)
    return [
        _decision(
            rows[0].subject_id or "job",
            fact_type,
            rows,
            rule_id="job_detail_highest_confidence_v1",
        )
        for fact_type, rows in sorted(by_fact.items())
    ]


def _decision(
    entity_id: str,
    fact_type: str,
    rows: list[Evidence],
    *,
    rule_id: str,
) -> Decision:
    candidates = sorted(rows, key=lambda row: (-row.confidence, row.evidence_id))
    accepted = candidates[0]
    return Decision(
        decision_id=stable_id("decision", entity_id, fact_type, accepted.evidence_id),
        entity_id=entity_id,
        fact_type=fact_type,
        accepted_evidence_ids=(accepted.evidence_id,),
        rejected=tuple(
            RejectedEvidence(
                evidence_id=row.evidence_id,
                reason="lower_confidence",
            )
            for row in candidates[1:]
        ),
        finding_ids=(),
        rule_id=rule_id,
        status="resolved",
    )
