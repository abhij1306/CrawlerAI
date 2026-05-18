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
    "_ordered_candidates_for_field",
    "_group_ordered_candidates_by_source",
    "_selector_self_heal_config",
    "_selected_selector_trace",
    "_materialize_record",
)

import logging
import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.confidence import score_record_confidence
from app.services.config.field_mappings import (
    DOM_HIGH_VALUE_FIELDS,
    DOM_OPTIONAL_CUE_FIELDS,
    ECOMMERCE_DETAIL_JS_STATE_PRIORITY_FIELDS,
    IMAGE_URL_FIELD,
    TITLE_FIELD,
    URL_FIELD,
    VARIANT_AXIS_FIELD_NAMES,
    VARIANT_DOM_FIELD_NAMES,
)
from app.services.config.extraction_rules import (
    DETAIL_CATEGORY_SOURCE_RANKS,
    DETAIL_PRODUCT_IMAGE_CUE_SELECTOR,
    DETAIL_IMAGE_RAW_SOUP_FALLBACK_MAX_WINNING_IMAGES,
    DETAIL_LONG_TEXT_RANK_FIELDS,
    DETAIL_LONG_TEXT_SOURCE_RANKS,
    DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS,
    DETAIL_LONG_TEXT_TRUNCATED_TAIL_TOKENS,
    DETAIL_TITLE_SOURCE_RANKS,
    SOURCE_PRIORITY,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extraction_context import (
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.structured_sources import harvest_js_state_objects
from app.services.shared.field_coerce import (
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    clean_text,
    coerce_field_value,
    finalize_record,
    is_title_noise,
    object_dict as _object_dict,
    object_list as _object_list,
    surface_alias_lookup,
    surface_fields,
    text_or_none,
)
from app.services.extract.field_candidates import (
    add_candidate,
    collect_structured_candidates,
    finalize_candidate_value,
    record_score,
)
from app.services.dom.selector_engine import (
    dedupe_image_urls,
    extract_page_images,
    requested_content_extractability,
)
from app.services.js_state.state_normalizer import map_js_state_to_fields
from app.services.network_payload_mapper import map_network_payloads_to_fields
from app.services.extract.detail.assembly.dom_fallbacks import apply_dom_fallbacks
from app.services.extract.detail.variants.dom_extraction import (
    extract_variants_from_dom as _extract_variants_from_dom,
)
from app.services.extract.detail.assembly.dom_section_targets import (
    primary_dom_context,
    record_has_rich_existing_variants,
)
from app.services.extract.detail.assembly.raw_signals import (
    breadcrumb_category_from_dom,
)
from app.services.extract.detail.identity.shell_filter import (
    detail_url_has_multiple_product_segments as _detail_url_has_multiple_product_segments,
    looks_like_site_shell_record as _looks_like_site_shell_record,
)
from app.services.extract.detail.identity.core import (
    detail_identity_codes_from_url as _detail_identity_codes_from_url,
    detail_identity_tokens as _detail_identity_tokens,
    detail_redirect_identity_is_mismatched as _detail_redirect_identity_is_mismatched,
    detail_title_from_url as _detail_title_from_url,
    detail_url_candidate_is_low_signal as _detail_url_candidate_is_low_signal,
    detail_url_is_collection_like as _detail_url_is_collection_like,
    detail_url_is_utility as _detail_url_is_utility,
    preferred_detail_identity_url as _preferred_detail_identity_url,
    prune_irrelevant_detail_dom_nodes,
    record_matches_requested_detail_identity as _record_matches_requested_detail_identity,
)
from app.services.extract.detail.assembly.final_cleanup import repair_ecommerce_detail_record_quality
from app.services.extract.table_extractor import extract_tables
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
    title_needs_promotion,
)
from app.services.extract.variant_choice_traversal import variant_dom_cues_present
from app.services.field_policy import exact_requested_field_key
from app.services.extract.detail.assembly.tiers import (
    DetailTierExecutor,
    DetailTierInputs,
    DetailTierRuntime,
    DetailTierState,
    PreparedDetailExtraction,
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
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    field_name: str,
    value: object,
    *,
    source: str,
) -> None:
    if not detail_candidate_is_valid(field_name, value, source=source):
        return
    before = len(candidates.get(field_name, []))
    add_candidate(candidates, field_name, value)
    after = len(candidates.get(field_name, []))
    if after <= before:
        return
    candidate_sources.setdefault(field_name, []).extend([source] * (after - before))
    bucket = field_sources.setdefault(field_name, [])
    if source not in bucket:
        bucket.append(source)


def _collect_record_candidates(
    record: dict[str, Any],
    *,
    page_url: str,
    fields: list[str],
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    source: str,
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
            candidate_sources,
            field_sources,
            normalized_field,
            coerce_field_value(normalized_field, value, page_url),
            source=source,
        )


def _collect_structured_payload_candidates(
    payload: object,
    *,
    alias_lookup: dict[str, str],
    page_url: str,
    requested_page_url: str | None,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    source: str,
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
            added = add_candidate(candidates, field_name, value)
            if added <= 0:
                continue
            candidate_sources.setdefault(field_name, []).extend(
                [candidate_source] * added
            )
            bucket = field_sources.setdefault(field_name, [])
            if candidate_source not in bucket:
                bucket.append(candidate_source)


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


def _ordered_candidates_for_field(
    surface: str,
    field_name: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
) -> list[tuple[str | None, object]]:
    sources = candidate_sources.get(field_name, [])
    indexed_entries = sorted(
        (
            _field_source_rank(
                surface,
                field_name,
                sources[index] if index < len(sources) else None,
            ),
            index,
            sources[index] if index < len(sources) else None,
            value,
        )
        for index, value in enumerate(candidates.get(field_name, []))
    )
    return [(source, value) for _, _, source, value in indexed_entries]


def _group_ordered_candidates_by_source(
    ordered_candidates: list[tuple[str | None, object]],
) -> list[tuple[str | None, list[object]]]:
    grouped: list[tuple[str | None, list[object]]] = []
    for source, value in ordered_candidates:
        if grouped and grouped[-1][0] == source:
            grouped[-1][1].append(value)
            continue
        grouped.append((source, [value]))
    return grouped


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


def _materialize_record(
    *,
    page_url: str,
    requested_page_url: str | None,
    surface: str,
    requested_fields: list[str] | None,
    fields: list[str],
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
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
        candidates=candidates,
        candidate_sources=candidate_sources,
        page_url=page_url,
        soup=soup,
        raw_soup=raw_soup,
    )
    for field_name in fields:
        if field_name in {"image_url", "additional_images"}:
            continue
        ordered_candidates = _ordered_candidates_for_field(
            surface,
            field_name,
            candidates,
            candidate_sources,
        )
        grouped_candidates = _group_ordered_candidates_by_source(ordered_candidates)
        selected_source = grouped_candidates[0][0] if grouped_candidates else None
        winning_values = grouped_candidates[0][1] if grouped_candidates else []
        if field_name in DETAIL_LONG_TEXT_RANK_FIELDS and grouped_candidates:
            selected_long_text = finalize_candidate_value(field_name, winning_values)
            if _detail_long_text_value_looks_truncated(selected_long_text) or (
                field_name == "description"
                and _detail_description_value_looks_thin(selected_long_text)
            ):
                for candidate_source, candidate_values in grouped_candidates[1:]:
                    candidate_long_text = finalize_candidate_value(
                        field_name, candidate_values
                    )
                    if candidate_long_text not in (
                        None,
                        "",
                        [],
                        {},
                    ) and not _detail_long_text_value_looks_truncated(
                        candidate_long_text
                    ) and not (
                        field_name == "description"
                        and _detail_description_value_looks_thin(candidate_long_text)
                    ):
                        selected_source = candidate_source
                        winning_values = candidate_values
                        break
        finalized = (
            finalize_candidate_value(
                field_name, [value for _, value in ordered_candidates]
            )
            if field_name in STRUCTURED_OBJECT_FIELDS | STRUCTURED_OBJECT_LIST_FIELDS
            else finalize_candidate_value(field_name, winning_values)
        )
        if (
            field_name == "url"
            and "detail" in str(surface or "").strip().lower()
            and _detail_url_candidate_is_low_signal(finalized, page_url=page_url)
        ):
            continue
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
            if selected_source:
                selected_field_sources[field_name] = selected_source
                if selected_source == "selector_rule":
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
    promoted = promote_detail_title(
        record,
        page_url=page_url,
        candidates=candidates,
        candidate_sources=candidate_sources,
        source_rank=_field_source_rank,
    )
    if promoted:
        selected_field_sources["title"] = promoted[1]
        selected_selector_traces.pop("title", None)
    record["_field_sources"] = {
        field_name: list(source_list)
        for field_name, source_list in field_sources.items()
        if field_name in record
    }
    if selected_selector_traces:
        record["_selector_traces"] = selected_selector_traces
    if candidates.get("_irrelevant_detail_structured_product"):
        record["_irrelevant_detail_structured_product"] = True
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
