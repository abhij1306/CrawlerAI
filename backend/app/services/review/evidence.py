from __future__ import annotations

from app.models.crawl_run import CrawlRecord
from app.services.db_utils import mapping_or_empty
from app.services.shared.field_coerce import object_list, safe_int

__all__ = ("collect_evidence_review",)


def collect_evidence_review(records: list[CrawlRecord]) -> dict[str, object]:
    fields: list[dict[str, object]] = []
    findings: list[dict[str, object]] = []
    for record in records:
        source_trace = mapping_or_empty(record.source_trace)
        for field_name, payload in mapping_or_empty(
            source_trace.get("field_discovery")
        ).items():
            field_trace = mapping_or_empty(payload)
            if not (
                safe_int(field_trace.get("conflict_count"), default=0)
                or safe_int(field_trace.get("rejected_candidate_count"), default=0)
                or object_list(field_trace.get("validation_finding_ids"))
            ):
                continue
            fields.append(
                {
                    "record_id": record.id,
                    "field_name": str(field_name),
                    "winning_evidence_ids": object_list(
                        field_trace.get("winning_evidence_ids")
                    ),
                    "candidate_count": safe_int(
                        field_trace.get("candidate_count"), default=0
                    ),
                    "rejected_candidate_count": safe_int(
                        field_trace.get("rejected_candidate_count"), default=0
                    ),
                    "conflict_count": safe_int(
                        field_trace.get("conflict_count"), default=0
                    ),
                    "validation_finding_ids": object_list(
                        field_trace.get("validation_finding_ids")
                    ),
                    "resolver_rule": field_trace.get("resolver_rule"),
                    "llm_used": bool(field_trace.get("llm_used")),
                }
            )
        findings.extend(
            finding
            for finding in object_list(
                mapping_or_empty(source_trace.get("extraction")).get(
                    "validation_findings"
                )
            )
            if isinstance(finding, dict)
        )
    return {"fields": fields, "validation_findings": findings}
