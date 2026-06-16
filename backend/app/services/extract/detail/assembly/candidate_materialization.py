from __future__ import annotations

from collections.abc import Callable

from app.services.config.extraction_rules import DETAIL_LONG_TEXT_RANK_FIELDS
from app.services.extract.contracts import CandidateSet, RawCandidate
from app.services.extract.detail.assembly import dom_completion as _detail_dom_completion
from app.services.extract.detail.identity.core import (
    detail_url_candidate_is_low_signal as _detail_url_candidate_is_low_signal,
)
from app.services.extract.field_candidates import finalize_candidate_value
from app.services.shared.field_coerce import (
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
)

_detail_description_value_looks_thin = (
    _detail_dom_completion._detail_description_value_looks_thin
)
_detail_long_text_value_looks_truncated = (
    _detail_dom_completion._detail_long_text_value_looks_truncated
)


def winning_materialized_field(
    *,
    field_name: str,
    surface: str,
    page_url: str,
    evidence_builder: CandidateSet,
    source_rank: Callable[[str, str, str | None], int],
) -> tuple[object, str | None, list[RawCandidate]]:
    ordered_candidates = evidence_builder.ordered(
        field_name,
        source_rank=lambda source: source_rank(surface, field_name, source),
    )
    grouped_entries = _group_candidates_by_source(ordered_candidates)
    grouped_values = [
        (source, [candidate.value for candidate in entries])
        for source, entries in grouped_entries
    ]
    selected_source = grouped_values[0][0] if grouped_values else None
    winning_values = grouped_values[0][1] if grouped_values else []
    selected_group_index = _best_long_text_group_index(field_name, grouped_values)
    if len(grouped_values) > selected_group_index:
        selected_source, winning_values = grouped_values[selected_group_index]
    finalized = _finalized_field_value(field_name, ordered_candidates, winning_values)
    if (
        field_name == "url"
        and "detail" in str(surface or "").strip().lower()
        and _detail_url_candidate_is_low_signal(finalized, page_url=page_url)
    ):
        return None, None, []
    if field_name in STRUCTURED_OBJECT_FIELDS | STRUCTURED_OBJECT_LIST_FIELDS:
        return finalized, selected_source, ordered_candidates
    selected_entries = (
        grouped_entries[selected_group_index][1]
        if len(grouped_entries) > selected_group_index
        else []
    )
    return finalized, selected_source, selected_entries


def _group_candidates_by_source(
    ordered_candidates: list[RawCandidate],
) -> list[tuple[str, list[RawCandidate]]]:
    grouped: list[tuple[str, list[RawCandidate]]] = []
    for candidate in ordered_candidates:
        if grouped and grouped[-1][0] == candidate.source:
            grouped[-1][1].append(candidate)
            continue
        grouped.append((candidate.source, [candidate]))
    return grouped


def _best_long_text_group_index(
    field_name: str,
    grouped_values: list[tuple[str, list[object]]],
) -> int:
    if field_name not in DETAIL_LONG_TEXT_RANK_FIELDS or not grouped_values:
        return 0
    selected_long_text = finalize_candidate_value(field_name, grouped_values[0][1])
    if not _detail_long_text_value_looks_truncated(selected_long_text) and not (
        field_name == "description"
        and _detail_description_value_looks_thin(selected_long_text)
    ):
        return 0
    for group_index, (_source, candidate_values) in enumerate(
        grouped_values[1:], start=1
    ):
        candidate_long_text = finalize_candidate_value(field_name, candidate_values)
        if candidate_long_text in (None, "", [], {}):
            continue
        if _detail_long_text_value_looks_truncated(candidate_long_text):
            continue
        if field_name == "description" and _detail_description_value_looks_thin(
            candidate_long_text
        ):
            continue
        return group_index
    return 0


def _finalized_field_value(
    field_name: str,
    ordered_candidates: list[RawCandidate],
    winning_values: list[object],
) -> object:
    if field_name in STRUCTURED_OBJECT_FIELDS | STRUCTURED_OBJECT_LIST_FIELDS:
        return finalize_candidate_value(
            field_name, [candidate.value for candidate in ordered_candidates]
        )
    return finalize_candidate_value(field_name, winning_values)
