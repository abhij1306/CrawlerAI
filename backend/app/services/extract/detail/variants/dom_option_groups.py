from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import VARIANT_CHOICE_OPTION_LIMIT
from app.services.config.variant_migration_rules import (
    VARIANT_STRONG_OPTION_SELECTOR,
    VARIANT_WEAK_OPTION_SELECTOR,
)
from app.services.extract.detail.variants import dom_coercion as _variant_coercion
from app.services.extract.detail.variants.dom_options import (
    merge_variant_option_state,
    node_attr_is_truthy,
    variant_option_availability,
    variant_option_url,
)
from app.services.extract.variant_axis import (
    normalized_variant_axis_key,
    option_scalar_fields,
    public_variant_axis_fields,
)
from app.services.extract.variant_choice_traversal import (
    infer_variant_group_name_from_values,
    iter_variant_choice_groups,
    iter_variant_select_groups,
    resolve_variant_group_name,
    variant_input_label,
)
from app.services.extract.variant_dom_provenance import (
    build_variant_candidate_group,
    variant_option_node_types,
    weak_variant_option_node_allowed,
)
from app.services.extract.variant_option_value import variant_option_value_is_noise
from app.services.shared.field_coerce import clean_text, text_or_none
from app.services.shared.url_utils import (
    clean_color_tokens,
    suffix_after_prefix,
    terminal_tokens,
    title_tokens,
)

__all__ = ("collect_dom_variant_candidate_groups",)

logger = logging.getLogger(__name__)

_coerce_variant_option_value = _variant_coercion._coerce_variant_option_value
_color_option_value_candidates = _variant_coercion._color_option_value_candidates
_component_size_style_from_group_name = (
    _variant_coercion._component_size_style_from_group_name
)
_dom_variant_group_name_allowed = _variant_coercion._dom_variant_group_name_allowed
_prefer_axis_inferred_from_values = _variant_coercion._prefer_axis_inferred_from_values
_resolve_dom_variant_group_name = _variant_coercion._resolve_dom_variant_group_name
_strip_variant_option_value_suffix_noise = (
    _variant_coercion._strip_variant_option_value_suffix_noise
)


def collect_dom_variant_candidate_groups(
    soup: BeautifulSoup,
    *,
    page_url: str,
    safe_int_config,
) -> list[Any]:
    title_hint = clean_text(soup.h1.get_text(" ", strip=True) if soup.h1 else "")
    return [
        *_select_variant_candidate_groups(soup, page_url=page_url),
        *_choice_variant_candidate_groups(
            soup,
            page_url=page_url,
            title_hint=title_hint,
            safe_int_config=safe_int_config,
        ),
    ]


def _select_variant_candidate_groups(
    soup: BeautifulSoup,
    *,
    page_url: str,
) -> list[Any]:
    candidate_groups: list[Any] = []
    for select in iter_variant_select_groups(soup):
        raw_option_values = [
            clean_text(option.get_text(" ", strip=True))
            for option in select.find_all("option")
            if clean_text(option.get_text(" ", strip=True))
        ]
        cleaned_name = resolve_variant_group_name(
            select
        ) or infer_variant_group_name_from_values(raw_option_values)
        cleaned_name = _prefer_axis_inferred_from_values(cleaned_name, raw_option_values)
        if not cleaned_name:
            continue
        component_style = _component_size_style_from_group_name(
            cleaned_name
        ) or _component_size_style_from_group_name(next(iter(raw_option_values), ""))
        if component_style:
            cleaned_name = "size"
        axis_key = normalized_variant_axis_key(cleaned_name)
        if not _dom_variant_group_name_allowed(cleaned_name):
            continue
        option_entries = _select_option_entries(
            select,
            axis_key=axis_key,
            page_url=page_url,
            component_style=component_style,
        )
        deduped_values = _deduped_entry_values(option_entries)
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
    return candidate_groups


def _choice_variant_candidate_groups(
    soup: BeautifulSoup,
    *,
    page_url: str,
    title_hint: str,
    safe_int_config,
) -> list[Any]:
    candidate_groups: list[Any] = []
    for container in iter_variant_choice_groups(soup):
        cleaned_name = _resolve_dom_variant_group_name(container)
        if not cleaned_name:
            continue
        option_entries = _collect_variant_choice_entries(
            container,
            page_url=page_url,
            title_hint=title_hint,
            safe_int_config=safe_int_config,
        )
        deduped_values = _deduped_entry_values(option_entries)
        cleaned_name = _prefer_axis_inferred_from_values(cleaned_name, deduped_values)
        if len(deduped_values) < 2:
            continue
        candidate_groups.append(
            build_variant_candidate_group(
                container,
                name=cleaned_name,
                values=deduped_values,
                entries=option_entries,
                extractor_path=_choice_extractor_path(container),
            )
        )
    return candidate_groups


def _deduped_entry_values(option_entries: list[dict[str, object]]) -> list[str]:
    return list(
        dict.fromkeys(
            str(entry["value"])
            for entry in option_entries
            if text_or_none(entry.get("value"))
        )
    )


def _choice_extractor_path(container: Any) -> str:
    node_types = variant_option_node_types(container, extractor_path="choice")
    return (
        "choice_radio"
        if any(item in {"input_radio", "role_radio"} for item in node_types)
        else "choice_button"
    )


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
    container: Any,
    *,
    page_url: str,
    title_hint: str,
    safe_int_config,
) -> list[dict[str, object]]:
    raw_group_name = _resolve_dom_variant_group_name(container)
    axis_name = normalized_variant_axis_key(raw_group_name)
    coercion_axis = (
        axis_name
        if axis_name in option_scalar_fields or axis_name in public_variant_axis_fields
        else "style"
    )
    entries_by_value: dict[str, dict[str, object]] = {}
    visible_text_cache: dict[int, str] = {}
    option_limit = safe_int_config(
        VARIANT_CHOICE_OPTION_LIMIT,
        50,
        "VARIANT_CHOICE_OPTION_LIMIT",
    )
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
        _add_choice_entry(
            entries_by_value,
            container=container,
            node=node,
            coercion_axis=coercion_axis,
            page_url=page_url,
            title_hint=title_hint,
            visible_text_cache=visible_text_cache,
        )
    for input_node in container.select("input[type='radio'], input[type='checkbox']")[
        :option_limit
    ]:
        label_node = variant_input_label(container, input_node)
        _add_choice_entry(
            entries_by_value,
            container=container,
            node=input_node,
            coercion_axis=coercion_axis,
            page_url=page_url,
            title_hint=title_hint,
            visible_text_cache=visible_text_cache,
            label_node=label_node,
        )
    return list(entries_by_value.values())


def _add_choice_entry(
    entries_by_value: dict[str, dict[str, object]],
    *,
    container: Any,
    node: Any,
    coercion_axis: str,
    page_url: str,
    title_hint: str,
    visible_text_cache: dict[int, str],
    label_node: Any | None = None,
) -> None:
    raw_value = _variant_choice_entry_value(
        container,
        node,
        axis_name=coercion_axis,
        label_node=label_node,
        visible_text_cache=visible_text_cache,
    )
    cleaned = _resolved_variant_option_value(
        coercion_axis,
        raw_value,
        page_url=page_url,
    )
    if not clean_text(cleaned) and coercion_axis == "color":
        option_url = variant_option_url(
            container=container,
            node=node,
            label_node=label_node,
            page_url=page_url,
        )
        cleaned = _color_value_from_option_url(
            option_url,
            page_url=page_url,
            title_hint=title_hint,
        )
        _log_url_color_fallback(
            cleaned,
            option_url=str(option_url or ""),
        )
    cleaned = _strip_variant_option_value_suffix_noise(cleaned)
    if variant_option_value_is_noise(cleaned):
        return
    entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
    merge_variant_option_state(
        entry,
        container=container,
        node=node,
        page_url=page_url,
        label_node=label_node,
    )
    variant_id = text_or_none(
        node.get("data-sku")
        or node.get("data-variant-id")
        or node.get("data-product-id")
    )
    if variant_id and entry.get("variant_id") in (None, "", [], {}):
        entry["variant_id"] = variant_id


def _variant_choice_entry_value(
    container: Any,
    node: Any,
    *,
    axis_name: str,
    label_node: Any | None = None,
    visible_text_cache: dict[int, str] | None = None,
) -> str:
    resolved_label = label_node or variant_input_label(container, node)
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
            _descendant_aria_label_text(resolved_label),
            _descendant_aria_label_text(node),
            node_text,
        ):
            cleaned = clean_text(raw_value)
            if not cleaned:
                continue
            candidates = _color_option_value_candidates(cleaned)
            if candidates and (candidate := candidates[0]):
                return candidate
    return clean_text(
        node.get("data-attr-displayvalue")
        or node.get("data-displayvalue")
        or node.get("data-display-value")
        or node.get("data-attr-value")
        or node.get("data-swatch-sr")
        or node.get("data-size")
        or label_text
        or node.get("data-value")
        or node.get("data-option-value")
        or aria_label
        or node.get("value")
        or node_text
    )


def _variant_option_value_is_url_like(value: object) -> bool:
    text = text_or_none(value)
    if not text:
        return False
    lowered = text.strip().lower()
    return (
        lowered.startswith(("http://", "https://", "/"))
        or "product-variation?" in lowered
    )


def _variant_axis_value_from_option_url(axis_name: str, value: object) -> str:
    if axis_name not in {"size", "length"}:
        return ""
    text = text_or_none(value)
    if not text:
        return ""
    parsed = urlsplit(text)
    for key, raw_value in parse_qsl(parsed.query, keep_blank_values=False):
        normalized_key = clean_text(key).casefold()
        candidate = clean_text(raw_value)
        if not normalized_key or not candidate:
            continue
        if axis_name == "size" and (
            normalized_key == "size"
            or normalized_key == "size1"
            or normalized_key == "waist"
            or normalized_key.endswith("_size")
            or normalized_key.endswith("_size1")
            or normalized_key.endswith("_waist")
        ):
            return candidate
        if axis_name == "length" and (
            normalized_key == "length"
            or normalized_key == "size2"
            or normalized_key == "inseam"
            or normalized_key.endswith("_length")
            or normalized_key.endswith("_size2")
            or normalized_key.endswith("_inseam")
        ):
            return candidate
    return ""


def _resolved_variant_option_value(
    axis_name: str,
    raw_value: object,
    *,
    page_url: str,
) -> str:
    cleaned = _coerce_variant_option_value(axis_name, raw_value, page_url=page_url)
    if _variant_option_value_is_url_like(cleaned or raw_value):
        derived = _variant_axis_value_from_option_url(axis_name, cleaned or raw_value)
        if derived:
            return _coerce_variant_option_value(axis_name, derived, page_url=page_url)
        if axis_name in {"size", "length"}:
            return ""
    return cleaned


def _descendant_image_alt_text(node: Any) -> str:
    if not hasattr(node, "find"):
        return ""
    image = node.find("img")
    if image is None or not hasattr(image, "get"):
        return ""
    return clean_text(image.get("alt"))


def _descendant_aria_label_text(node: Any) -> str:
    if not hasattr(node, "find"):
        return ""
    child = node.find(attrs={"aria-label": True})
    if child is None or not hasattr(child, "get"):
        return ""
    return clean_text(child.get("aria-label"))


def _color_value_from_option_url(
    value: object,
    *,
    page_url: str,
    title_hint: str = "",
) -> str:
    option_tokens = terminal_tokens(value)
    page_tokens = terminal_tokens(page_url)
    if len(option_tokens) < 2:
        return ""
    suffix_tokens = suffix_after_prefix(option_tokens, title_tokens(title_hint))
    if not suffix_tokens:
        suffix_tokens = suffix_after_prefix(option_tokens, page_tokens)
    if not suffix_tokens or len(suffix_tokens) > 4:
        return ""
    suffix_tokens = clean_color_tokens(suffix_tokens)
    if not suffix_tokens or len(suffix_tokens) > 4:
        return ""
    return " ".join(token.capitalize() for token in suffix_tokens)


def _log_url_color_fallback(color: str, *, option_url: str) -> None:
    if not color:
        return
    logger.debug(
        "Extracted DOM variant color from option URL",
        extra={"color_length": len(color), "color_extracted": bool(color)},
    )


def _select_option_entries(
    select: Any,
    *,
    axis_key: str,
    page_url: str,
    component_style: str | None,
) -> list[dict[str, object]]:
    option_entries: list[dict[str, object]] = []
    for option in select.find_all("option"):
        raw_value_attr = text_or_none(option.get("value"))
        cleaned_value = _resolved_variant_option_value(
            axis_key,
            option.get_text(" ", strip=True) or raw_value_attr,
            page_url=page_url,
        ) or clean_text(option.get_text(" ", strip=True))
        cleaned_value = _strip_variant_option_value_suffix_noise(cleaned_value)
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
        availability, stock_quantity = variant_option_availability(
            node=option,
            label_node=None,
        )
        if availability:
            entry["availability"] = availability
        if stock_quantity is not None:
            entry["stock_quantity"] = stock_quantity
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
    return option_entries
