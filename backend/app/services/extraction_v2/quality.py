from __future__ import annotations

from app.services.extraction_v2.contracts import ResolutionResult


def quality_verdict(record: dict[str, object], resolution: ResolutionResult, acquisition_outcome: str) -> str:
    if acquisition_outcome == "error":
        return "error"
    if acquisition_outcome == "blocked":
        return "blocked"
    if not record:
        return "empty"
    if resolution.blocking_finding_ids:
        return "invalid"
    if not resolution.primary_product_entity_id:
        return "review"
    if record.get("url") and record.get("title") and not resolution.unresolved_fact_types:
        return "success"
    if record.get("title") or record.get("price"):
        return "partial"
    return "review"
