from __future__ import annotations

__all__ = (
    "existing_variant_cluster_has_transport_signal",
    "primary_dom_context",
    "record_has_rich_existing_variants",
    "extract_variants_from_dom",
    "backfill_variants_from_dom_if_missing",
)

import logging
import re
from itertools import product
from typing import Any

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    DOM_VARIANT_CARTESIAN_COMBO_LIMIT,
    DOM_VARIANT_GROUP_LIMIT,
    VARIANT_CHOICE_OPTION_LIMIT,
)
from app.services.config.variant_migration_rules import (
    VARIANT_STRONG_OPTION_SELECTOR,
    VARIANT_WEAK_OPTION_SELECTOR,
)
from app.services.extract.variant_normalization.contract import (
    flatten_variants_for_public_output,
)
from app.services.shared.field_coerce import (
    clean_text,
    object_dict as _object_dict,
    object_list as _object_list,
    text_or_none,
)
from app.services.extract.detail.variants.state_targets import (
    state_variant_targets as _state_variant_targets,
)
from app.services.extract.detail.variants.dom_options import (
    merge_variant_option_state,
    node_attr_is_truthy,
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
from app.services.extract.variant_choice_traversal import (
    infer_variant_group_name_from_values,
    iter_variant_choice_groups,
    iter_variant_select_groups,
    resolve_variant_group_name,
    variant_dom_cues_present,
)
from app.services.extract.variant_identity_merge import (
    merge_variant_pair,
    resolve_variants,
    split_variant_axes,
)
from app.services.extract.variant_axis import (
    normalized_variant_axis_key,
    option_scalar_fields,
    public_variant_axis_fields,
)
from app.services.extract.variant_option_value import (
    variant_option_value_is_noise,
)
from app.services.extract.detail.assembly import (
    dom_section_targets as _detail_dom_section_targets,
)
from app.services.extract.detail.variants import dom_coercion as _variant_coercion

existing_variant_cluster_has_transport_signal = (
    _detail_dom_section_targets.existing_variant_cluster_has_transport_signal
)
primary_dom_context = _detail_dom_section_targets.primary_dom_context
record_has_rich_existing_variants = (
    _detail_dom_section_targets.record_has_rich_existing_variants
)

logger = logging.getLogger(__name__)


def _safe_int_config(value: object, default: int, name: str) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError) as exc:
        logger.warning(
            f"Invalid {name}; using {default}",
            extra={"value": value},
            exc_info=exc,
        )
        return default


_VARIANT_TRANSPORT_FIELDS = (
    "sku",
    "price",
    "currency",
    "url",
    "image_url",
    "availability",
    "stock_quantity",
)


_coerce_variant_option_value = _variant_coercion._coerce_variant_option_value
_color_option_value_candidates = _variant_coercion._color_option_value_candidates
_component_size_style_from_group_name = (
    _variant_coercion._component_size_style_from_group_name
)
_dom_variant_axis_allowed = _variant_coercion._dom_variant_axis_allowed
_dom_variant_group_name_allowed = _variant_coercion._dom_variant_group_name_allowed
_expand_compound_option_group = _variant_coercion._expand_compound_option_group
_prefer_axis_inferred_from_values = _variant_coercion._prefer_axis_inferred_from_values
_resolve_dom_variant_group_name = _variant_coercion._resolve_dom_variant_group_name
_strip_variant_option_value_suffix_noise = (
    _variant_coercion._strip_variant_option_value_suffix_noise
)


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
    container: Any, *, page_url: str, title_hint: str = ""
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
        if not clean_text(cleaned) and coercion_axis == "color":
            cleaned = _color_value_from_option_url(
                variant_option_url(
                    container=container,
                    node=node,
                    label_node=None,
                    page_url=page_url,
                ),
                page_url=page_url,
                title_hint=title_hint,
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
        if not clean_text(cleaned) and coercion_axis == "color":
            cleaned = _color_value_from_option_url(
                variant_option_url(
                    container=container,
                    node=input_node,
                    label_node=label_node,
                    page_url=page_url,
                ),
                page_url=page_url,
                title_hint=title_hint,
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
            _descendant_aria_label_text(resolved_label),
            _descendant_aria_label_text(node),
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
    option_tokens = _url_terminal_tokens(value)
    page_tokens = _url_terminal_tokens(page_url)
    if len(option_tokens) < 2:
        return ""
    suffix_tokens = _url_suffix_after_prefix(option_tokens, _url_title_tokens(title_hint))
    if not suffix_tokens:
        suffix_tokens = _url_suffix_after_prefix(option_tokens, page_tokens)
    if not suffix_tokens or len(suffix_tokens) > 4:
        return ""
    suffix_tokens = _clean_color_suffix_tokens(suffix_tokens)
    if not suffix_tokens or len(suffix_tokens) > 4:
        return ""
    return " ".join(token.capitalize() for token in suffix_tokens)


def _url_terminal_tokens(value: object) -> list[str]:
    from urllib.parse import unquote, urlparse

    text = clean_text(value)
    if not text:
        return []
    terminal = unquote(urlparse(text).path.rstrip("/").rsplit("/", 1)[-1])
    return [
        _url_identity_token(token)
        for token in re.findall(r"[a-z0-9]+", terminal.casefold())
        if token and token != "s"
    ]


def _url_title_tokens(value: object) -> list[str]:
    return [
        _url_identity_token(token)
        for token in re.findall(r"[a-z0-9]+", clean_text(value).casefold())
        if token and token != "s"
    ]


def _url_suffix_after_prefix(tokens: list[str], prefix: list[str]) -> list[str]:
    if not prefix or len(tokens) <= len(prefix):
        return []
    if tokens[: len(prefix)] == prefix:
        return tokens[len(prefix) :]
    for index, (left, right) in enumerate(zip(tokens, prefix, strict=False)):
        if left != right:
            return tokens[index:]
    return tokens[len(prefix) :]


def _clean_color_suffix_tokens(tokens: list[str]) -> list[str]:
    cleaned = [token for token in tokens if not token.isdigit() and token not in {"html"}]
    while cleaned and cleaned[0] in {"in", "color", "colour"}:
        cleaned = cleaned[1:]
    return cleaned


def _url_identity_token(value: str) -> str:
    if value in {"mens", "womens", "kids"}:
        return value[:-1]
    if len(value) > 4 and value.endswith("s"):
        return value[:-1]
    return value


def extract_variants_from_dom(
    soup: BeautifulSoup,
    *,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> dict[str, object]:
    candidate_groups = []
    title_hint = clean_text(soup.h1.get_text(" ", strip=True) if soup.h1 else "")
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
        option_entries = _collect_variant_choice_entries(
            container,
            page_url=page_url,
            title_hint=title_hint,
        )
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
    group_limit = _safe_int_config(
        DOM_VARIANT_GROUP_LIMIT,
        1,
        "DOM_VARIANT_GROUP_LIMIT",
    )
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
    combo_limit = _safe_int_config(
        DOM_VARIANT_CARTESIAN_COMBO_LIMIT,
        1000,
        "DOM_VARIANT_CARTESIAN_COMBO_LIMIT",
    )
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
    ) and not _dom_variants_add_missing_existing_axis(
        existing_variants, dom_variant_rows
    ):
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
        any(
            text_or_none(row.get(field_name))
            for field_name in _VARIANT_TRANSPORT_FIELDS
        )
        for row in existing_variants
        if isinstance(row, dict)
    ):
        return []
    combo_limit = _safe_int_config(
        DOM_VARIANT_CARTESIAN_COMBO_LIMIT,
        1000,
        "DOM_VARIANT_CARTESIAN_COMBO_LIMIT",
    )
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
