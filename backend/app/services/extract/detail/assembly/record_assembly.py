from __future__ import annotations

__all__ = (
    "build_detail_record",
    "detail_record_rejection_reason",
    "infer_detail_failure_reason",
    "extract_detail_records",
)

from typing import Any

from bs4 import BeautifulSoup

from app.services.confidence import score_record_confidence
from app.services.extraction_context import (
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.extract.detail.assembly import candidate_collection as _candidates
from app.services.extract.detail.assembly import dom_completion as _detail_dom_completion
from app.services.extract.detail.assembly.dom_fallbacks import apply_dom_fallbacks
from app.services.extract.detail.assembly.dom_section_targets import primary_dom_context
from app.services.extract.detail.variants.dom_extraction import (
    extract_variants_from_dom as _extract_variants_from_dom,
)
from app.services.extract.detail.identity.core import (
    detail_identity_tokens as _detail_identity_tokens,
    detail_redirect_identity_is_mismatched as _detail_redirect_identity_is_mismatched,
    detail_title_from_url as _detail_title_from_url,
    detail_url_is_collection_like as _detail_url_is_collection_like,
    detail_url_is_utility as _detail_url_is_utility,
    prune_irrelevant_detail_dom_nodes,
    record_matches_requested_detail_identity as _record_matches_requested_detail_identity,
)
from app.services.extract.detail.price.core import (
    drop_low_signal_zero_detail_price,
    reconcile_detail_currency_with_url as _reconcile_detail_currency_with_url,
)
from app.services.extract.detail.assembly.final_cleanup import repair_ecommerce_detail_record_quality
from app.services.extract.detail.identity.shell_filter import (
    detail_url_has_multiple_product_segments as _detail_url_has_multiple_product_segments,
    looks_like_site_shell_record as _looks_like_site_shell_record,
)
from app.services.extract.detail.assembly.tiers import (
    DetailTierExecutor,
    DetailTierInputs,
    DetailTierRuntime,
    DetailTierState,
    PreparedDetailExtraction,
)
from app.services.extract.detail.assembly.title_scorer import title_needs_promotion
from app.services.extract.field_candidates import record_score
from app.services.extract.table_extractor import extract_tables
from app.services.js_state.state_normalizer import map_js_state_to_fields
from app.services.network_payload_mapper import map_network_payloads_to_fields
from app.services.shared.field_coerce import (
    finalize_record,
    is_title_noise,
    surface_alias_lookup,
    surface_fields,
    text_or_none,
)
from app.services.structured_sources import harvest_js_state_objects

(
    _add_sourced_candidate,
    _coerce_float,
    _collect_record_candidates,
    _collect_structured_payload_candidates,
    _materialize_record,
    _selector_self_heal_config,
) = (
    _candidates._add_sourced_candidate,
    _candidates._coerce_float,
    _candidates._collect_record_candidates,
    _candidates._collect_structured_payload_candidates,
    _candidates._materialize_record,
    _candidates._selector_self_heal_config,
)
(
    _requires_dom_completion,
    _should_collect_dom_variants,
) = (
    _detail_dom_completion._requires_dom_completion,
    _detail_dom_completion._should_collect_dom_variants,
)

def _finalize_early_detail_record(
    record: dict[str, Any],
    *,
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    requested_page_url: str | None,
    soup: BeautifulSoup,
    js_state_objects: dict[str, Any],
) -> dict[str, Any]:
    _attach_detail_tables(record, soup)
    if str(surface or "").strip().lower() == "ecommerce_detail":
        _reconcile_detail_currency_with_url(record, page_url=page_url)
        repair_ecommerce_detail_record_quality(
            record,
            html=html,
            page_url=page_url,
            requested_page_url=requested_page_url,
            soup=soup,
            js_state_objects=js_state_objects,
        )
        drop_low_signal_zero_detail_price(record)
        record = finalize_record(record, surface=surface)
    record["_confidence"] = score_record_confidence(
        record,
        surface=surface,
        requested_fields=requested_fields,
    )
    record["_extraction_tiers"]["early_exit"] = "js_state"
    return record


def _promote_dom_detail_title(
    record: dict[str, Any],
    *,
    js_state_record: dict[str, Any],
    page_url: str,
) -> None:
    if not title_needs_promotion(
        text_or_none(record.get("title")) or "",
        page_url=page_url,
    ):
        return
    preferred_title = text_or_none(js_state_record.get("title"))
    if preferred_title:
        record["title"] = preferred_title
    return


def _fill_missing_dom_detail_title(record: dict[str, Any], *, page_url: str) -> None:
    if text_or_none(record.get("title")):
        return
    fallback_title = _detail_title_from_url(page_url)
    if not fallback_title:
        return
    record["title"] = fallback_title
    title_sources = record.setdefault("_field_sources", {}).setdefault("title", [])
    if "url_slug" not in title_sources:
        title_sources.append("url_slug")


def _finalize_dom_detail_record(
    record: dict[str, Any],
    *,
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    requested_page_url: str | None,
    soup: BeautifulSoup,
    js_state_objects: dict[str, Any],
) -> dict[str, Any]:
    _attach_detail_tables(record, soup)
    if str(surface or "").strip().lower() == "ecommerce_detail":
        _reconcile_detail_currency_with_url(record, page_url=page_url)
        repair_ecommerce_detail_record_quality(
            record,
            html=html,
            page_url=page_url,
            requested_page_url=requested_page_url,
            soup=soup,
            js_state_objects=js_state_objects,
        )
        drop_low_signal_zero_detail_price(record)
        record = finalize_record(record, surface=surface)
    record["_confidence"] = score_record_confidence(
        record,
        surface=surface,
        requested_fields=requested_fields,
    )
    record["_extraction_tiers"]["early_exit"] = None
    return record


def _attach_detail_tables(record: dict[str, Any], soup: BeautifulSoup | None) -> None:
    if record.get("tables") not in (None, "", [], {}) or soup is None:
        return
    tables = extract_tables(soup)
    if tables:
        record["tables"] = tables


def _prepare_detail_extraction(
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    *,
    requested_page_url: str | None,
    extraction_runtime_snapshot: dict[str, object] | None,
) -> PreparedDetailExtraction:
    context = prepare_extraction_context(html)
    dom_parser, soup = primary_dom_context(context, page_url=page_url)
    raw_soup = context.original_soup
    if str(surface or "").strip().lower() == "ecommerce_detail":
        soup = BeautifulSoup(str(soup), "html.parser")
        prune_irrelevant_detail_dom_nodes(
            soup,
            page_url=page_url,
            requested_page_url=text_or_none(requested_page_url) or page_url,
        )
    candidates: dict[str, list[object]] = {}
    candidate_sources: dict[str, list[str]] = {}
    field_sources: dict[str, list[str]] = {}
    selector_trace_candidates: dict[str, list[dict[str, object]]] = {}
    state = DetailTierState(
        page_url=page_url,
        requested_page_url=requested_page_url,
        surface=surface,
        requested_fields=requested_fields,
        fields=surface_fields(surface, requested_fields),
        candidates=candidates,
        candidate_sources=candidate_sources,
        field_sources=field_sources,
        selector_trace_candidates=selector_trace_candidates,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
        completed_tiers=[],
        raw_soup=raw_soup,
        soup=soup,
    )
    js_state_objects = harvest_js_state_objects(None, context.cleaned_html)
    js_state_record = map_js_state_to_fields(
        js_state_objects,
        surface=surface,
        page_url=page_url,
    )
    if surface == "ecommerce_detail" and is_title_noise(js_state_record.get("title")):
        js_state_record = dict(js_state_record)
        js_state_record.pop("title", None)
    return PreparedDetailExtraction(
        context=context,
        dom_parser=dom_parser,
        soup=soup,
        raw_soup=raw_soup,
        state=state,
        js_state_objects=js_state_objects,
        js_state_record=js_state_record,
        selector_self_heal=_selector_self_heal_config(extraction_runtime_snapshot),
    )


def _apply_prepared_dom_fallbacks(
    prepared: PreparedDetailExtraction,
    *,
    selector_rules: list[dict[str, object]] | None,
) -> None:
    apply_dom_fallbacks(
        prepared.dom_parser,
        prepared.soup,
        page_url=prepared.state.page_url,
        surface=prepared.state.surface,
        requested_fields=prepared.state.requested_fields,
        candidates=prepared.state.candidates,
        candidate_sources=prepared.state.candidate_sources,
        field_sources=prepared.state.field_sources,
        selector_trace_candidates=prepared.state.selector_trace_candidates,
        selector_rules=selector_rules,
        add_sourced_candidate=_add_sourced_candidate,
        breadcrumb_soup=prepared.raw_soup,
    )


def _extract_prepared_dom_variants(
    soup: BeautifulSoup,
    *,
    page_url: str,
    prepared: PreparedDetailExtraction,
) -> dict[str, object]:
    return _extract_variants_from_dom(
        soup,
        page_url=page_url,
        js_state_objects=prepared.js_state_objects,
    )


def build_detail_record(
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    *,
    requested_page_url: str | None = None,
    adapter_records: list[dict[str, Any]] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
) -> dict[str, Any]:
    prepared = _prepare_detail_extraction(
        html,
        page_url,
        surface,
        requested_fields,
        requested_page_url=requested_page_url,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
    )
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    tier_executor = DetailTierExecutor(
        DetailTierRuntime(
            materialize_record=_materialize_record,
            collect_record_candidates=_collect_record_candidates,
            map_network_payloads_to_fields=map_network_payloads_to_fields,
            collect_structured_source_payloads=collect_structured_source_payloads,
            collect_structured_payload_candidates=_collect_structured_payload_candidates,
            apply_dom_fallbacks=_apply_prepared_dom_fallbacks,
            extract_variants_from_dom=(
                lambda soup, *, page_url: _extract_prepared_dom_variants(
                    soup,
                    page_url=page_url,
                    prepared=prepared,
                )
            ),
            should_collect_dom_variants=_should_collect_dom_variants,
            add_sourced_candidate=_add_sourced_candidate,
            coerce_float=_coerce_float,
            requires_dom_completion=_requires_dom_completion,
            promote_dom_detail_title=_promote_dom_detail_title,
            fill_missing_dom_detail_title=_fill_missing_dom_detail_title,
            finalize_early_detail_record=_finalize_early_detail_record,
            finalize_dom_detail_record=_finalize_dom_detail_record,
        )
    )
    return tier_executor.build_record(
        prepared,
        DetailTierInputs(
            adapter_records=adapter_records,
            network_payloads=network_payloads,
            alias_lookup=alias_lookup,
            selector_rules=selector_rules,
            html=html,
            page_url=page_url,
            surface=surface,
            requested_fields=requested_fields,
        ),
    )


def detail_record_rejection_reason(
    record: dict[str, Any],
    *,
    page_url: str,
    requested_page_url: str | None = None,
) -> str | None:
    if _detail_redirect_identity_is_mismatched(
        record,
        page_url=page_url,
        requested_page_url=requested_page_url,
    ):
        return "detail_identity_mismatch"
    if _looks_like_site_shell_record(record, page_url=page_url):
        if (
            _detail_url_has_multiple_product_segments(page_url)
            or _detail_url_is_collection_like(page_url)
            or _detail_url_is_utility(page_url)
        ):
            return "non_detail_seed"
        return "detail_shell"
    return None


def infer_detail_failure_reason(
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    *,
    requested_page_url: str | None = None,
    adapter_records: list[dict[str, Any]] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
) -> str | None:
    if "detail" not in str(surface or "").strip().lower():
        return None
    record = build_detail_record(
        html,
        page_url,
        surface,
        requested_fields,
        requested_page_url=requested_page_url,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
    )
    return detail_record_rejection_reason(
        record,
        page_url=page_url,
        requested_page_url=requested_page_url,
    )


def extract_detail_records(
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None = None,
    *,
    requested_page_url: str | None = None,
    adapter_records: list[dict[str, Any]] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
) -> list[dict[str, Any]]:
    record = build_detail_record(
        html,
        page_url,
        surface,
        requested_fields,
        requested_page_url=requested_page_url,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
    )
    if surface == "ecommerce_detail" and _looks_like_site_shell_record(
        record,
        page_url=page_url,
    ):
        return []
    if surface == "ecommerce_detail" and _detail_redirect_identity_is_mismatched(
        record,
        page_url=page_url,
        requested_page_url=requested_page_url,
    ):
        return []
    if (
        surface == "ecommerce_detail"
        and record.get("_irrelevant_detail_structured_product")
        and len(
            _detail_identity_tokens(
                _detail_title_from_url(requested_page_url or page_url)
            )
        )
        >= 2
        and not _record_matches_requested_detail_identity(
            record,
            requested_page_url=requested_page_url or page_url,
        )
    ):
        return []
    if record_score(record) <= 0:
        return []
    return [record]
