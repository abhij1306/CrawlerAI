from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from app.extraction.contracts import FieldEvidenceState

FieldStateName = Literal[
    "captured_and_resolved",
    "captured_but_rejected",
    "captured_conflicting",
    "capture_incomplete",
    "collector_missed",
    "join_failed",
    "interaction_required",
    "source_unavailable",
    "not_present_in_captured_sources",
    "output_divergent",
    "not_captured",
    "captured_published",
    "captured_suppressed",
    "captured_unowned",
    "not_present_in_source",
    "not_requested",
]


def field_state(
    *,
    field: str,
    state: FieldStateName,
    evidence_ids: Iterable[str] = (),
    reason_codes: Iterable[str] = (),
    entity_id: str | None = None,
) -> FieldEvidenceState:
    return FieldEvidenceState(
        entity_id=entity_id,
        field=field,
        state=state,
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        reason_codes=tuple(dict.fromkeys(code for code in reason_codes if code)),
    )
