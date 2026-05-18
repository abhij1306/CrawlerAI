from __future__ import annotations

__all__ = ("apply_dom_fallbacks",)

import re
from collections.abc import Callable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.config.extraction_rules import DETAIL_DOM_SCALAR_SIZE_PATTERN
from app.services.dom.selector_engine import (
    apply_selector_fallbacks,
    extract_feature_rows,
    extract_heading_sections,
    extract_page_images,
)
from app.services.extract.detail.assembly import dom_section_targets as _section_targets
from app.services.extract.content_surface_extractor import (
    CONTENT_DETAIL_SURFACES,
    extract as extract_content_surface,
)
from app.services.extract.detail.price.inline_scalar import collect_inline_scalar_rows
from app.services.extract.detail.assembly.raw_signals import (
    breadcrumb_category_from_dom,
    gender_from_detail_context,
)
from app.services.shared.field_coerce import (
    RATING_RE,
    REVIEW_COUNT_RE,
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_currency_code,
    is_title_noise,
    surface_alias_lookup,
    surface_fields,
    text_or_none,
)

_dom_section_target_fields = _section_targets._dom_section_target_fields


def apply_dom_fallbacks(
    dom_parser: LexborHTMLParser,
    soup: BeautifulSoup,
    *,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    selector_rules: list[dict[str, object]] | None,
    add_sourced_candidate: Callable[..., None],
    breadcrumb_soup: BeautifulSoup | None = None,
) -> None:
    fields = surface_fields(surface, requested_fields)
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface in CONTENT_DETAIL_SURFACES:
        for field_name, value in extract_content_surface(
            soup,
            page_url=page_url,
            surface=normalized_surface,
        ).items():
            if field_name in fields:
                add_sourced_candidate(
                    candidates,
                    candidate_sources,
                    field_sources,
                    field_name,
                    coerce_field_value(field_name, value, page_url),
                    source="dom_text",
                )
        return
    # ``prune_irrelevant_detail_dom_nodes`` may decompose the body H1 on the
    # BeautifulSoup without touching the selectolax parser cache. Mirror that
    # decision here so the DOM fallback cannot resurrect a title from a page
    # whose primary structured evidence pointed to a different product.
    h1_in_soup = soup.select_one("h1") if soup is not None else None
    h1 = dom_parser.css_first("h1") if h1_in_soup is not None else None
    page_title = dom_parser.css_first("title") if h1_in_soup is not None else None
    h1_title = text_or_none(h1.text(separator=" ", strip=True) if h1 else "")
    page_title_text = text_or_none(
        page_title.text(separator=" ", strip=True) if page_title else ""
    )
    title = next(
        (
            candidate
            for candidate in (h1_title, page_title_text)
            if candidate and not is_title_noise(candidate)
        ),
        None,
    )
    if title:
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            "title",
            title,
            source="dom_h1",
        )
    apply_selector_fallbacks(
        soup,
        page_url,
        surface,
        requested_fields,
        candidates,
        selector_rules=selector_rules,
        candidate_sources=candidate_sources,
        field_sources=field_sources,
        selector_trace_candidates=selector_trace_candidates,
    )
    canonical = soup.find("link", attrs={"rel": re.compile("canonical", re.I)})
    canonical_href = canonical.get("href") if canonical is not None else None
    if canonical_href:
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            "url",
            absolute_url(page_url, canonical_href),
            source="dom_canonical",
        )
    images = extract_page_images(
        soup,
        page_url,
        exclude_linked_detail_images="detail" in str(surface or "").strip().lower(),
        surface=surface,
    )
    if images:
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            "image_url",
            images[0],
            source="dom_images",
        )
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            "additional_images",
            images[1:],
            source="dom_images",
        )
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    inline_scalar_target_fields = {
        field_name
        for field_name in ("color", "size")
        if field_name in fields and not candidates.get(field_name)
    }
    for field_name, value in collect_inline_scalar_rows(
        soup,
        alias_lookup,
        allowed_fields=inline_scalar_target_fields,
    ):
        if field_name not in fields or candidates.get(field_name):
            continue
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            field_name,
            coerce_field_value(field_name, value, page_url),
            source="dom_text",
        )
    dom_section_fields = _dom_section_target_fields(
        surface,
        requested_fields,
    )
    section_target_fields = {field for field in fields if field in dom_section_fields}
    for label, value in extract_heading_sections(
        soup,
        alias_lookup=alias_lookup,
        allowed_fields=section_target_fields,
    ).items():
        normalized = alias_lookup.get(label.lower()) or alias_lookup.get(
            re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        )
        if normalized:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                normalized,
                coerce_field_value(normalized, value, page_url),
                source="dom_sections",
            )
    if "features" in fields:
        feature_rows = extract_feature_rows(soup)
        if feature_rows:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "features",
                feature_rows,
                source="dom_sections",
            )
    breadcrumb_category = breadcrumb_category_from_dom(
        breadcrumb_soup or soup,
        current_title=title,
        page_url=page_url,
    )
    if "category" in fields and breadcrumb_category:
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            "category",
            breadcrumb_category,
            source="dom_breadcrumb",
        )
    if "gender" in fields and not candidates.get("gender"):
        gender = gender_from_detail_context(
            breadcrumb_category, title, urlsplit(page_url).path
        )
        if gender:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "gender",
                gender,
                source="dom_text",
            )
    body_text = ""
    body_text_needed = (
        ("size" in fields and not candidates.get("size"))
        or ("review_count" in fields and not candidates.get("review_count"))
        or ("rating" in fields and not candidates.get("rating"))
        or (
            normalized_surface.startswith("job_")
            and "remote" in fields
            and not candidates.get("remote")
        )
    )
    if body_text_needed:
        body_node = dom_parser.body
        body_text = (
            clean_text(body_node.text(separator=" ", strip=True)) if body_node else ""
        )
    if "size" in fields and not candidates.get("size"):
        size_match = re.search(str(DETAIL_DOM_SCALAR_SIZE_PATTERN), body_text, re.I)
        if size_match:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "size",
                coerce_field_value("size", size_match.group(1), page_url),
                source="dom_text",
            )
    if "currency" in fields and not candidates.get("currency"):
        for price_value in list(candidates.get("price") or []):
            currency_code = extract_currency_code(price_value)
            if not currency_code:
                continue
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "currency",
                currency_code,
                source="dom_text",
            )
            break
    if "review_count" in fields and not candidates.get("review_count"):
        review_match = REVIEW_COUNT_RE.search(body_text)
        if review_match:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "review_count",
                review_match.group(1),
                source="dom_text",
            )
    if "rating" in fields and not candidates.get("rating"):
        rating_match = RATING_RE.search(body_text)
        if rating_match:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "rating",
                rating_match.group(1),
                source="dom_text",
            )
    if (
        normalized_surface.startswith("job_")
        and "remote" in fields
        and not candidates.get("remote")
    ):
        lowered = body_text.lower()
        if "remote" in lowered or "work from home" in lowered:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                "remote",
                "remote",
                source="dom_text",
            )
