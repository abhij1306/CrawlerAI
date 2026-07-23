from __future__ import annotations

import logging

from app.extraction.documents import HtmlDocument, HtmlNode
from app.core.records.field_policy import (
    exact_requested_field_key,
    normalize_field_key,
    normalize_requested_field,
)
from app.core.shared.field_coerce import clean_text, surface_fields

logger = logging.getLogger(__name__)


def requested_content_extractability(
    document: HtmlDocument,
    *,
    surface: str,
    requested_fields: list[str] | None,
    selector_rules: list[dict[str, object]] | None = None,
    probe_fields: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, object]:
    requested = {
        normalized
        for value in requested_fields or []
        for normalized in (
            exact_requested_field_key(value),
            normalize_requested_field(value),
        )
        if normalized
    }
    fields = (
        [
            field_name
            for field_name in (
                normalize_field_key(str(value or "")) for value in probe_fields or []
            )
            if field_name
        ]
        if probe_fields is not None
        else surface_fields(surface, requested_fields)
    )
    field_scope = set(fields)
    recipe_fields = _recipe_fields_with_content(
        document,
        selector_rules=selector_rules,
        field_scope=field_scope,
    )
    heuristic_fields = _heuristic_fields_with_content(document, field_scope)
    extractable_fields = recipe_fields | heuristic_fields
    matched_requested_fields = sorted(requested & extractable_fields)
    return {
        "verified": bool(
            matched_requested_fields or (not requested and extractable_fields)
        ),
        "matched_requested_fields": matched_requested_fields,
        "extractable_fields": sorted(extractable_fields),
        "section_fields": [],
        "dom_pattern_fields": sorted(heuristic_fields),
        "selector_backed_fields": sorted(recipe_fields),
    }


def _recipe_fields_with_content(
    doc: HtmlDocument,
    *,
    selector_rules: list[dict[str, object]] | None,
    field_scope: set[str],
) -> set[str]:
    fields: set[str] = set()
    for row in selector_rules or []:
        if not isinstance(row, dict) or not bool(row.get("is_active", True)):
            continue
        field_name = normalize_field_key(str(row.get("field_name") or ""))
        selector = str(row.get("css_selector") or "").strip()
        if not field_name or field_name not in field_scope or not selector:
            continue
        if any(_node_has_value(node) for node in _safe_select(doc, selector)[:8]):
            fields.add(field_name)
    return fields


def _heuristic_fields_with_content(
    doc: HtmlDocument, field_scope: set[str]
) -> set[str]:
    selectors = {
        "title": ("h1", "[itemprop='name']", "[data-testid*='title' i]"),
        "name": ("h1", "[itemprop='name']"),
        "price": ("[itemprop='price']", "[class*='price' i]", "[data-price]"),
        "brand": ("[itemprop='brand']", "[class*='brand' i]"),
        "company": ("[class*='company' i]", "[data-testid*='company' i]"),
        "location": ("[class*='location' i]", "[data-testid*='location' i]"),
        "description": ("[itemprop='description']", "main", "article"),
    }
    fields: set[str] = set()
    for field_name, candidates in selectors.items():
        if field_name not in field_scope:
            continue
        for selector in candidates:
            if any(_node_has_value(node) for node in _safe_select(doc, selector)[:8]):
                fields.add(field_name)
                break
    return fields


def _safe_select(doc: HtmlDocument, selector: str) -> tuple[HtmlNode, ...]:
    try:
        return doc.css(selector)
    except Exception:
        logger.debug(
            "Extractability probe failed for selector %r; treating as no match",
            selector,
            exc_info=True,
        )
        return ()


def _node_has_value(node: HtmlNode) -> bool:
    if node.is_hidden():
        return False
    for attr in ("content", "value", "src", "href", "alt", "title", "aria-label"):
        if clean_text(node.attribute(attr)):
            return True
    return bool(clean_text(node.text(separator=" ", strip=True)))
