from __future__ import annotations

import logging
import re
from itertools import product
from urllib.parse import urlsplit
from collections.abc import Callable
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.config.extraction_rules import (
    DOM_VARIANT_CARTESIAN_COMBO_LIMIT,
    DOM_VARIANT_GROUP_LIMIT,
    DETAIL_DOM_SCALAR_SIZE_PATTERN,
    DETAIL_LONG_TEXT_RANK_FIELDS,
    DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR,
    VARIANT_CHOICE_OPTION_LIMIT,
    VARIANT_COMPONENT_SIZE_STYLE_LABELS,
)
from app.services.config.variant_migration_rules import (
    VARIANT_STRONG_OPTION_SELECTOR,
    VARIANT_WEAK_OPTION_SELECTOR,
)
from app.services.config.field_mappings import (
    DOM_HIGH_VALUE_FIELDS,
    DOM_OPTIONAL_CUE_FIELDS,
)
from app.services.field_policy import exact_requested_field_key, normalize_field_key
from app.services.shared.field_coerce import (
    RATING_RE,
    REVIEW_COUNT_RE,
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_currency_code,
    flatten_variants_for_public_output,
    is_title_noise,
    object_dict as _object_dict,
    object_list as _object_list,
    surface_alias_lookup,
    surface_fields,
    text_or_none,
)
from app.services.dom.selector_engine import (
    apply_selector_fallbacks,
    extract_feature_rows,
    extract_heading_sections,
    extract_page_images,
)
from app.services.extract.detail_raw_signals import (
    breadcrumb_category_from_dom,
    gender_from_detail_context,
)
from app.services.extract.content_surface_extractor import (
    CONTENT_DETAIL_SURFACES,
    extract as extract_content_surface,
)
from app.services.extract.detail_state_variant_targets import (
    state_variant_targets as _state_variant_targets,
)
from app.services.extract.detail_dom_variant_options import (
    merge_variant_option_state,
    node_attr_is_truthy,
    variant_option_availability,
    variant_option_url,
)
from app.services.extract.variant_group_validator import (
    VariantGroupValidator,
)
from app.services.extract.variant_dom_provenance import (
    build_variant_candidate_group,
    variant_option_node_types,
    weak_variant_option_node_allowed,
)
from app.services.js_state.helpers import select_variant
from app.services.extract.shared_variant_logic import (
    infer_variant_group_name_from_values,
    iter_variant_choice_groups,
    iter_variant_select_groups,
    merge_variant_pair,
    normalized_variant_axis_display_name,
    normalized_variant_axis_key,
    option_scalar_fields,
    public_variant_axis_fields,
    resolve_variants,
    resolve_variant_group_name,
    split_variant_axes,
    variant_axis_name_is_semantic,
    variant_dom_cues_present,
    variant_option_value_is_noise,
    variant_option_value_suffix_noise_patterns,
    variant_size_value_patterns,
)
from app.services.extract.detail_inline_scalar import collect_inline_scalar_rows

logger = logging.getLogger(__name__)


_VARIANT_TRANSPORT_FIELDS = (
    "sku",
    "price",
    "currency",
    "url",
    "image_url",
    "availability",
    "stock_quantity",
)


def _dom_section_target_fields(
    surface: str,
    requested_fields: list[str] | None,
) -> set[str]:
    normalized_surface = str(surface or "").strip().lower()
    targets = {
        str(field_name).strip()
        for field_name in {
            *set(DETAIL_LONG_TEXT_RANK_FIELDS),
            *set(DOM_HIGH_VALUE_FIELDS.get(normalized_surface) or ()),
            *set(DOM_OPTIONAL_CUE_FIELDS.get(normalized_surface) or ()),
        }
        if str(field_name).strip()
    }
    canonical_fields = set(surface_fields(surface, None))
    for raw_field_name in list(requested_fields or []):
        normalized_field = exact_requested_field_key(raw_field_name) or normalize_field_key(
            raw_field_name
        )
        if normalized_field and normalized_field not in canonical_fields:
            targets.add(normalized_field)
    return targets


def record_has_rich_existing_variants(record: dict[str, Any]) -> bool:
    variants = [
        row for row in _object_list(record.get("variants")) if isinstance(row, dict)
    ]
    if len(variants) < 2:
        return False
    return all(
        any(text_or_none(row.get(axis)) for axis in public_variant_axis_fields)
        and any(text_or_none(row.get(field)) for field in _VARIANT_TRANSPORT_FIELDS)
        for row in variants
    )


def _dom_variant_axis_allowed(axis_name: str) -> bool:
    return axis_name in public_variant_axis_fields or axis_name == "style"


def _dom_variant_group_name_allowed(group_name: str) -> bool:
    axis_name = normalized_variant_axis_key(group_name)
    return _dom_variant_axis_allowed(axis_name) or bool(
        _split_compound_axis_name(group_name)
    )


def primary_dom_context(
    context: Any,
    *,
    page_url: str,
) -> tuple[LexborHTMLParser, BeautifulSoup]:
    cleaned_parser = context.dom_parser
    cleaned_soup = context.soup
    if cleaned_parser.css_first(
        DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR
    ) or cleaned_soup.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR):
        return cleaned_parser, cleaned_soup
    original_parser = context.original_dom_parser
    original_soup = context.original_soup
    if not (
        original_parser.css_first(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR)
        or original_soup.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR)
    ):
        return cleaned_parser, cleaned_soup
    logger.debug(
        "Using original DOM after cleaned DOM lost primary content for %s", page_url
    )
    return original_parser, original_soup


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
    page_title = dom_parser.css_first("title")
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
    normalized_surface = str(surface or "")
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


def _resolve_dom_variant_group_name(node: Any) -> str:
    attribute_axis = _dom_variant_axis_from_attributes(node)
    if attribute_axis:
        return attribute_axis
    resolved = resolve_variant_group_name(node)
    if resolved and _dom_variant_group_name_allowed(resolved):
        return resolved
    if not hasattr(node, "select"):
        return resolved or ""
    for input_node in node.select("input[type='radio'], input[type='checkbox']")[:24]:
        attribute_axis = _dom_variant_axis_from_attributes(input_node)
        if attribute_axis:
            return attribute_axis
        input_resolved = resolve_variant_group_name(input_node)
        if input_resolved and _dom_variant_group_name_allowed(input_resolved):
            return input_resolved
    return resolved or ""


def _dom_variant_axis_from_attributes(node: Any) -> str:
    if node is None or not hasattr(node, "attrs"):
        return ""
    attrs = getattr(node, "attrs", {}) or {}
    parts: list[str] = []
    for key, value in attrs.items():
        key_text = str(key)
        parts.append(key_text)
        if value not in (None, "", [], {}) and key_text.lower() in {
            "class",
            "data-option-name",
            "data-qa",
            "data-qa-action",
            "data-testid",
            "data-test",
            "id",
            "name",
        }:
            parts.append(str(value))
    attr_blob = " ".join(parts).casefold()
    if "color" in attr_blob or "colour" in attr_blob:
        return "color"
    if "size" in attr_blob:
        return "size"
    return ""


def _strip_variant_option_value_suffix_noise(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    stripped = cleaned
    for pattern in variant_option_value_suffix_noise_patterns:
        stripped = pattern.sub("", stripped).strip()
    return stripped or cleaned


def _coerce_variant_option_value(
    axis_name: str,
    raw_value: object,
    *,
    page_url: str,
) -> str:
    if axis_name == "color":
        return _coerce_color_option_value(raw_value, page_url=page_url)
    if axis_name in option_scalar_fields:
        coerced = text_or_none(coerce_field_value(axis_name, raw_value, page_url))
        if coerced:
            return coerced
    return clean_text(raw_value)


def _coerce_color_option_value(raw_value: object, *, page_url: str) -> str:
    cleaned = clean_text(raw_value)
    if not cleaned:
        return ""
    for candidate in _color_option_value_candidates(cleaned):
        coerced = text_or_none(coerce_field_value("color", candidate, page_url))
        if coerced:
            return coerced
    return cleaned


def _color_option_value_candidates(value: str) -> list[str]:
    candidates: list[str] = []
    for pattern in (
        re.compile(r"\b(?:in|colour|color)\s*[:\-]?\s+(.+)$", flags=re.I),
        re.compile(r"\b(?:colour|color)\s*[:\-]\s*(.+)$", flags=re.I),
    ):
        match = pattern.search(value)
        if match is None:
            continue
        candidate = clean_text(match.group(1))
        if candidate:
            candidates.append(candidate)
    candidates.append(value)
    return list(dict.fromkeys(candidates))


def _component_size_style_from_group_name(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    lowered = cleaned.casefold()
    if "size" not in re.split(r"[^a-z0-9]+", lowered):
        return ""
    for label in tuple(VARIANT_COMPONENT_SIZE_STYLE_LABELS or ()):
        normalized_label = clean_text(label).casefold()
        if not normalized_label:
            continue
        if normalized_label in re.split(r"[^a-z0-9]+", lowered):
            return " ".join(part.capitalize() for part in normalized_label.split())
    return ""


def _prefer_axis_inferred_from_values(
    cleaned_name: str,
    values: list[str],
) -> str:
    inferred_name = infer_variant_group_name_from_values(values)
    if not inferred_name:
        return cleaned_name
    normalized_name = normalized_variant_axis_key(cleaned_name)
    if normalized_name == inferred_name:
        return cleaned_name
    normalized_values = {
        clean_text(value).casefold() for value in values if clean_text(value)
    }
    if clean_text(cleaned_name).casefold() in normalized_values:
        return inferred_name
    if {normalized_name, inferred_name} == {"color", "size"}:
        return inferred_name
    if normalized_name == "base" and inferred_name in {"color", "size"}:
        return inferred_name
    if not variant_axis_name_is_semantic(cleaned_name):
        return inferred_name
    return cleaned_name


def _variant_input_label(container: Any, input_node: Any) -> Any | None:
    input_id = (
        text_or_none(input_node.get("id")) if hasattr(input_node, "get") else None
    )
    if input_id:
        label = container.find("label", attrs={"for": input_id})
        if label is not None:
            return label
    if hasattr(input_node, "find_parent"):
        label = input_node.find_parent("label")
        if label is not None:
            return label
    sibling = getattr(input_node, "next_sibling", None)
    while sibling is not None:
        if getattr(sibling, "name", None) == "label":
            return sibling
        sibling = getattr(sibling, "next_sibling", None)
    return None


def _visible_node_text(
    node: Any | None,
    *,
    cache: dict[int, str] | None = None,
) -> str:
    if node is None or not hasattr(node, "get_text"):
        return ""
    cache_key = id(node)
    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    parsed = BeautifulSoup(str(node), "html.parser")
    for hidden in parsed.select(
        ".sr-only, .visually-hidden, [aria-hidden='true'], svg, title, use"
    ):
        hidden.decompose()
    visible_text = clean_text(parsed.get_text(" ", strip=True))
    if cache is not None:
        cache[cache_key] = visible_text
    return visible_text


def _collect_variant_choice_entries(
    container: Any, *, page_url: str
) -> list[dict[str, object]]:
    raw_group_name = _resolve_dom_variant_group_name(container)
    axis_name = normalized_variant_axis_key(raw_group_name)
    coercion_axis = (
        axis_name
        if axis_name in option_scalar_fields
        or axis_name in public_variant_axis_fields
        else "style"
    )
    entries_by_value: dict[str, dict[str, object]] = {}
    visible_text_cache: dict[int, str] = {}
    option_limit = int(VARIANT_CHOICE_OPTION_LIMIT)
    option_nodes = list(container.select(str(VARIANT_STRONG_OPTION_SELECTOR)))[
        :option_limit
    ]
    if len(option_nodes) < 2:
        option_nodes = list(container.select(str(VARIANT_WEAK_OPTION_SELECTOR)))[
            :option_limit
        ]
    for node in option_nodes:
        if not weak_variant_option_node_allowed(
            node,
            container=container,
            page_url=page_url,
        ):
            continue
        cleaned = _coerce_variant_option_value(
            coercion_axis,
            _variant_choice_entry_value(
                container,
                node,
                axis_name=coercion_axis,
                visible_text_cache=visible_text_cache,
            ),
            page_url=page_url,
        )
        cleaned = _strip_variant_option_value_suffix_noise(cleaned)
        if variant_option_value_is_noise(cleaned):
            continue
        entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
        merge_variant_option_state(
            entry,
            container=container,
            node=node,
            page_url=page_url,
        )
        variant_id = text_or_none(
            node.get("data-sku")
            or node.get("data-variant-id")
            or node.get("data-product-id")
        )
        if variant_id and entry.get("variant_id") in (None, "", [], {}):
            entry["variant_id"] = variant_id
    for input_node in container.select("input[type='radio'], input[type='checkbox']")[
        :option_limit
    ]:
        label_node = _variant_input_label(container, input_node)
        cleaned = _coerce_variant_option_value(
            coercion_axis,
            _variant_choice_entry_value(
                container,
                input_node,
                axis_name=coercion_axis,
                label_node=label_node,
                visible_text_cache=visible_text_cache,
            ),
            page_url=page_url,
        )
        cleaned = _strip_variant_option_value_suffix_noise(cleaned)
        if variant_option_value_is_noise(cleaned):
            continue
        entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
        merge_variant_option_state(
            entry,
            container=container,
            node=input_node,
            page_url=page_url,
            label_node=label_node,
        )
    return list(entries_by_value.values())


def _variant_choice_entry_value(
    container: Any,
    node: Any,
    *,
    axis_name: str,
    label_node: Any | None = None,
    visible_text_cache: dict[int, str] | None = None,
) -> str:
    resolved_label = label_node or _variant_input_label(container, node)
    label_text = _visible_node_text(resolved_label, cache=visible_text_cache)
    node_text = _visible_node_text(node, cache=visible_text_cache)
    aria_label = node.get("aria-label") if hasattr(node, "get") else None
    if axis_name == "color":
        for raw_value in (
            node.get("data-swatch-sr") if hasattr(node, "get") else None,
            aria_label,
            label_text,
            _descendant_image_alt_text(resolved_label),
            _descendant_image_alt_text(node),
            node_text,
        ):
            cleaned = clean_text(raw_value)
            if not cleaned:
                continue
            if candidate := _color_option_value_candidates(cleaned)[0]:
                return candidate
    return clean_text(
        node.get("data-attr-displayvalue")
        or node.get("data-displayvalue")
        or node.get("data-display-value")
        or node.get("data-swatch-sr")
        or node.get("data-size")
        or label_text
        or node.get("data-value")
        or node.get("data-option-value")
        or aria_label
        or node.get("value")
        or node_text
    )


def _descendant_image_alt_text(node: Any) -> str:
    if not hasattr(node, "find"):
        return ""
    image = node.find("img")
    if image is None or not hasattr(image, "get"):
        return ""
    return clean_text(image.get("alt"))


def _split_compound_axis_name(name: object) -> list[tuple[str, str]]:
    cleaned = clean_text(name)
    if not cleaned:
        return []
    parts = [
        clean_text(part)
        for part in re.split(r"\s*(?:&|/|\band\b)\s*", cleaned, flags=re.I)
        if clean_text(part)
    ]
    if len(parts) < 2:
        return []
    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for part in parts:
        if not variant_axis_name_is_semantic(part):
            return []
        axis_key = normalized_variant_axis_key(part)
        if not axis_key or axis_key in seen:
            return []
        seen.add(axis_key)
        resolved.append((axis_key, normalized_variant_axis_display_name(part) or part))
    return resolved if len(resolved) >= 2 else []


def _strip_variant_option_price_suffix(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    without_price = re.sub(r"\s*\([^)]*[\d][^)]*\)\s*$", "", cleaned).strip()
    return without_price or cleaned


def _split_compound_option_value(
    value: object,
    *,
    axis_keys: tuple[str, ...],
) -> dict[str, str] | None:
    cleaned = _strip_variant_option_price_suffix(value)
    if not cleaned or len(axis_keys) != 2 or "size" not in axis_keys:
        return None
    other_axis = next((axis for axis in axis_keys if axis != "size"), "")
    if not other_axis:
        return None
    tokens = [token for token in cleaned.split() if token]
    for width in range(min(3, len(tokens)), 0, -1):
        size_candidate = " ".join(tokens[-width:])
        if not any(
            pattern.fullmatch(size_candidate)
            for pattern in variant_size_value_patterns
        ):
            continue
        other_value = clean_text(" ".join(tokens[:-width]))
        if not other_value:
            return None
        return {
            other_axis: other_value,
            "size": size_candidate,
        }
    return None


def _expand_compound_option_group(
    group: dict[str, object],
) -> list[dict[str, object]] | None:
    axis_parts = _split_compound_axis_name(group.get("name"))
    if len(axis_parts) != 2:
        return None
    entries = [
        entry for entry in _object_list(group.get("entries")) if isinstance(entry, dict)
    ]
    if not entries:
        return None
    axis_keys = tuple(axis_key for axis_key, _ in axis_parts)
    parsed_rows: list[dict[str, str]] = []
    for entry in entries:
        parsed = _split_compound_option_value(entry.get("value"), axis_keys=axis_keys)
        if not parsed:
            return None
        parsed_rows.append(parsed)
    axis_values: dict[str, list[str]] = {axis_key: [] for axis_key, _ in axis_parts}
    observed_combos: set[tuple[str, ...]] = set()
    for parsed in parsed_rows:
        combo = tuple(parsed.get(axis_key, "") for axis_key, _ in axis_parts)
        if any(not value for value in combo):
            return None
        observed_combos.add(combo)
        for axis_key, _ in axis_parts:
            axis_value = parsed[axis_key]
            if axis_value not in axis_values[axis_key]:
                axis_values[axis_key].append(axis_value)
    expected_combo_count = 1
    for axis_key, _ in axis_parts:
        values = axis_values.get(axis_key) or []
        if len(values) < 2:
            return None
        expected_combo_count *= len(values)
    if (
        len(observed_combos) != len(parsed_rows)
        or len(observed_combos) != expected_combo_count
    ):
        return None
    return [
        {
            "name": display_name,
            "values": axis_values[axis_key],
            "entries": [{"value": axis_value} for axis_value in axis_values[axis_key]],
        }
        for axis_key, display_name in axis_parts
    ]


def extract_variants_from_dom(
    soup: BeautifulSoup,
    *,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> dict[str, object]:
    candidate_groups = []
    for select in iter_variant_select_groups(soup):
        raw_option_values = [
            clean_text(option.get_text(" ", strip=True))
            for option in select.find_all("option")
            if clean_text(option.get_text(" ", strip=True))
        ]
        cleaned_name = resolve_variant_group_name(
            select
        ) or infer_variant_group_name_from_values(raw_option_values)
        cleaned_name = _prefer_axis_inferred_from_values(
            cleaned_name,
            raw_option_values,
        )
        if not cleaned_name:
            continue
        component_style = _component_size_style_from_group_name(
            cleaned_name
        ) or _component_size_style_from_group_name(next(iter(raw_option_values), ""))
        if component_style:
            cleaned_name = "size"
        option_entries: list[dict[str, object]] = []
        axis_key = normalized_variant_axis_key(cleaned_name)
        if not _dom_variant_group_name_allowed(cleaned_name):
            continue
        select_options = list(select.find_all("option"))
        for option_index, option in enumerate(select_options):
            cleaned_value = _coerce_variant_option_value(
                axis_key,
                option.get_text(" ", strip=True),
                page_url=page_url,
            ) or clean_text(option.get_text(" ", strip=True))
            cleaned_value = _strip_variant_option_value_suffix_noise(cleaned_value)
            raw_value_attr = text_or_none(option.get("value"))
            if (
                not cleaned_value
                or variant_option_value_is_noise(cleaned_value)
                or (
                    raw_value_attr is not None
                    and raw_value_attr.lower() in {"select", "choose"}
                )
            ):
                continue
            entry: dict[str, object] = {"value": cleaned_value}
            if node_attr_is_truthy(option, "selected", "aria-selected"):
                entry["selected"] = True
            variant_url = variant_option_url(
                container=select,
                node=option,
                label_node=None,
                page_url=page_url,
            )
            if variant_url:
                entry["url"] = variant_url
            if component_style:
                entry["style"] = component_style
            option_entries.append(entry)
        deduped_values = list(
            dict.fromkeys(
                str(entry["value"])
                for entry in option_entries
                if text_or_none(entry.get("value"))
            )
        )
        if len(deduped_values) >= 2:
            candidate_groups.append(
                build_variant_candidate_group(
                    select,
                    name=cleaned_name,
                    values=deduped_values,
                    entries=option_entries,
                    extractor_path="select",
                )
            )

    for container in iter_variant_choice_groups(soup):
        cleaned_name = _resolve_dom_variant_group_name(container)
        if not cleaned_name:
            continue
        option_entries = _collect_variant_choice_entries(container, page_url=page_url)
        deduped_values = [
            str(entry["value"])
            for entry in option_entries
            if text_or_none(entry.get("value"))
        ]
        cleaned_name = _prefer_axis_inferred_from_values(
            cleaned_name,
            deduped_values,
        )
        if len(deduped_values) >= 2:
            candidate_groups.append(
                build_variant_candidate_group(
                    container,
                    name=cleaned_name,
                    values=deduped_values,
                    entries=option_entries,
                    extractor_path=(
                        "choice_radio"
                        if any(
                            item in {"input_radio", "role_radio"}
                            for item in variant_option_node_types(
                                container,
                                extractor_path="choice",
                            )
                        )
                        else "choice_button"
                    ),
                )
            )

    validator = VariantGroupValidator()
    option_groups = [
        group.as_option_group()
        for group in candidate_groups
        if validator.validate(group, page_url=page_url)
    ]
    expanded_option_groups: list[dict[str, object]] = []
    for group in option_groups:
        compound_groups = _expand_compound_option_group(group)
        if compound_groups:
            expanded_option_groups.extend(compound_groups)
            continue
        expanded_option_groups.append(group)

    deduped_groups: list[dict[str, object]] = []
    merged_groups: dict[str, dict[str, object]] = {}
    for group in expanded_option_groups:
        values = [
            clean_text(value)
            for value in _object_list(group.get("values"))
            if clean_text(value)
        ]
        if len(values) < 2:
            continue
        name = clean_text(group.get("name"))
        axis_key = normalized_variant_axis_key(name)
        if not axis_key:
            continue
        merged = merged_groups.setdefault(
            axis_key, {"name": name or axis_key, "values": [], "entries": {}}
        )
        if len(name) > len(str(merged.get("name") or "")):
            merged["name"] = name
        existing_values = _object_list(merged.get("values"))
        merged["values"] = list(dict.fromkeys([*existing_values, *values]))
        merged_entries = merged.setdefault("entries", {})
        if not isinstance(merged_entries, dict):
            merged_entries = {}
            merged["entries"] = merged_entries
        for group_entry in _object_list(group.get("entries")):
            if not isinstance(group_entry, dict):
                continue
            value = clean_text(group_entry.get("value"))
            if not value:
                continue
            existing = _object_dict(merged_entries.get(value, {"value": value}))
            availability = text_or_none(group_entry.get("availability"))
            if availability and existing.get("availability") in (None, "", [], {}):
                existing["availability"] = availability
            if group_entry.get("stock_quantity") not in (None, "", [], {}):
                existing["stock_quantity"] = group_entry.get("stock_quantity")
            if group_entry.get("style") not in (None, "", [], {}) and existing.get(
                "style"
            ) in (None, "", [], {}):
                existing["style"] = group_entry.get("style")
            if group_entry.get("selected"):
                existing["selected"] = True
            if group_entry.get("url") not in (None, "", [], {}) and existing.get(
                "url"
            ) in (None, "", [], {}):
                existing["url"] = group_entry.get("url")
            if group_entry.get("variant_id") not in (None, "", [], {}) and existing.get(
                "variant_id"
            ) in (None, "", [], {}):
                existing["variant_id"] = group_entry.get("variant_id")
            if group_entry.get("image_url") not in (None, "", [], {}) and existing.get(
                "image_url"
            ) in (None, "", [], {}):
                existing["image_url"] = group_entry.get("image_url")
            merged_entries[value] = existing
    try:
        group_limit = max(1, int(DOM_VARIANT_GROUP_LIMIT))
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Invalid DOM_VARIANT_GROUP_LIMIT; using 1",
            extra={"value": DOM_VARIANT_GROUP_LIMIT},
            exc_info=exc,
        )
        group_limit = 1
    for group in merged_groups.values():
        values = [
            clean_text(value)
            for value in _object_list(group.get("values"))
            if clean_text(value)
        ]
        if len(values) < 2:
            continue
        merged_entries = _object_dict(group.get("entries"))
        deduped_groups.append(
            {
                "name": clean_text(group.get("name")),
                "values": values,
                "entries": list(merged_entries.values()),
            }
        )
        if len(deduped_groups) >= group_limit:
            break

    if not deduped_groups:
        return {}

    state_axis_targets, state_combo_targets = _state_variant_targets(
        js_state_objects,
        page_url=page_url,
    )
    record: dict[str, object] = {}
    axis_values_by_name: dict[str, list[str]] = {}
    axis_option_metadata: dict[str, dict[str, dict[str, object]]] = {}
    axis_order: list[tuple[str, str, list[str]]] = []
    for group in deduped_groups:
        name = clean_text(group.get("name"))
        values = [str(value) for value in _object_list(group.get("values"))]
        axis_key = normalized_variant_axis_key(name)
        if not _dom_variant_axis_allowed(axis_key):
            continue
        axis_values_by_name[axis_key] = values
        axis_option_metadata[axis_key] = {
            clean_text(entry.get("value")): {
                key: entry.get(key)
                for key in (
                    "availability",
                    "selected",
                    "style",
                    "stock_quantity",
                    "url",
                    "variant_id",
                    "image_url",
                )
                if entry.get(key) not in (None, "", [], {})
            }
            for entry in _object_list(group.get("entries"))
            if isinstance(entry, dict)
            if clean_text(entry.get("value"))
        }
        for option_value, state_metadata in dict(
            state_axis_targets.get(axis_key) or {}
        ).items():
            merged_metadata = axis_option_metadata[axis_key].setdefault(
                option_value, {}
            )
            for key in ("url", "variant_id", "image_url"):
                if state_metadata.get(key) not in (
                    None,
                    "",
                    [],
                    {},
                ) and merged_metadata.get(key) in (None, "", [], {}):
                    merged_metadata[key] = state_metadata[key]
        axis_order.append((axis_key, name, values))
    if not axis_values_by_name:
        return {}

    variants: list[dict[str, object]] = []
    axis_names = [axis_key for axis_key, _label, _values in axis_order]
    axis_value_lists = [values for _axis_key, _label, values in axis_order]
    try:
        combo_limit = int(DOM_VARIANT_CARTESIAN_COMBO_LIMIT)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Invalid DOM_VARIANT_CARTESIAN_COMBO_LIMIT; using 1000",
            extra={"value": DOM_VARIANT_CARTESIAN_COMBO_LIMIT},
            exc_info=exc,
        )
        combo_limit = 1000
    if _dom_variant_combo_count(axis_value_lists) > combo_limit:
        variants = _axis_only_dom_variants(axis_order, axis_option_metadata)
    else:
        for combo in product(*axis_value_lists):
            option_values = {
                axis_name: value
                for axis_name, value in zip(axis_names, combo, strict=False)
                if clean_text(value)
            }
            if not option_values:
                continue
            variant: dict[str, object] = {
                "option_values": option_values,
            }
            for axis_name, value in option_values.items():
                variant[axis_name] = value
            combo_metadata = state_combo_targets.get(
                tuple(sorted(option_values.items())), {}
            )
            for key in ("url", "variant_id", "image_url"):
                if combo_metadata.get(key) not in (None, "", [], {}):
                    variant[key] = combo_metadata[key]
            if len(axis_names) == 1:
                axis_key = axis_names[0]
                option_metadata = axis_option_metadata.get(axis_key, {}).get(
                    str(combo[0]), {}
                )
                availability = text_or_none(option_metadata.get("availability"))
                if availability:
                    variant["availability"] = availability
                if option_metadata.get("stock_quantity") not in (None, "", [], {}):
                    variant["stock_quantity"] = option_metadata.get("stock_quantity")
                if option_metadata.get("style") not in (None, "", [], {}):
                    variant["style"] = option_metadata.get("style")
                for key in ("url", "variant_id", "image_url"):
                    if option_metadata.get(key) not in (None, "", [], {}):
                        variant[key] = option_metadata.get(key)
            variants.append(variant)

    selectable_axes, single_value_attributes = split_variant_axes(
        axis_values_by_name,
        always_selectable_axes=frozenset({"size"}),
    )
    resolved_variants = (
        resolve_variants(selectable_axes or axis_values_by_name, variants)
        if variants
        else []
    )
    active_variant = select_variant(resolved_variants, page_url=page_url)
    selected_option_values = {
        axis_name: option_value
        for axis_name, option_value in (
            (
                axis_name,
                next(
                    (
                        value
                        for value, metadata in axis_option_metadata.get(
                            axis_name, {}
                        ).items()
                        if metadata.get("selected")
                    ),
                    None,
                ),
            )
            for axis_name in axis_names
        )
        if option_value
    }
    if selected_option_values:
        active_variant = next(
            (
                variant
                for variant in resolved_variants
                if variant.get("option_values") == selected_option_values
            ),
            active_variant,
        )
    for axis_name, value in single_value_attributes.items():
        record.setdefault(axis_name, value)
    if resolved_variants:
        flat_variants = flatten_variants_for_public_output(
            resolved_variants,
            page_url=page_url,
        )
        if flat_variants:
            for variant in flat_variants:
                variant["_validated"] = True
            record["variants"] = flat_variants
            record["variant_count"] = len(flat_variants)
        if active_variant:
            if record.get("availability") in (None, "", [], {}):
                selected_availability = text_or_none(active_variant.get("availability"))
                if selected_availability:
                    record["availability"] = selected_availability
    return record


def _dom_variant_combo_count(axis_value_lists: list[list[str]]) -> int:
    count = 1
    for values in axis_value_lists:
        count *= max(1, len(values))
    return count


def _axis_only_dom_variants(
    axis_order: list[tuple[str, str, list[str]]],
    axis_option_metadata: dict[str, dict[str, dict[str, object]]],
) -> list[dict[str, object]]:
    variants: list[dict[str, object]] = []
    for axis_key, _name, values in axis_order:
        for value in values:
            cleaned_value = clean_text(value)
            if not cleaned_value:
                continue
            option_values = {axis_key: cleaned_value}
            variant: dict[str, object] = {
                "option_values": option_values,
                axis_key: cleaned_value,
            }
            metadata = axis_option_metadata.get(axis_key, {}).get(cleaned_value, {})
            for key in (
                "availability",
                "selected",
                "style",
                "stock_quantity",
                "url",
                "variant_id",
                "image_url",
            ):
                if metadata.get(key) not in (None, "", [], {}):
                    variant[key] = metadata[key]
            variants.append(variant)
    return variants


def backfill_variants_from_dom_if_missing(
    record: dict[str, Any],
    *,
    soup: BeautifulSoup,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> None:
    existing_variants = [
        row for row in list(record.get("variants") or []) if isinstance(row, dict)
    ]
    if not variant_dom_cues_present(soup):
        return
    dom_variants = extract_variants_from_dom(
        soup,
        page_url=page_url,
        js_state_objects=js_state_objects,
    )
    dom_variant_rows = [
        row
        for row in _object_list(dom_variants.get("variants"))
        if isinstance(row, dict)
    ]
    if not dom_variant_rows:
        return
    if (
        record_has_rich_existing_variants(record)
        or existing_variant_cluster_has_transport_signal(existing_variants)
    ) and not _dom_variants_add_missing_existing_axis(existing_variants, dom_variant_rows):
        return
    if dom_variant_rows:
        expanded_rows = _expand_existing_variants_with_dom_axes(
            existing_variants,
            dom_variant_rows,
        )
        if expanded_rows:
            record["variants"] = expanded_rows
            record["variant_count"] = len(expanded_rows)
        else:
            existing_by_key: dict[str, dict[str, Any]] = {}
            for row in existing_variants:
                row_key = text_or_none(row.get("variant_id")) or text_or_none(
                    row.get("url")
                )
                if row_key:
                    # Preserve the first occurrence so duplicate variant_id/url
                    # keys cannot overwrite earlier rows and merge unrelated variants.
                    existing_by_key.setdefault(row_key, row)
            merged_rows: list[dict[str, Any]] = []
            for dom_row in dom_variant_rows:
                dom_key = text_or_none(dom_row.get("variant_id")) or text_or_none(
                    dom_row.get("url")
                )
                existing_row = existing_by_key.get(dom_key or "") if dom_key else None
                merged_rows.append(
                    merge_variant_pair(existing_row, dom_row)
                    if isinstance(existing_row, dict)
                    else dom_row
                )
            record["variants"] = merged_rows
            record["variant_count"] = len(merged_rows)
    currency = text_or_none(record.get("currency"))
    price = text_or_none(record.get("price"))
    parent_availability = text_or_none(record.get("availability"))
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    if any(
        isinstance(variant, dict) and variant.get("price") not in (None, "", [], {})
        for variant in variants
    ):
        return
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if (
            parent_availability == "in_stock"
            and variant.get("availability") in (None, "", [], {})
            and variant.get("stock_quantity") in (None, "", [], {})
        ):
            variant["availability"] = parent_availability
        if price:
            variant["price"] = price
        if currency and variant.get("currency") in (None, "", [], {}):
            variant["currency"] = currency


def _variant_axes_present(variants: list[dict[str, Any]]) -> set[str]:
    return {
        axis
        for row in variants
        if isinstance(row, dict)
        for axis in public_variant_axis_fields
        if text_or_none(row.get(axis))
    }


def _dom_variants_add_missing_existing_axis(
    existing_variants: list[dict[str, Any]],
    dom_variant_rows: list[dict[str, Any]],
) -> bool:
    existing_axes = _variant_axes_present(existing_variants)
    dom_axes = _variant_axes_present(dom_variant_rows)
    return bool(existing_axes and dom_axes - existing_axes)


def _expand_existing_variants_with_dom_axes(
    existing_variants: list[dict[str, Any]],
    dom_variant_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not existing_variants or not dom_variant_rows:
        return []
    existing_axes = _variant_axes_present(existing_variants)
    dom_axes = _variant_axes_present(dom_variant_rows)
    missing_dom_axes = dom_axes - existing_axes
    if not existing_axes or not missing_dom_axes:
        return []
    if not all(
        any(text_or_none(row.get(field_name)) for field_name in _VARIANT_TRANSPORT_FIELDS)
        for row in existing_variants
        if isinstance(row, dict)
    ):
        return []
    try:
        combo_limit = int(DOM_VARIANT_CARTESIAN_COMBO_LIMIT)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Invalid DOM_VARIANT_CARTESIAN_COMBO_LIMIT; using 1000",
            extra={"value": DOM_VARIANT_CARTESIAN_COMBO_LIMIT},
            exc_info=exc,
        )
        combo_limit = 1000
    if len(existing_variants) * len(dom_variant_rows) > combo_limit:
        return []

    expanded_rows: list[dict[str, Any]] = []
    for existing_row, dom_row in product(existing_variants, dom_variant_rows):
        merged = dict(existing_row)
        for field_name in ("sku", "variant_id", "barcode"):
            merged.pop(field_name, None)
        option_values = {
            key: value
            for source in (
                existing_row.get("option_values"),
                dom_row.get("option_values"),
            )
            if isinstance(source, dict)
            for key, value in source.items()
            if text_or_none(value)
        }
        for axis in public_variant_axis_fields:
            dom_value = text_or_none(dom_row.get(axis))
            if axis in missing_dom_axes and dom_value:
                merged[axis] = dom_value
                option_values[axis] = dom_value
        if option_values:
            merged["option_values"] = option_values
        expanded_rows.append(merged)
    return expanded_rows


def existing_variant_cluster_has_transport_signal(
    variants: list[dict[str, Any]],
) -> bool:
    if len(variants) < 2:
        return False
    rows_with_transport = 0
    for row in variants:
        if not isinstance(row, dict):
            continue
        has_identity = any(
            text_or_none(row.get(field_name))
            for field_name in ("sku", "variant_id", "url", "image_url")
        )
        has_price = text_or_none(row.get("price")) is not None
        if has_identity and has_price:
            rows_with_transport += 1
    return rows_with_transport >= 2
