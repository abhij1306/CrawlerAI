from __future__ import annotations

__all__ = (
    "infer_variant_group_name",
    "variant_dom_cues_present",
    "resolve_variant_group_name",
    "infer_variant_group_name_from_values",
    "iter_variant_select_groups",
    "iter_variant_choice_groups",
)

import re
from collections.abc import Sequence
from typing import Any

from app.services.config.extraction_rules import (
    VARIANT_AXIS_EXCLUDED_SINGLE_TOKENS,
    VARIANT_CHOICE_GROUP_MAX,
    VARIANT_CHOICE_GROUP_SELECTOR,
    VARIANT_CHOICE_CONTAINER_GROUP_LIMIT,
    VARIANT_CHOICE_CONTAINER_MIN_DISTINCT_NAMES,
    VARIANT_CHOICE_CONTAINER_OPTION_LIMIT,
    VARIANT_CHOICE_CONTAINER_SELECT_LIMIT,
    VARIANT_CHOICE_OPTION_LIMIT,
    VARIANT_CHOICE_OPTION_SELECTOR,
    VARIANT_COLOR_AXIS_TOKENS,
    VARIANT_DESCENDANT_SCAN_LIMIT,
    VARIANT_GROUP_ATTR_NOISE_PATTERNS,
    VARIANT_GROUP_ATTR_NOISE_TOKENS,
    VARIANT_MATCHING_INPUT_LIMIT,
    VARIANT_QUANTITY_ATTR_TOKENS,
    VARIANT_SELECT_GROUP_MAX,
    VARIANT_SIZE_AXIS_TOKENS,
    VARIANT_SIZE_VALUE_PATTERNS,
    VARIANT_SELECT_GROUP_SELECTOR,
    VARIANT_SIBLING_SEARCH_DEPTH,
    VARIANT_SWATCH_BUTTON_LIMIT,
    VARIANT_SWATCH_BUTTON_SELECTOR,
    VARIANT_SWATCH_PARENT_DEPTH,
)
from app.services.extract.variant_dom_cues import (
    select_variant_nodes as _select_variant_nodes,
    variant_context_noise_tokens as _variant_context_noise_tokens,
    variant_node_in_noise_context,
)
from app.services.extract.variant_axis import (
    normalized_variant_axis_key,
    resolve_machine_variant_group_name as _resolve_machine_variant_group_name,
    resolve_visible_variant_group_name as _resolve_visible_variant_group_name,
    semantic_group_label_from_text as _semantic_group_label_from_text,
    variant_axis_allowed_single_tokens as _variant_axis_allowed_single_tokens,
)
from app.services.extract.variant_option_value import (
    is_sequential_integer_run as _is_sequential_integer_run,
    select_option_texts_from_node as _select_option_texts,
    select_option_values_are_noise as _select_option_values_are_noise,
    value_looks_like_color as _value_looks_like_color,
)
from app.services.shared.field_coerce import clean_text, text_or_none

_ALNUM_SPLIT_PATTERN = r"[^a-z0-9]+"

_variant_group_attr_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_GROUP_ATTR_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_group_attr_noise_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_GROUP_ATTR_NOISE_PATTERNS or ())
    if str(pattern).strip()
)
_variant_size_value_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_SIZE_VALUE_PATTERNS or ())
    if str(pattern).strip()
)
_variant_quantity_attr_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_QUANTITY_ATTR_TOKENS or ())
    if str(token).strip()
)


def infer_variant_group_name(node: Any) -> str:
    if not hasattr(node, "get"):
        return ""
    parts: list[str] = []
    for attr_name in (
        "data-option-name",
        "data-testid",
        "data-qa-action",
        "id",
        "name",
        "class",
    ):
        value = node.get(attr_name)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
        elif value not in (None, "", [], {}):
            parts.append(str(value))
    probe = " ".join(parts).replace("_", " ").replace("-", " ").lower()
    probe_tokens = frozenset(
        token for token in re.split(_ALNUM_SPLIT_PATTERN, probe) if token
    )
    if VARIANT_COLOR_AXIS_TOKENS & probe_tokens:
        return "color"
    if VARIANT_SIZE_AXIS_TOKENS & probe_tokens:
        return "size"
    for token in probe_tokens:
        if (
            token in _variant_axis_allowed_single_tokens
            and token not in VARIANT_AXIS_EXCLUDED_SINGLE_TOKENS
        ):
            return token
    return ""


def variant_dom_cues_present(soup: Any) -> bool:
    return bool(iter_variant_select_groups(soup) or iter_variant_choice_groups(soup))


def _choice_option_text(node: Any, *, parent: Any | None = None) -> str:
    if node is None or not hasattr(node, "get"):
        return ""
    label_text = ""
    if str(getattr(node, "name", "") or "").strip().lower() in {"input", "button"}:
        label = _variant_input_label(parent or node, node)
        if label is not None:
            label_text = clean_text(label.get_text(" ", strip=True))
    node_text = (
        clean_text(node.get_text(" ", strip=True)) if hasattr(node, "get_text") else ""
    )
    return clean_text(
        node.get("data-attr-displayvalue")
        or node.get("data-displayvalue")
        or node.get("data-display-value")
        or node.get("data-swatch-sr")
        or label_text
        or node.get("data-value")
        or node.get("data-option-value")
        or node.get("aria-label")
        or node.get("value")
        or node_text
    )


def _variant_input_label(container: Any, input_node: Any) -> Any | None:
    input_id = (
        text_or_none(input_node.get("id")) if hasattr(input_node, "get") else None
    )
    if input_id and hasattr(container, "find"):
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


def _choice_option_texts(node: Any) -> list[str]:
    if not hasattr(node, "select"):
        return []
    values: list[str] = []
    for option in node.select(VARIANT_CHOICE_OPTION_SELECTOR)[
        : int(VARIANT_CHOICE_OPTION_LIMIT)
    ]:
        value = _choice_option_text(option, parent=node)
        if value:
            values.append(value)
    return values


def _descendant_variant_group_name(node: Any) -> str:
    if not hasattr(node, "select"):
        return ""
    for child in node.find_all(
        ["legend", "label", "h1", "h2", "h3", "h4", "h5", "h6", "div", "span"],
        limit=int(VARIANT_DESCENDANT_SCAN_LIMIT),
        recursive=False,
    ):
        child_tag = str(getattr(child, "name", "") or "").strip().lower()
        child_role = str(child.get("role") or "").strip().lower() if hasattr(child, "get") else ""
        if child_tag in {"a", "button", "input", "option"} or (
            hasattr(child, "get")
            and (
                child.get("data-selected") not in (None, "", [], {})
                or child.get("aria-selected") not in (None, "", [], {})
                or child_role in {"radio", "option"}
            )
        ) or (
            hasattr(child, "select")
            and child.select(
                "a[href], button, input[type='radio'], input[type='checkbox'], "
                "[role='radio'], [role='option'], [data-selected], [aria-selected]"
            )
        ):
            continue
        raw_value = clean_text(child.get_text(" ", strip=True))
        if not raw_value or len(raw_value.split()) > 4:
            continue
        if resolved_name := _resolve_visible_variant_group_name(raw_value):
            return resolved_name
    for child in node.select("label")[: int(VARIANT_DESCENDANT_SCAN_LIMIT)]:
        sr_only = child.select_one(".sr-only, .visually-hidden")
        raw_value = (
            sr_only.get_text(" ", strip=True)
            if sr_only is not None
            else child.get_text(" ", strip=True)
        )
        if resolved_name := _resolve_visible_variant_group_name(raw_value):
            return resolved_name
    for child in node.select(
        "[data-option-name], input[type='radio'], input[type='checkbox'], button"
    )[: int(VARIANT_DESCENDANT_SCAN_LIMIT)]:
        for attr_name in (
            "data-option-name",
            "name",
            "id",
            "data-testid",
            "data-qa-action",
        ):
            raw_value = child.get(attr_name)
            if raw_value in (None, "", [], {}):
                continue
            if resolved_name := _resolve_machine_variant_group_name(raw_value):
                return resolved_name
    return ""


def _node_supports_value_only_axis_inference(node: Any) -> bool:
    if not hasattr(node, "find"):
        return False
    if node.find("select") is not None:
        return True
    if node.find(attrs={"data-option-name": True}) is not None:
        return True
    if node.find("a", href=True) is not None:
        return True
    for input_type in ("radio", "checkbox"):
        if node.find("input", attrs={"type": input_type}) is not None:
            return True
    return False


def _descendant_variant_choice_inputs(node: Any, *, limit: int) -> list[Any]:
    if not hasattr(node, "find_all"):
        return []
    normalized_limit = max(1, int(limit))
    inputs: list[Any] = []
    for child in node.find_all(["input", "button"], limit=normalized_limit):
        tag_name = str(getattr(child, "name", "") or "").strip().lower()
        if tag_name == "button":
            inputs.append(child)
            continue
        input_type = str(child.get("type") or "").strip().lower() if hasattr(child, "get") else ""
        if input_type in {"radio", "checkbox"}:
            inputs.append(child)
    remaining = normalized_limit - len(inputs)
    if remaining <= 0:
        return inputs
    for child in node.find_all("a", attrs={"href": True}, limit=remaining):
        if _anchor_node_has_variant_signal(child):
            inputs.append(child)
    return inputs

def _anchor_node_has_variant_signal(node: Any) -> bool:
    href = text_or_none(node.get("href")) if hasattr(node, "get") else None
    if not href:
        return False
    href_lower = href.casefold()
    if any(marker in href_lower for marker in ("/product/", "/products/", "/p/", "?piid=", "&piid=", "variant=")):
        return True
    if any(
        node.get(attr) not in (None, "", [], {})
        for attr in ("data-selected", "aria-current", "aria-pressed")
    ):
        return True
    probe_parts: list[str] = []
    for attr_name in ("class", "id", "data-testid"):
        value = node.get(attr_name) if hasattr(node, "get") else None
        if isinstance(value, list):
            probe_parts.extend(str(item) for item in value if item)
        elif value not in (None, "", [], {}):
            probe_parts.append(str(value))
    probe = clean_text(" ".join(probe_parts)).lower()
    return any(
        token in probe for token in ("selected", "current", "checked", "variant", "swatch", "option")
    )


def _descendant_group_label_nodes(node: Any, *, limit: int) -> list[Any]:
    if not hasattr(node, "find_all"):
        return []
    normalized_limit = max(1, int(limit))
    groups: list[Any] = []
    seen_ids: set[int] = set()
    for child in node.find_all(attrs={"role": "radiogroup"}, limit=normalized_limit):
        groups.append(child)
        seen_ids.add(id(child))
    if len(groups) >= normalized_limit:
        return groups
    remaining = normalized_limit - len(groups)
    if remaining <= 0:
        return groups
    for child in node.find_all(attrs={"aria-label": True}, limit=remaining):
        child_id = id(child)
        if child_id in seen_ids:
            continue
        groups.append(child)
        seen_ids.add(child_id)
        if len(groups) >= normalized_limit:
            break
    return groups


def _variant_choice_container_is_overbroad(node: Any) -> bool:
    if not hasattr(node, "find_all"):
        return False
    if str(getattr(node, "name", "") or "").strip().lower() == "fieldset":
        return False
    if len(node.find_all("fieldset", limit=2)) >= 2:
        return True
    raw_names = {
        text_or_none(
            child.get("name")
            or child.get("data-option-name")
            or child.get("data-testid")
        )
        for child in _descendant_variant_choice_inputs(
            node,
            limit=int(VARIANT_CHOICE_CONTAINER_OPTION_LIMIT),
        )
    }
    distinct_names = {
        normalized_variant_axis_key(raw_name) or clean_text(raw_name).casefold()
        for raw_name in raw_names
        if raw_name
    }
    for select in node.find_all(
        "select",
        limit=int(VARIANT_CHOICE_CONTAINER_SELECT_LIMIT),
    ):
        raw_name = text_or_none(
            select.get("name")
            or select.get("aria-label")
            or select.get("data-option-name")
        )
        if raw_name:
            distinct_names.add(
                normalized_variant_axis_key(raw_name) or clean_text(raw_name).casefold()
            )
    for group_node in _descendant_group_label_nodes(
        node,
        limit=int(VARIANT_CHOICE_CONTAINER_GROUP_LIMIT),
    ):
        if str(getattr(group_node, "name", "") or "").strip().lower() in {
            "button",
            "a",
            "img",
            "input",
            "option",
        }:
            continue
        raw_name = text_or_none(group_node.get("aria-label"))
        if raw_name:
            distinct_names.add(
                normalized_variant_axis_key(raw_name) or clean_text(raw_name).casefold()
            )
    return len(distinct_names) >= int(VARIANT_CHOICE_CONTAINER_MIN_DISTINCT_NAMES)


def resolve_variant_group_name(node: Any) -> str:
    if not hasattr(node, "get"):
        return ""
    if _variant_group_node_attrs_are_noise(node):
        return ""
    inferred_name = infer_variant_group_name(node)
    visible_candidates: list[object] = []
    machine_candidates: list[object] = []
    tag_name = str(getattr(node, "name", "") or "").strip().lower()
    node_id = text_or_none(node.get("id"))
    if node_id and tag_name not in {"input", "button", "option"}:
        root = node
        while getattr(root, "parent", None) is not None:
            root = root.parent
        if hasattr(root, "find"):
            external_label = root.find("label", attrs={"for": node_id})
            if external_label is not None:
                visible_candidates.append(external_label.get_text(" ", strip=True))
    label = node.find_parent("label") if hasattr(node, "find_parent") else None
    if label is not None and tag_name not in {"input", "button", "option"}:
        visible_candidates.append(label.get_text(" ", strip=True))
    fieldset = (
        node
        if tag_name == "fieldset"
        else (node.find_parent("fieldset") if hasattr(node, "find_parent") else None)
    )
    if fieldset is not None:
        legend = fieldset.find("legend")
        if legend is not None:
            visible_candidates.append(legend.get_text(" ", strip=True))
    if _node_attr_can_hold_group_label(node):
        aria_label = node.get("aria-label")
        if aria_label not in (None, "", [], {}):
            visible_candidates.append(aria_label)
    machine_candidates.extend(
        node.get(attr_name)
        for attr_name in (
            "data-option-name",
            "name",
            "id",
            "data-testid",
            "data-qa-action",
        )
        if node.get(attr_name) not in (None, "", [], {})
    )
    for raw_name in [*visible_candidates, inferred_name]:
        if resolved_name := _resolve_visible_variant_group_name(raw_name):
            return resolved_name
    if descendant_name := _descendant_variant_group_name(node):
        return descendant_name
    for raw_name in machine_candidates:
        resolved_name = _resolve_machine_variant_group_name(raw_name)
        if resolved_name:
            return resolved_name
    if tag_name == "select":
        inferred_from_values = infer_variant_group_name_from_values(
            _select_option_texts(node)
        )
        if inferred_from_values == "size":
            return inferred_from_values
    if (
        tag_name != "select"
        and _node_supports_value_only_axis_inference(node)
        and (
            inferred_from_values := infer_variant_group_name_from_values(
                _choice_option_texts(node)
            )
        )
    ):
        return inferred_from_values
    if nearby := _nearby_variant_group_name(node):
        return nearby
    if hasattr(node, "select"):
        for child in node.select(
            "[data-option-name], [aria-label], [data-testid], [data-qa-action], [role='radio'], input, button"
        )[: int(VARIANT_DESCENDANT_SCAN_LIMIT)]:
            inferred_child = infer_variant_group_name(child)
            if inferred_child:
                return inferred_child
    return clean_text(inferred_name)


def infer_variant_group_name_from_values(values: Sequence[object]) -> str:
    cleaned_values = [
        clean_text(value) for value in list(values or []) if clean_text(value)
    ]
    if len(cleaned_values) < 2:
        return ""
    # Sequential integer runs are quantity selectors, not variant axes.
    if _is_sequential_integer_run(cleaned_values):
        return ""
    size_hits = sum(
        1
        for value in cleaned_values
        if any(pattern.fullmatch(value) for pattern in _variant_size_value_patterns)
    )
    if size_hits >= 2 and size_hits / len(cleaned_values) >= 0.5:
        return "size"
    color_hits = sum(1 for value in cleaned_values if _value_looks_like_color(value))
    if color_hits >= 2 and color_hits / len(cleaned_values) >= 0.5:
        return "color"
    return ""


def _variant_group_node_attrs_are_noise(node: Any) -> bool:
    if not hasattr(node, "get"):
        return False
    parts: list[str] = []
    for attr_name in (
        "aria-label",
        "data-option-name",
        "data-testid",
        "data-qa-action",
        "id",
        "name",
        "class",
    ):
        value = node.get(attr_name)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
        elif value not in (None, "", [], {}):
            parts.append(str(value))
    probe = clean_text(" ".join(parts)).lower()
    if not probe:
        return False
    if any(token in probe for token in _variant_group_attr_noise_tokens):
        return True
    if any(token in probe for token in _variant_context_noise_tokens):
        return True
    return any(pattern.search(probe) for pattern in _variant_group_attr_noise_patterns)


def _node_attr_can_hold_group_label(node: Any) -> bool:
    tag_name = str(getattr(node, "name", "") or "").strip().lower()
    role = str(node.get("role") or "").strip().lower()
    if role == "radiogroup":
        return True
    if tag_name in {"select", "fieldset"}:
        return True
    if tag_name in {"input", "button", "option", "img", "a"}:
        return False
    if not hasattr(node, "select"):
        return True
    input_count = len(node.select("input[type='radio'], input[type='checkbox']"))
    return input_count >= 2 or tag_name in {"div", "section", "ul", "ol", "form"}


def _nearby_variant_group_name(node: Any) -> str:
    current = node
    for _ in range(int(VARIANT_SIBLING_SEARCH_DEPTH)):
        sibling = getattr(current, "previous_sibling", None)
        while sibling is not None:
            if hasattr(sibling, "select") and sibling.select(
                "a[href], button, input[type='radio'], input[type='checkbox'], "
                "[role='radio'], [role='option']"
            ):
                sibling = getattr(sibling, "previous_sibling", None)
                continue
            if hasattr(sibling, "get_text"):
                sibling_text = sibling.get_text(" ", strip=True)
                extracted = _resolve_visible_variant_group_name(
                    sibling_text
                ) or _semantic_group_label_from_text(sibling_text)
                if extracted:
                    return extracted
            sibling = getattr(sibling, "previous_sibling", None)
        parent = getattr(current, "parent", None)
        if parent is None:
            break
        current = parent
    return ""


def _variant_group_has_multiple_options(node: Any) -> bool:
    if not hasattr(node, "select"):
        return False
    tag_name = str(getattr(node, "name", "") or "").strip().lower()
    if tag_name in {"button", "a", "img", "input", "option"}:
        return False
    option_nodes = node.select(
        "button, a[href], [role='radio'], [role='option'], input[type='radio'], "
        "input[type='checkbox'], [data-value], [data-option-value], "
        "[data-selected], [aria-selected], [data-state], option"
    )
    return len(option_nodes) >= 2


def _select_is_quantity_node(node: Any) -> bool:
    """Return True when the <select> element is a quantity picker."""
    if not hasattr(node, "get"):
        return False
    for attr_name in ("name", "id", "aria-label", "data-testid"):
        value = str(node.get(attr_name) or "").strip().lower()
        if not value:
            continue
        tokens = re.split(_ALNUM_SPLIT_PATTERN, value)
        if any(t in _variant_quantity_attr_tokens for t in tokens):
            return True
    return False


def iter_variant_select_groups(soup: Any) -> list[Any]:
    groups: list[Any] = []
    seen_ids: set[int] = set()
    for select in _select_variant_nodes(soup, VARIANT_SELECT_GROUP_SELECTOR):
        if _select_is_quantity_node(select):
            continue
        if _select_option_values_are_noise(select):
            continue
        if resolve_variant_group_name(select):
            groups.append(select)
            seen_ids.add(id(select))
        if len(groups) >= int(VARIANT_SELECT_GROUP_MAX):
            break
    if len(groups) >= int(VARIANT_SELECT_GROUP_MAX):
        return groups
    for select in _select_variant_nodes(soup, "select"):
        if id(select) in seen_ids:
            continue
        if _select_is_quantity_node(select):
            continue
        if _select_option_values_are_noise(select):
            continue
        if resolve_variant_group_name(select):
            groups.append(select)
            seen_ids.add(id(select))
        if len(groups) >= int(VARIANT_SELECT_GROUP_MAX):
            break
    return groups


def iter_variant_choice_groups(soup: Any) -> list[Any]:
    """Find variant groups via selectors, input inference, buttons, then swatch parents."""
    groups: list[Any] = []
    seen_ids: set[int] = set()
    for container in _select_variant_nodes(soup, VARIANT_CHOICE_GROUP_SELECTOR):
        if _variant_choice_container_is_overbroad(container):
            continue
        resolved_name = resolve_variant_group_name(container)
        if _variant_group_has_multiple_options(container) and (
            resolved_name
            or (
                _node_supports_value_only_axis_inference(container)
                and infer_variant_group_name_from_values(
                    _choice_option_texts(container)
                )
            )
        ):
            groups.append(container)
            seen_ids.add(id(container))
        if len(groups) >= int(VARIANT_CHOICE_GROUP_MAX):
            break
    if len(groups) >= int(VARIANT_CHOICE_GROUP_MAX):
        return groups
    # discovery of variant choice containers for input elements and specific buttons
    for node in soup.select("input[type='radio'], input[type='checkbox']"):
        if variant_node_in_noise_context(node):
            continue
        candidate = _variant_choice_container_for_input(node)
        if (
            candidate is not None
            and not variant_node_in_noise_context(candidate)
            and id(candidate) not in seen_ids
        ):
            groups.append(candidate)
            seen_ids.add(id(candidate))
            if len(groups) >= int(VARIANT_CHOICE_GROUP_MAX):
                break
    if len(groups) < int(VARIANT_CHOICE_GROUP_MAX):
        for node in soup.select(
            "button[data-variant], button.variant-option, button.size-option, button.color-option"
        ):
            if variant_node_in_noise_context(node):
                continue
            if id(node) not in seen_ids:
                groups.append(node)
                seen_ids.add(id(node))
                if len(groups) >= int(VARIANT_CHOICE_GROUP_MAX):
                    break
    # Fallback: discover containers of button / link / div swatches (e.g. YETI, Shopify visual swatches)
    if len(groups) < int(VARIANT_CHOICE_GROUP_MAX):
        all_btns = soup.select(VARIANT_SWATCH_BUTTON_SELECTOR)
        # Cap buttons to avoid O(n) blow-up on large rendered pages; variant groups are near top
        button_limit = int(VARIANT_SWATCH_BUTTON_LIMIT)
        btn_slice = (
            all_btns[:button_limit] if len(all_btns) > button_limit else all_btns
        )
        if btn_slice:
            # Cache parent sibling counts so we never re-select the same parent
            _parent_swatch_cache: dict[int, list[Any]] = {}
            for btn in btn_slice:
                if (
                    str(getattr(btn, "name", "") or "").strip().lower() == "a"
                    and not _anchor_node_has_variant_signal(btn)
                ):
                    continue
                parent = getattr(btn, "parent", None)
                depth = 0
                while parent is not None and depth < int(VARIANT_SWATCH_PARENT_DEPTH):
                    if not hasattr(parent, "select"):
                        parent = getattr(parent, "parent", None)
                        depth += 1
                        continue
                    if variant_node_in_noise_context(parent):
                        parent = getattr(parent, "parent", None)
                        depth += 1
                        continue
                    pid = id(parent)
                    if pid in seen_ids:
                        break
                    tag_name = str(getattr(parent, "name", "") or "").lower()
                    role = (
                        str(parent.get("role") or "").lower()
                        if hasattr(parent, "get")
                        else ""
                    )
                    class_attr = parent.get("class") if hasattr(parent, "get") else None
                    class_probe = (
                        " ".join(str(v) for v in class_attr)
                        if isinstance(class_attr, list)
                        else str(class_attr or "")
                    ).lower()
                    # Fast path: skip non-container tags unless they have explicit swatch hints
                    if tag_name not in {
                        "div",
                        "section",
                        "fieldset",
                        "ul",
                        "ol",
                        "nav",
                        "form",
                        "li",
                    } and not (
                        role == "radiogroup"
                        or any(
                            hint in class_probe
                            for hint in ("swatch", "variant", "color", "size", "option")
                        )
                    ):
                        parent = getattr(parent, "parent", None)
                        depth += 1
                        continue
                    siblings = _parent_swatch_cache.get(pid)
                    if siblings is None:
                        siblings = parent.select(VARIANT_SWATCH_BUTTON_SELECTOR)
                        _parent_swatch_cache[pid] = siblings
                    if len(siblings) >= 2:
                        if (
                            role == "radiogroup"
                            or tag_name in {"fieldset", "ul", "ol"}
                            or any(
                                hint in class_probe
                                for hint in (
                                    "color",
                                    "size",
                                    "swatch",
                                    "variant",
                                    "option",
                                    *_variant_axis_allowed_single_tokens,
                                )
                            )
                            or resolve_variant_group_name(parent)
                        ) and _variant_group_has_multiple_options(parent):
                            groups.append(parent)
                            seen_ids.add(pid)
                            if len(groups) >= int(VARIANT_CHOICE_GROUP_MAX):
                                break
                        # Stop walking up for this button once we found a sibling-rich parent
                        break
                    parent = getattr(parent, "parent", None)
                    depth += 1
                if len(groups) >= int(VARIANT_CHOICE_GROUP_MAX):
                    break
    return groups


def _variant_choice_container_for_input(
    node: Any, *, axis_name: str | None = None
) -> Any | None:
    if axis_name is None:
        axis_name = resolve_variant_group_name(node)
    input_type = (
        str(node.get("type") or "").strip().lower() if hasattr(node, "get") else ""
    )
    parent = getattr(node, "parent", None)
    while parent is not None:
        if not hasattr(parent, "find_all"):
            parent = getattr(parent, "parent", None)
            continue
        if variant_node_in_noise_context(parent):
            parent = getattr(parent, "parent", None)
            continue
        if _variant_choice_container_is_overbroad(parent):
            parent = getattr(parent, "parent", None)
            continue
        candidate_inputs = _descendant_variant_choice_inputs(
            parent,
            limit=max(
                int(VARIANT_CHOICE_CONTAINER_OPTION_LIMIT),
                int(VARIANT_MATCHING_INPUT_LIMIT),
            ),
        )
        if axis_name:
            matching_inputs = [
                item
                for item in candidate_inputs
                if resolve_variant_group_name(item) == axis_name
            ]
        else:
            matching_inputs = candidate_inputs
        class_attr = parent.get("class") if hasattr(parent, "get") else None
        class_probe = (
            " ".join(str(value) for value in class_attr)
            if isinstance(class_attr, list)
            else str(class_attr or "")
        ).lower()
        tag_name = str(getattr(parent, "name", "") or "").lower()
        role = str(parent.get("role") or "").lower() if hasattr(parent, "get") else ""
        parent_group_name = ""
        parent_has_axis_hint = (
            role == "radiogroup"
            or tag_name in {"fieldset", "ul", "ol"}
            or any(
                hint in class_probe
                for hint in (
                    "color",
                    "size",
                    "swatch",
                    "variant",
                    *_variant_axis_allowed_single_tokens,
                )
            )
        )
        parent_is_axis_container = parent_has_axis_hint
        if not parent_is_axis_container:
            parent_group_name = resolve_variant_group_name(parent)
            parent_is_axis_container = bool(parent_group_name)
        if (
            len(matching_inputs) == 1
            and axis_name in {"color", *_variant_axis_allowed_single_tokens}
            and parent_has_axis_hint
        ):
            return parent
        if len(matching_inputs) < 2:
            parent = getattr(parent, "parent", None)
            continue
        if input_type == "checkbox" and not (
            axis_name
            or parent_has_axis_hint
            or parent_group_name
        ):
            parent = getattr(parent, "parent", None)
            continue
        inferred_from_values = (
            infer_variant_group_name_from_values(_choice_option_texts(parent))
            if input_type != "checkbox" and _node_supports_value_only_axis_inference(parent)
            else ""
        )
        if parent_is_axis_container or inferred_from_values:
            return parent
        if (
            axis_name
            and len(matching_inputs) <= int(VARIANT_MATCHING_INPUT_LIMIT)
            and tag_name in {"div", "section"}
        ):
            return parent
        parent = getattr(parent, "parent", None)
    return None
