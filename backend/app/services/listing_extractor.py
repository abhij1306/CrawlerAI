from __future__ import annotations
import re
import logging
from typing import Any
from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser, SelectolaxError

from app.services.config.extraction_rules import (
    EXTRACTION_RULES,
    LISTING_STRUCTURE_NEGATIVE_HINTS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extraction_context import (
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.extract.article_card_parser import (
    article_card_date,
    article_card_summary,
    article_card_text,
)
from app.services.extract.structured_listing_handler import (
    allow_embedded_json_listing_payloads,
    extract_structured_listing,
)
from app.services.extract.listing_candidate_ranking import (
    best_listing_candidate_set,
    listing_record_supported,
    looks_like_utility_record,
)
from app.services.extract.listing_signals import (
    card_title_node,
    card_title_score,
    extract_brand_signal_from_card,
    extract_image_title_hint,
    extract_label_value_pairs_from_node,
    extract_page_images_from_node,
    extract_price_signal_from_card,
    normalize_listing_title,
    same_url_anchor_text_candidates,
    select_primary_anchor,
    select_primary_card_url,
    should_replace_title_with_image_hint,
    title_token_overlap,
    title_from_url,
)
from app.services.extract.listing_integrity_gate import (
    IntegrityDecision,
    evaluate_listing_integrity,
)
from app.services.extract.detail.identity.core import (
    listing_detail_like_path,
    listing_url_is_structural,
)
from app.services.extract.listing_card_fragments import (
    listing_card_html_fragments,
    listing_fragment_structural_signature,
    listing_node_attr,
    listing_node_css,
    listing_node_html as _node_html,
    listing_node_signature as _node_signature,
    listing_node_tag as _node_tag,
    listing_node_text,
    select_listing_fragment_nodes,
)
from app.services.extract.listing_visual import visual_listing_records
from app.services.extract.content_listing_handler import has_table_row_intent, table_row_records
from app.services.extract.detail.price.core import currency_hint_from_page_url
from app.services.field_policy import normalize_requested_field
from app.services.shared.field_coerce import (
    PRICE_RE,
    RATING_RE,
    REVIEW_COUNT_RE,
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_currency_code,
    extract_price_text,
    finalize_record,
    is_title_noise,
    same_host,
    surface_alias_lookup,
    surface_fields,
)
from app.services.field_url_normalization import same_site
from app.services.extract.field_candidates import (
    add_candidate,
    finalize_candidate_value,
)
from app.services.dom.selector_engine import apply_selector_fallbacks

logger = logging.getLogger(__name__)
_LISTING_STRUCTURE_NEGATIVE_HINTS = frozenset(LISTING_STRUCTURE_NEGATIVE_HINTS)


def _resolve_selector_trace(
    field_name: str,
    finalized_value: object,
    selector_trace_candidates: dict[str, list[dict[str, object]]],
) -> dict[str, object] | None:
    traces = list(selector_trace_candidates.get(field_name) or [])
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        if trace.get("_candidate_value") == finalized_value:
            return {
                key: value for key, value in trace.items() if not str(key).startswith("_")
            }
    trace = next((row for row in traces if isinstance(row, dict)), {})
    if not isinstance(trace, dict):
        return None
    return {key: value for key, value in trace.items() if not str(key).startswith("_")}


def _is_title_only_candidate_allowed(
    *,
    is_job: bool,
    anchor_score: int,
    title_score: int,
    cleaned_title: str,
    cleaned_url: str,
    page_url: str,
) -> bool:
    return (
        not is_job
        and anchor_score >= 10
        and title_score >= 10
        and len(re.findall(r"[a-z0-9]+", cleaned_title, flags=re.I)) >= 3
        and not listing_url_is_structural(cleaned_url, page_url)
        and not looks_like_utility_record(
            title=cleaned_title,
            url=cleaned_url,
        )
        and not re.match(
            r"^(?:article|flyer|guide|manual|resource)\s*:", cleaned_title, flags=re.I
        )
        and not re.search(r"\.(?:pdf|docx?|pptx?)(?:$|[?#])", cleaned_url, flags=re.I)
        and not any(
            token in cleaned_url.lower()
            for token in (
                "/article/",
                "/articles/",
                "/assets/",
                "/deepweb/",
                "/technical-documents/",
                "/technical-article/",
            )
        )
        and title_token_overlap(cleaned_title, title_from_url(cleaned_url) or "") >= 2
    )


def _surface_has_dom_fallback_patterns(surface: str) -> bool:
    dom_patterns_raw = EXTRACTION_RULES.get("dom_patterns")
    dom_patterns = dict(dom_patterns_raw) if isinstance(dom_patterns_raw, dict) else {}
    return any(
        str(dom_patterns.get(field_name) or "").strip()
        for field_name in surface_fields(surface, None)
    )


def _build_card_candidates(
    card,
    *,
    page_url: str,
    surface: str,
    is_job: bool,
    title: str,
    url: str,
    selector_rules: list[dict[str, object]] | None,
    image_urls: list[str],
    best_same_url_text: str | None,
    same_url_texts: list[str],
    card_text: str,
) -> tuple[dict[str, list[object]], dict[str, list[dict[str, object]]]]:
    alias_lookup = surface_alias_lookup(surface, None)
    candidates: dict[str, list[object]] = {"title": [title], "url": [url]}
    selector_trace_candidates: dict[str, list[dict[str, object]]] = {}
    card_soup: BeautifulSoup | None = None
    needs_card_soup = (
        bool(selector_rules)
        or surface in {"article_listing", "content_listing"}
        or _surface_has_dom_fallback_patterns(surface)
    )
    if needs_card_soup:
        card_soup = BeautifulSoup(str(getattr(card, "html", "") or ""), "html.parser")
    if card_soup is not None:
        apply_selector_fallbacks(
            card_soup,
            page_url,
            surface,
            None,
            candidates,
            selector_rules=selector_rules,
            selector_trace_candidates=selector_trace_candidates,
        )
    if surface == "article_listing" and card_soup is not None:
        author = article_card_text(
            card_soup, [".author", ".byline", "[rel='author']", "[itemprop='author']"]
        )
        if author:
            add_candidate(candidates, "author", author)
        publication_date = article_card_date(card_soup)
        if publication_date:
            add_candidate(candidates, "publication_date", publication_date)
        summary = article_card_summary(card_soup, title)
        if summary:
            add_candidate(candidates, "summary", summary)
    elif surface == "content_listing" and card_soup is not None:
        summary = article_card_summary(card_soup, title)
        if summary:
            add_candidate(candidates, "summary", summary)
    if not is_job and not candidates.get("brand"):
        brand_text = extract_brand_signal_from_card(card, title)
        if brand_text:
            add_candidate(candidates, "brand", brand_text)
    if image_urls and not candidates.get("image_url"):
        add_candidate(candidates, "image_url", image_urls[0])
    if best_same_url_text and not candidates.get("description"):
        description_text = next(
            (
                text
                for text in same_url_texts
                if text != title
                and len(text) >= 20
                and len(re.findall(r"[a-z0-9]+", text, flags=re.I)) >= 3
                and not PRICE_RE.search(text)
                and not is_title_noise(text)
                and (
                    title_token_overlap(text, title) >= 2
                    or len(re.findall(r"[a-z0-9]+", text, flags=re.I)) >= 5
                )
            ),
            None,
        )
        if description_text:
            add_candidate(candidates, "description", description_text)
    for label, value in extract_label_value_pairs_from_node(card):
        normalized_label = normalize_requested_field(label)
        if not normalized_label:
            normalized_label = clean_text(label).lower().replace(" ", "_")
        canonical = alias_lookup.get(normalized_label)
        if canonical:
            add_candidate(
                candidates,
                canonical,
                coerce_field_value(canonical, value, page_url),
            )
    if not is_job and not candidates.get("price"):
        price_text = extract_price_signal_from_card(card)
        if price_text:
            add_candidate(candidates, "price", price_text)
    if not is_job and not candidates.get("currency"):
        for price_value in list(candidates.get("price") or []):
            currency_code = extract_currency_code(price_value)
            if currency_code:
                add_candidate(candidates, "currency", currency_code)
                break
        else:
            inferred_currency = currency_hint_from_page_url(page_url)
            if inferred_currency and candidates.get("price"):
                add_candidate(candidates, "currency", inferred_currency)
    if is_job and not candidates.get("salary"):
        salary_match = PRICE_RE.search(card_text)
        if salary_match:
            add_candidate(candidates, "salary", salary_match.group(0))
    if not candidates.get("rating"):
        rating_match = RATING_RE.search(card_text)
        if rating_match:
            add_candidate(candidates, "rating", rating_match.group(1))
    if not candidates.get("review_count"):
        review_match = REVIEW_COUNT_RE.search(card_text)
        if review_match:
            add_candidate(candidates, "review_count", review_match.group(1))
    return candidates, selector_trace_candidates


def _listing_record_from_card(
    card,
    page_url: str,
    surface: str,
    *,
    selector_rules: list[dict[str, object]] | None = None,
) -> dict[str, Any] | None:
    is_job = surface.startswith("job_")
    title_node = card_title_node(card)
    primary_anchor = select_primary_anchor(
        card,
        page_url,
        surface=surface,
        title_node=title_node,
    )
    if primary_anchor is None:
        fallback_url = select_primary_card_url(card, page_url)
        if not fallback_url or title_node is None:
            return None
        primary_anchor = (
            title_node,
            fallback_url,
            clean_text(listing_node_text(title_node)),
            max(10, card_title_score(title_node) + 4),
        )
    anchor_node, url, anchor_text, anchor_score = primary_anchor
    title_node = title_node or anchor_node
    title_score = card_title_score(title_node)
    image_title_hint = extract_image_title_hint(card, page_url=page_url)
    title = clean_text(
        listing_node_attr(title_node, "title")
        or listing_node_attr(title_node, "alt")
        or listing_node_text(title_node)
        or anchor_text
    )
    same_url_texts = same_url_anchor_text_candidates(card, url)
    best_same_url_text = next(
        (
            text
            for text in sorted(same_url_texts, key=len, reverse=True)
            if len(re.findall(r"[a-z0-9]+", text, flags=re.I)) >= 3
            and not PRICE_RE.search(text)
            and not is_title_noise(text)
        ),
        None,
    )
    if best_same_url_text and (
        len(re.findall(r"[a-z0-9]+", title, flags=re.I)) < 3 or is_title_noise(title)
    ):
        title = best_same_url_text
    if should_replace_title_with_image_hint(title, image_title_hint):
        title = clean_text(image_title_hint)
    title = normalize_listing_title(title)
    if len(title) < 4 or is_title_noise(title):
        return None
    if anchor_score < 4 and title_score < 8:
        return None
    card_text = listing_node_text(card)
    image_urls = extract_page_images_from_node(card, page_url)
    has_supporting_listing_signals = bool(
        PRICE_RE.search(card_text)
        or RATING_RE.search(card_text)
        or REVIEW_COUNT_RE.search(card_text)
        or image_urls
    )
    if not listing_detail_like_path(url, is_job=is_job):
        if is_job and anchor_score < 8:
            if not any(
                token in card_text.lower()
                for token in ("salary", "remote", "location", "apply")
            ):
                return None
        if (
            not is_job
            and anchor_score < 8
            and not has_supporting_listing_signals
            and title_score < 8
        ):
            return None
    candidates, selector_trace_candidates = _build_card_candidates(
        card,
        page_url=page_url,
        surface=surface,
        is_job=is_job,
        title=title,
        url=url,
        selector_rules=selector_rules,
        image_urls=image_urls,
        best_same_url_text=best_same_url_text,
        same_url_texts=same_url_texts,
        card_text=card_text,
    )
    record: dict[str, Any] = {
        "source_url": page_url,
        "_source": "dom_listing",
    }
    selected_selector_traces: dict[str, dict[str, object]] = {}
    for field_name in surface_fields(surface, None):
        finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
            selector_trace = _resolve_selector_trace(
                field_name,
                finalized,
                selector_trace_candidates,
            )
            if selector_trace:
                selected_selector_traces[field_name] = selector_trace
    if selected_selector_traces:
        record["_selector_traces"] = selected_selector_traces
    cleaned = finalize_record(record, surface=surface)
    if not cleaned.get("url") or not cleaned.get("title"):
        return None
    cleaned_title = clean_text(cleaned.get("title"))
    cleaned_url = str(cleaned.get("url") or "").strip()
    allow_title_only_dom_candidate = _is_title_only_candidate_allowed(
        is_job=is_job,
        anchor_score=anchor_score,
        title_score=title_score,
        cleaned_title=cleaned_title,
        cleaned_url=cleaned_url,
        page_url=page_url,
    )
    if not listing_record_supported(
        cleaned,
        page_url=page_url,
        surface=surface,
        title_is_noise=is_title_noise,
        url_is_structural=listing_url_is_structural,
        detail_like_url=(
            lambda url: listing_detail_like_path(
                url,
                is_job=surface.startswith("job_"),
            )
        ),
    ):
        if not allow_title_only_dom_candidate:
            return None
    cleaned["_structural_signature"] = listing_fragment_structural_signature(
        card,
        url=cleaned_url,
    )
    return cleaned


def _detail_anchor_count(
    parser: LexborHTMLParser,
    *,
    page_url: str,
    surface: str,
    fallback_fragment_limit: int,
) -> int:
    is_job = surface.startswith("job_")
    seen_urls: set[str] = set()
    count = 0
    for card in listing_card_html_fragments(
        parser,
        is_job=is_job,
        fallback_fragment_limit=fallback_fragment_limit,
    ):
        primary_anchor = select_primary_anchor(card, page_url, surface=surface)
        if primary_anchor is None:
            continue
        url = str(primary_anchor[1] or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        if listing_detail_like_path(url, is_job=is_job):
            count += 1
    return count


def _attach_gate_decision_to_artifacts(
    artifacts: dict[str, object] | None,
    decision: IntegrityDecision | None,
) -> None:
    """Attach the integrity gate decision to the artifacts dict under key ``listing_integrity``."""
    if artifacts is None:
        return
    if decision is None or not isinstance(decision, IntegrityDecision):
        artifacts["listing_integrity"] = {
            "outcome": "unknown",
            "reason": "invalid_decision",
            "metrics": {},
        }
        return
    artifacts["listing_integrity"] = {
        "outcome": decision.outcome,
        "reason": decision.reason,
        "metrics": decision.metrics,
    }


def apply_listing_integrity_gate(
    records: list[dict[str, Any]],
    *,
    page_url: str,
    surface: str,
    artifacts: dict[str, object] | None = None,
) -> list[dict[str, Any]]:
    if not records:
        _attach_gate_decision_to_artifacts(artifacts, None)
        return []
    try:
        decision = evaluate_listing_integrity(
            records, page_url=page_url, surface=surface
        )
    except Exception:
        logger.error(
            "evaluate_listing_integrity failed for page_url=%s surface=%s records=%d",
            page_url,
            surface,
            len(records),
            exc_info=True,
        )
        decision = None
    _attach_gate_decision_to_artifacts(artifacts, decision)
    if decision is not None and decision.outcome == "promo_only_cluster":
        return []
    return [_strip_listing_integrity_internals(record) for record in records]


def _strip_listing_integrity_internals(record: dict[str, Any]) -> dict[str, Any]:
    if "_structural_signature" not in record:
        return record
    cleaned = dict(record)
    cleaned.pop("_structural_signature", None)
    return cleaned


def _structured_listing_stage(
    context: Any,
    *,
    page_url: str,
    surface: str,
    max_records: int,
    listing_min_items: int,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for source_name, source_payloads in collect_structured_source_payloads(
        context,
        page_url=page_url,
        surface=surface,
    ):
        if source_name == "js_state":
            continue
        payload_list = [
            payload for payload in list(source_payloads) if isinstance(payload, dict)
        ]
        if (
            source_name == "embedded_json"
            and not allow_embedded_json_listing_payloads(
                payload_list,
                listing_min_items=listing_min_items,
            )
        ):
            continue
        payloads.extend(payload_list)
    return extract_structured_listing(
        payloads,
        page_url,
        surface,
        max_records=max_records,
        listing_min_items=listing_min_items,
    )


def _dom_listing_stage(
    parser: LexborHTMLParser,
    *,
    page_url: str,
    surface: str,
    is_job_surface: bool,
    max_records: int,
    fallback_fragment_limit: int,
    selector_rules: list[dict[str, object]] | None,
    seed_urls: set[str] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    skipped_urls: set[str] = set(seed_urls or ())
    records_by_url: dict[str, dict[str, Any]] = {}
    for card in listing_card_html_fragments(
        parser,
        is_job=is_job_surface,
        fallback_fragment_limit=fallback_fragment_limit,
        limit=max_records,
    ):
        record = _listing_record_from_card(
            card,
            page_url,
            surface,
            selector_rules=selector_rules,
        )
        if record is None:
            continue
        url = str(record.get("url") or "")
        if not url:
            continue
        existing = records_by_url.get(url)
        if existing is not None:
            for key, value in record.items():
                if key not in existing or existing.get(key) in (None, "", [], {}):
                    existing[key] = value
            continue
        if url in skipped_urls:
            continue
        skipped_urls.add(url)
        records_by_url[url] = record
        records.append(record)
    return records


def extract_listing_records(
    html: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    artifacts: dict[str, object] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
) -> list[dict[str, Any]]:
    del network_payloads
    if surface == "content_listing":
        table_records = table_row_records(html, page_url, max_records=max_records)
        if table_records:
            return table_records
        # Table intent prevents falling back to unrelated DOM cards when table parsing finds no records.
        table_row_intent = has_table_row_intent(html)
    else:
        table_row_intent = False
    context = prepare_extraction_context(html)
    dom_parser = context.dom_parser
    is_job_surface = surface.startswith("job_")
    listing_fallback_fragment_limit = int(
        crawler_runtime_settings.listing_fallback_fragment_limit
    )
    listing_min_items = int(crawler_runtime_settings.listing_min_items)
    if not listing_card_html_fragments(
        dom_parser,
        is_job=is_job_surface,
        fallback_fragment_limit=listing_fallback_fragment_limit,
        limit=max_records,
    ):
        original_parser = context.original_dom_parser
        if listing_card_html_fragments(
            original_parser,
            is_job=is_job_surface,
            fallback_fragment_limit=listing_fallback_fragment_limit,
            limit=max_records,
        ):
            logger.debug(
                "Using original listing DOM after cleaned DOM lost card fragments for %s",
                page_url,
            )
            dom_parser = original_parser

    structured_records = _structured_listing_stage(
        context,
        page_url=page_url,
        surface=surface,
        max_records=max_records,
        listing_min_items=listing_min_items,
    )
    dom_records = _dom_listing_stage(
        dom_parser,
        page_url=page_url,
        surface=surface,
        is_job_surface=is_job_surface,
        max_records=max_records,
        fallback_fragment_limit=listing_fallback_fragment_limit,
        selector_rules=selector_rules,
    )
    original_dom_records: list[dict[str, Any]] = []
    if context.original_html and context.original_html != context.cleaned_html:
        original_parser = context.original_dom_parser
        cleaned_detail_anchor_count = _detail_anchor_count(
            dom_parser,
            page_url=page_url,
            surface=surface,
            fallback_fragment_limit=listing_fallback_fragment_limit,
        )
        original_detail_anchor_count = _detail_anchor_count(
            original_parser,
            page_url=page_url,
            surface=surface,
            fallback_fragment_limit=listing_fallback_fragment_limit,
        )
        if original_detail_anchor_count >= max(3, cleaned_detail_anchor_count + 2):
            original_dom_records = _dom_listing_stage(
                original_parser,
                page_url=page_url,
                surface=surface,
                is_job_surface=is_job_surface,
                max_records=max_records,
                fallback_fragment_limit=listing_fallback_fragment_limit,
                selector_rules=selector_rules,
            )
            logger.debug(
                "Using original listing DOM after cleaned DOM lost detail-link evidence for %s",
                page_url,
            )
    rendered_fragments = (
        artifacts.get("rendered_listing_fragments")
        if isinstance(artifacts, dict)
        else None
    )
    rendered_dom_records: list[dict[str, Any]] = []
    if isinstance(rendered_fragments, list):
        rendered_fragment_html = "\n".join(
            fragment
            for fragment in (str(item or "").strip() for item in rendered_fragments)
            if fragment
        )
        if rendered_fragment_html:
            rendered_parser = LexborHTMLParser(
                f"<html><body>{rendered_fragment_html}</body></html>"
            )
            rendered_dom_records = _dom_listing_stage(
                rendered_parser,
                page_url=page_url,
                surface=surface,
                is_job_surface=is_job_surface,
                max_records=max_records,
                fallback_fragment_limit=listing_fallback_fragment_limit,
                selector_rules=selector_rules,
            )
    listing_visual_elements = (
        artifacts.get("listing_visual_elements")
        if isinstance(artifacts, dict)
        else None
    )
    visual_records = visual_listing_records(
        listing_visual_elements if isinstance(listing_visual_elements, list) else None,
        page_url=page_url,
        surface=surface,
        max_records=max_records,
        title_is_noise=is_title_noise,
        url_is_structural=listing_url_is_structural,
    )
    visual_records = [
        record
        for record in visual_records
        if listing_record_supported(
            record,
            page_url=page_url,
            surface=surface,
            title_is_noise=is_title_noise,
            url_is_structural=listing_url_is_structural,
            detail_like_url=(
                lambda url: listing_detail_like_path(
                    url,
                    is_job=surface.startswith("job_"),
                )
            ),
        )
    ]
    candidate_sets: list[tuple[str, list[dict[str, Any]]]] = [
        ("structured", structured_records),
        ("dom", dom_records),
        ("structured_plus_dom", [*dom_records, *structured_records]),
    ]
    if original_dom_records:
        candidate_sets.append(("original_dom", original_dom_records))
    if rendered_dom_records:
        candidate_sets.append(("rendered_dom", rendered_dom_records))
    if visual_records:
        candidate_sets.append(("visual", visual_records))
    best_records = best_listing_candidate_set(
        candidate_sets,
        page_url=page_url,
        surface=surface,
        max_records=max_records,
        title_is_noise=is_title_noise,
        url_is_structural=listing_url_is_structural,
        detail_like_url=lambda candidate_url: listing_detail_like_path(
            candidate_url,
            is_job=is_job_surface,
        ),
    )
    if table_row_intent and not best_records:
        # Preserve empty table-listing results instead of substituting non-table card records.
        return []
    return apply_listing_integrity_gate(
        best_records,
        page_url=page_url,
        surface=surface,
        artifacts=artifacts,
    )
