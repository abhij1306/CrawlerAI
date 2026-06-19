from __future__ import annotations

from typing import Any

from app.services.extraction.contracts import (
    Decision,
    Evidence,
    JobDetailRecord,
    JobListingRecord,
    RejectedEvidence,
)
from app.services.extraction.ids import stable_id
from app.services.extraction.materialization import lineage


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


def materialize_job_detail(
    evidence_rows: list[Evidence],
    decisions: list[Decision],
) -> list[JobDetailRecord]:
    by_id = {row.evidence_id: row for row in evidence_rows}
    field_map = {
        "job.title": "title",
        "job.id": "job_id",
        "job.company": "company",
        "job.location": "location",
        "job.type": "job_type",
        "job.posted_date": "posted_date",
        "job.url": "url",
        "job.apply_url": "apply_url",
        "job.description": "description",
    }
    row, lineages = _materialized_fields(by_id, decisions, field_map)
    if not row.get("title"):
        return []
    if lineages:
        row["_lineage"] = lineages
    return [JobDetailRecord.model_validate(row)]


def materialize_job_listing(
    evidence_rows: list[Evidence],
    decisions: list[Decision],
    *,
    max_records: int,
) -> list[JobListingRecord]:
    by_id = {row.evidence_id: row for row in evidence_rows}
    field_map = {
        "job.title": "title",
        "job.url": "url",
        "job.company": "company",
        "job.location": "location",
    }
    rows_by_subject: dict[str, dict[str, Any]] = {}
    lineage_by_subject: dict[str, dict[str, object]] = {}
    for decision in decisions:
        field = field_map.get(decision.fact_type)
        if not field or not decision.accepted_evidence_ids:
            continue
        evidence_row = by_id[decision.accepted_evidence_ids[0]]
        subject_id = evidence_row.subject_id or decision.entity_id
        rows_by_subject.setdefault(subject_id, {})[field] = evidence_row.value
        lineage_by_subject.setdefault(subject_id, {})[field] = lineage(
            decision=decision
        )
    materialized = []
    for subject_id, row in rows_by_subject.items():
        if not row.get("title") or not row.get("url"):
            continue
        row["_lineage"] = lineage_by_subject.get(subject_id, {})
        row["_subject_id"] = subject_id
        materialized.append(JobListingRecord.model_validate(row))
    materialized.sort(key=lambda row: str(row.url))
    return materialized[:max_records]


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
        decision_id=stable_id(
            "decision", entity_id, fact_type, accepted.evidence_id
        ),
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


def _materialized_fields(
    by_id: dict[str, Evidence],
    decisions: list[Decision],
    field_map: dict[str, str],
) -> tuple[dict[str, Any], dict[str, object]]:
    row: dict[str, Any] = {}
    lineages: dict[str, object] = {}
    for decision in decisions:
        field = field_map.get(decision.fact_type)
        if not field or not decision.accepted_evidence_ids:
            continue
        evidence_row = by_id[decision.accepted_evidence_ids[0]]
        row[field] = evidence_row.value
        lineages[field] = lineage(decision=decision)
    return row, lineages
