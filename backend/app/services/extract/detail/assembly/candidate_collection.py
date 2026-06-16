from __future__ import annotations

__all__ = (
    "_EARLY_PRICE_REPAIR_REQUIRED_FIELDS",
    "_materialize_image_fields",
    "_coerce_float",
    "_field_source_rank",
    "_add_sourced_candidate",
    "_collect_record_candidates",
    "_collect_structured_payload_candidates",
    "_primary_source_for_record",
    "_SOURCE_PRIORITY_RANK",
    "_selector_self_heal_config",
    "_selected_selector_trace",
    "_materialize_record",
)

import logging
from typing import Any

from bs4 import BeautifulSoup

from app.services.confidence import score_record_confidence
from app.services.config.field_mappings import (
    ECOMMERCE_DETAIL_JS_STATE_PRIORITY_FIELDS,
    IMAGE_URL_FIELD,
    TITLE_FIELD,
    URL_FIELD,
)
from app.services.config.extraction_rules import (
    DETAIL_CATEGORY_SOURCE_RANKS,
    DETAIL_LONG_TEXT_RANK_FIELDS,
    DETAIL_LONG_TEXT_SOURCE_RANKS,
    DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS,
    DETAIL_TITLE_SOURCE_RANKS,
    SOURCE_PRIORITY,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.shared.field_coerce import (
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    coerce_field_value,
    finalize_record,
)
from app.services.extract.field_candidates import (
    add_candidate,
    collect_structured_candidates,
    finalize_candidate_value,
)
from app.services.extract.contracts import CandidateSet, RawCandidate
from app.services.extract.detail.identity.core import (
    detail_identity_codes_from_url as _detail_identity_codes_from_url,
    detail_identity_tokens as _detail_identity_tokens,
    detail_title_from_url as _detail_title_from_url,
    detail_url_candidate_is_low_signal as _detail_url_candidate_is_low_signal,
    preferred_detail_identity_url as _preferred_detail_identity_url,
)
from app.services.extract.detail.images.dedupe import dedupe_primary_and_additional_images
from app.services.extract.detail.assembly import dom_completion as _detail_dom_completion
from app.services.extract.detail.images import materialize as _detail_image_materialize
from app.services.extract.detail.identity import structured_pruning as _detail_structured_pruning
from app.services.extract.detail.text.sanitizer import detail_candidate_is_valid
from app.services.extract.detail.price.core import (
    drop_low_signal_zero_detail_price,
    reconcile_detail_currency_with_url as _reconcile_detail_currency_with_url,
)
from app.services.extract.detail.assembly.title_scorer import (
    promote_detail_title,
)

logger = logging.getLogger(__name__)

_EARLY_PRICE_REPAIR_REQUIRED_FIELDS = (TITLE_FIELD, IMAGE_URL_FIELD, URL_FIELD)
(
    _detail_structured_payload_is_irrelevant_product,
    _prune_irrelevant_detail_structured_payload,
    _structured_payload_is_breadcrumb_list,
) = (
    _detail_structured_pruning._detail_structured_payload_is_irrelevant_product,
    _detail_structured_pruning._prune_irrelevant_detail_structured_payload,
    _detail_structured_pruning._structured_payload_is_breadcrumb_list,
)
(
    _detail_description_value_looks_thin,
    _detail_long_text_value_looks_truncated,
    _requires_dom_completion,
    _should_collect_dom_variants,
) = (
    _detail_dom_completion._detail_description_value_looks_thin,
    _detail_dom_completion._detail_long_text_value_looks_truncated,
    _detail_dom_completion._requires_dom_completion,
    _detail_dom_completion._should_collect_dom_variants,
)
_materialize_image_fields = _detail_image_materialize._materialize_image_fields

try:
    DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS_INT = int(
        DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS
    )
except (TypeError, ValueError):
    DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS_INT = 50


def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _field_source_rank(surface: str, field_name: str, source: str | None) -> int:
    if str(surface or "").strip().lower() == "ecommerce_detail":
        if field_name == "category":
            configured_rank = DETAIL_CATEGORY_SOURCE_RANKS.get(str(source or ""))
            if configured_rank is not None:
                return configured_rank
        if field_name == "title":
            return DETAIL_TITLE_SOURCE_RANKS.get(str(source or ""), 20)
        if field_name in DETAIL_LONG_TEXT_RANK_FIELDS:
            return DETAIL_LONG_TEXT_SOURCE_RANKS.get(str(source or ""), 20)
        if (
            field_name in ECOMMERCE_DETAIL_JS_STATE_PRIORITY_FIELDS
            and source == "js_state"
        ):
            return 2
    return 100 + _SOURCE_PRIORITY_RANK.get(
        str(source or ""), len(_SOURCE_PRIORITY_RANK)
    )


def _add_sourced_candidate(
    candidates: dict[str, list[object]],
    field_name: str,
    value: object,
    *,
    source: str,
    evidence_builder: CandidateSet | None = None,
    validate: bool = True,
) -> int:
    if validate and not detail_candidate_is_valid(field_name, value, source=source):
        return 0
    admitted_values: dict[str, list[object]] = {}
    add_candidate(admitted_values, field_name, value)
    if evidence_builder is not None:
        for item in admitted_values.get(field_name, []):
            if any(
                candidate.source == source and candidate.value == item
                for candidate in evidence_builder.field_candidates(field_name)
            ):
                continue
            candidate_index = len(evidence_builder.field_candidates(field_name))
            evidence_builder.add(
                field_name=field_name,
                value=item,
                source=source,
                extraction_tier=_tier_from_source(source),
                candidate_index=candidate_index,
                source_locator=f"{source}:{field_name}[{candidate_index}]",
                evidence=f"{source}:{field_name}[{candidate_index}]",
            )
    added = 0
    for item in admitted_values.get(field_name, []):
        added += add_candidate(candidates, field_name, item)
    return added


def _collect_record_candidates(
    record: dict[str, Any],
    *,
    page_url: str,
    fields: list[str],
    candidates: dict[str, list[object]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    source: str,
    evidence_builder: CandidateSet | None = None,
) -> None:
    allowed_fields = set(fields)
    for field_name, value in dict(record or {}).items():
        normalized_field = str(field_name or "").strip()
        if (
            not normalized_field
            or normalized_field.startswith("_")
            or normalized_field not in allowed_fields
        ):
            continue
        _add_sourced_candidate(
            candidates,
            normalized_field,
            coerce_field_value(normalized_field, value, page_url),
            source=source,
            evidence_builder=evidence_builder,
        )


def _collect_structured_payload_candidates(
    payload: object,
    *,
    alias_lookup: dict[str, str],
    page_url: str,
    requested_page_url: str | None,
    candidates: dict[str, list[object]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    source: str,
    evidence_builder: CandidateSet | None = None,
) -> None:
    identity_url = requested_page_url or page_url
    if identity_url:
        requested_title = _detail_title_from_url(identity_url)
        requested_tokens = _detail_identity_tokens(requested_title)
        requested_codes = _detail_identity_codes_from_url(identity_url)
        had_irrelevant_product_payload = (
            isinstance(payload, dict)
            and _detail_structured_payload_is_irrelevant_product(
                payload,
                page_url=page_url,
                requested_page_url=identity_url,
                requested_title=requested_title,
                requested_tokens=requested_tokens,
                requested_codes=requested_codes,
                detail_identity_tokens=_detail_identity_tokens,
            )
        )
        payload = _prune_irrelevant_detail_structured_payload(
            payload,
            page_url=page_url,
            requested_page_url=identity_url,
            requested_title=requested_title,
            requested_tokens=requested_tokens,
            requested_codes=requested_codes,
            detail_title_from_url=_detail_title_from_url,
            detail_identity_tokens=_detail_identity_tokens,
            detail_identity_codes_from_url=_detail_identity_codes_from_url,
        )
        if had_irrelevant_product_payload and payload in (None, "", [], {}):
            candidates.setdefault("_irrelevant_detail_structured_product", []).append(
                True
            )
    if payload in (None, "", [], {}):
        return
    structured_candidates: dict[str, list[object]] = {}
    collect_structured_candidates(
        payload,
        alias_lookup,
        page_url,
        structured_candidates,
    )
    for field_name, values in structured_candidates.items():
        for value in values:
            candidate_source = source
            if (
                field_name == "category"
                and source == "json_ld"
                and _structured_payload_is_breadcrumb_list(payload)
            ):
                candidate_source = "json_ld_breadcrumb"
            _add_sourced_candidate(
                candidates,
                field_name,
                value,
                source=candidate_source,
                evidence_builder=evidence_builder,
                validate=False,
            )


def _primary_source_for_record(selected_field_sources: dict[str, str]) -> str:
    selected_sources = [
        str(source or "").strip()
        for source in selected_field_sources.values()
        if str(source or "").strip()
    ]
    if selected_sources:
        return min(
            selected_sources,
            key=lambda source_name: _SOURCE_PRIORITY_RANK.get(
                source_name,
                len(_SOURCE_PRIORITY_RANK),
            ),
        )
    return "structured_dom"


_SOURCE_PRIORITY_RANK = {
    source_name: index for index, source_name in enumerate(SOURCE_PRIORITY)
}


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


def _tier_from_source(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized in {"adapter", "network_payload"}:
        return "authoritative"
    if normalized in {"json_ld", "microdata", "opengraph", "json_ld_breadcrumb"}:
        return "structured_data"
    if normalized == "js_state":
        return "js_state"
    if normalized.startswith("dom") or normalized in {"selector_rule", "html_image"}:
        return "dom"
    return "unknown"


def _selector_self_heal_config(
    extraction_runtime_snapshot: dict[str, object] | None,
) -> dict[str, object]:
    selector_self_heal = (
        extraction_runtime_snapshot.get("selector_self_heal")
        if isinstance(extraction_runtime_snapshot, dict)
        else None
    )
    return {
        "enabled": bool(
            selector_self_heal.get("enabled")
            if isinstance(selector_self_heal, dict)
            and selector_self_heal.get("enabled") is not None
            else crawler_runtime_settings.selector_self_heal_enabled
        ),
        "threshold": _coerce_float(
            selector_self_heal.get("min_confidence")
            if isinstance(selector_self_heal, dict)
            and selector_self_heal.get("min_confidence") is not None
            else crawler_runtime_settings.selector_self_heal_min_confidence,
            default=float(crawler_runtime_settings.selector_self_heal_min_confidence),
        ),
    }


def _selected_selector_trace(
    *,
    field_name: str,
    finalized_value: object,
    selector_trace_candidates: dict[str, list[dict[str, object]]],
) -> dict[str, object] | None:
    traces = list(selector_trace_candidates.get(field_name) or [])
    if not traces:
        return None
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        if trace.get("_candidate_value") == finalized_value:
            return {
                key: value
                for key, value in trace.items()
                if not str(key).startswith("_")
            }
    trace = next((row for row in traces if isinstance(row, dict)), {})
    if not isinstance(trace, dict):
        return None
    return {key: value for key, value in trace.items() if not str(key).startswith("_")}


def _winning_materialized_field(
    *,
    field_name: str,
    surface: str,
    page_url: str,
    evidence_builder: CandidateSet,
) -> tuple[object, str | None, list[RawCandidate]]:
    ordered_candidates = evidence_builder.ordered(
        field_name,
        source_rank=lambda source: _field_source_rank(surface, field_name, source),
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


def _materialize_record(
    *,
    page_url: str,
    requested_page_url: str | None,
    surface: str,
    requested_fields: list[str] | None,
    fields: list[str],
    candidates: dict[str, list[object]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    evidence_builder: CandidateSet,
    extraction_runtime_snapshot: dict[str, object] | None,
    tier_name: str,
    completed_tiers: list[str],
    soup: BeautifulSoup | None = None,
    raw_soup: BeautifulSoup | None = None,
) -> dict[str, Any]:
    identity_url = _preferred_detail_identity_url(
        surface=surface,
        page_url=page_url,
        requested_page_url=requested_page_url,
    )
    record: dict[str, Any] = {"source_url": identity_url, "url": identity_url}
    selected_field_sources: dict[str, str] = {}
    selected_selector_traces: dict[str, dict[str, object]] = {}
    merged_images, merged_image_source = _materialize_image_fields(
        surface=surface,
        candidate_set=evidence_builder,
        source_rank=_field_source_rank,
        page_url=page_url,
        soup=soup,
        raw_soup=raw_soup,
    )
    for field_name in fields:
        if field_name in {"image_url", "additional_images"}:
            continue
        finalized, selected_source, selected_evidence_entries = (
            _winning_materialized_field(
                field_name=field_name,
                surface=surface,
                page_url=page_url,
                evidence_builder=evidence_builder,
            )
        )
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
            if selected_source:
                selected_field_sources[field_name] = selected_source
                record.setdefault("_field_evidence", {})[field_name] = (
                    _field_evidence_summary(
                        field_name=field_name,
                        selected_entries=selected_evidence_entries,
                        evidence_builder=evidence_builder,
                    )
                )
                if selected_source in {"selector_rule", "dom_selector", "dom_h1"}:
                    selector_trace = _selected_selector_trace(
                        field_name=field_name,
                        finalized_value=finalized,
                        selector_trace_candidates=selector_trace_candidates,
                    )
                    if selector_trace:
                        selected_selector_traces[field_name] = selector_trace
    if merged_images:
        record["image_url"] = merged_images[0]
        if len(merged_images) > 1:
            record["additional_images"] = merged_images[1:]
        if merged_image_source:
            selected_field_sources["image_url"] = merged_image_source
            image_entries = evidence_builder.ordered(
                "image_url",
                source_rank=lambda source: _field_source_rank(
                    surface,
                    "image_url",
                    source,
                ),
            )
            if image_entries:
                record.setdefault("_field_evidence", {})["image_url"] = (
                    _field_evidence_summary(
                        field_name="image_url",
                        selected_entries=image_entries[:1],
                        evidence_builder=evidence_builder,
                    )
                )
    promoted = promote_detail_title(
        record,
        page_url=page_url,
        candidate_set=evidence_builder,
        source_rank=_field_source_rank,
    )
    if promoted:
        selected_field_sources["title"] = promoted.source
        title_summary = evidence_builder.record_resolution(
            field_name="title",
            winning_evidence_ids=[promoted.evidence_id],
            resolver_rule="title_promotion",
        )
        record.setdefault("_field_evidence", {})["title"] = title_summary
        if promoted.source in {"selector_rule", "dom_selector", "dom_h1"}:
            selector_trace = _selected_selector_trace(
                field_name="title",
                finalized_value=record.get("title"),
                selector_trace_candidates=selector_trace_candidates,
            )
            if selector_trace:
                selected_selector_traces["title"] = selector_trace
            else:
                selected_selector_traces.pop("title", None)
        else:
            selected_selector_traces.pop("title", None)
    record["_field_sources"] = {
        field_name: sources
        for field_name in fields
        if field_name in record
        if (sources := evidence_builder.winning_field_sources(field_name))
    }
    if selected_selector_traces:
        record["_selector_traces"] = selected_selector_traces
    if candidates.get("_irrelevant_detail_structured_product"):
        record["_irrelevant_detail_structured_product"] = True
    graph = evidence_builder.as_graph()
    record["_evidence_graph"] = graph
    review_bucket = _review_bucket_from_decisions(evidence_builder)
    if review_bucket:
        record["_review_bucket"] = review_bucket
    record["_source"] = _primary_source_for_record(selected_field_sources)
    if str(surface or "").strip().lower() == "ecommerce_detail":
        _reconcile_detail_currency_with_url(record, page_url=page_url)
    drop_low_signal_zero_detail_price(record)
    dedupe_primary_and_additional_images(record)
    confidence = score_record_confidence(
        record,
        surface=surface,
        requested_fields=requested_fields,
    )
    selector_self_heal = _selector_self_heal_config(extraction_runtime_snapshot)
    record["_confidence"] = confidence
    record["_extraction_tiers"] = {
        "completed": list(completed_tiers),
        "current": tier_name,
    }
    record["_self_heal"] = {
        "enabled": bool(selector_self_heal["enabled"]),
        "triggered": False,
        "threshold": _coerce_float(selector_self_heal.get("threshold")),
    }
    return finalize_record(record, surface=surface)


def _review_bucket_from_decisions(
    evidence_builder: CandidateSet,
) -> list[dict[str, object]]:
    candidate_by_id = {
        candidate.evidence_id: candidate for candidate in evidence_builder.candidates
    }
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for field_name, decision in evidence_builder.field_decisions.items():
        for rejection in decision.get("rejected_candidates") or []:
            if not isinstance(rejection, dict) or rejection.get("reason") == "duplicate_value":
                continue
            candidate = candidate_by_id.get(str(rejection.get("evidence_id") or ""))
            if candidate is None:
                continue
            signature = (field_name, repr(candidate.value))
            if signature in seen:
                continue
            seen.add(signature)
            rows.append(
                {
                    "key": field_name,
                    "value": candidate.value,
                    "source": candidate.source,
                    "evidence_id": candidate.evidence_id,
                    "reason": rejection.get("reason"),
                }
            )
    return rows


def _field_evidence_summary(
    *,
    field_name: str,
    selected_entries: list[RawCandidate],
    evidence_builder: CandidateSet,
) -> dict[str, object]:
    return evidence_builder.record_resolution(
        field_name=field_name,
        winning_evidence_ids=[
            candidate.evidence_id for candidate in selected_entries
        ],
        resolver_rule="source_priority",
    )
