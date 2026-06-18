from __future__ import annotations

__all__ = (
    "build_variant_candidate_group",
    "node_class_tokens",
    "ancestor_class_tokens",
    "variant_scope_source",
    "variant_option_node_types",
    "variant_option_node_type",
    "node_matches_selector",
    "weak_variant_option_node_allowed",
    "anchor_is_variant_candidate",
    "anchor_has_selected_variant_signal",
)

from typing import Any
from urllib.parse import urlsplit

from soupsieve import match as selector_matches

from app.services.config.extraction_rules import DETAIL_VARIANT_SCOPE_SELECTOR
from app.services.config.variant_migration_rules import (
    VARIANT_OPTION_ATTRIBUTE_NAMES,
    VARIANT_SCOPE_SOURCE_SOFT,
    VARIANT_SCOPE_SOURCE_TRUSTED,
    VARIANT_SELECTED_SIGNAL_ATTRIBUTE_NAMES,
    VARIANT_SELECTED_SIGNAL_TOKENS,
    VARIANT_SELECTED_SIGNAL_TRUE_VALUES,
    VARIANT_STRONG_OPTION_SELECTOR,
    VARIANT_WEAK_OPTION_SELECTOR,
)
from app.services.extract.variant_axis import normalized_variant_axis_key
from app.services.extract.variant_group_validator import VariantCandidateGroup
from app.services.shared.field_coerce import absolute_url, clean_text, text_or_none


def build_variant_candidate_group(
    node: Any,
    *,
    name: str,
    values: list[str],
    entries: list[dict[str, object]],
    extractor_path: str,
) -> VariantCandidateGroup:
    return VariantCandidateGroup(
        name=name,
        axis_key=normalized_variant_axis_key(name),
        values=values,
        entries=entries,
        container_tag=str(getattr(node, "name", "") or "").strip().lower(),
        container_classes=node_class_tokens(node),
        container_id=(
            text_or_none(node.get("id") or node.get("data-testid"))
            if hasattr(node, "get")
            else None
        ),
        container_role=text_or_none(node.get("role")) if hasattr(node, "get") else None,
        ancestor_class_tokens=ancestor_class_tokens(node),
        extractor_path=extractor_path,
        scope_source=variant_scope_source(node),
        option_node_types=variant_option_node_types(node, extractor_path=extractor_path),
    )


def node_class_tokens(node: Any) -> list[str]:
    if not hasattr(node, "get"):
        return []
    raw = node.get("class")
    if isinstance(raw, list):
        return [clean_text(value).lower() for value in raw if clean_text(value)]
    return [clean_text(raw).lower()] if clean_text(raw) else []


def ancestor_class_tokens(node: Any) -> list[str]:
    tokens: list[str] = []
    current = getattr(node, "parent", None)
    while current is not None and len(tokens) < 12:
        if hasattr(current, "get"):
            tokens.extend(node_class_tokens(current))
            if node_id := text_or_none(current.get("id")):
                tokens.append(node_id.lower())
        current = getattr(current, "parent", None)
    return tokens[:12]


def variant_scope_source(node: Any) -> str:
    current = node
    while current is not None:
        if node_matches_selector(current, str(DETAIL_VARIANT_SCOPE_SELECTOR or "")):
            return VARIANT_SCOPE_SOURCE_TRUSTED
        current = getattr(current, "parent", None)
    return VARIANT_SCOPE_SOURCE_SOFT


def variant_option_node_types(node: Any, *, extractor_path: str) -> list[str]:
    if extractor_path == "select":
        return ["option"]
    if not hasattr(node, "select"):
        return []
    option_nodes = list(node.select(str(VARIANT_STRONG_OPTION_SELECTOR)))
    if len(option_nodes) < 2:
        option_nodes = list(node.select(str(VARIANT_WEAK_OPTION_SELECTOR)))
    types = [variant_option_node_type(option) for option in option_nodes]
    return list(dict.fromkeys(item for item in types if item))


def variant_option_node_type(node: Any) -> str:
    tag_name = str(getattr(node, "name", "") or "").strip().lower()
    role = str(node.get("role") or "").strip().lower() if hasattr(node, "get") else ""
    input_type = str(node.get("type") or "").strip().lower() if hasattr(node, "get") else ""
    if hasattr(node, "get") and node.get("data-selected") not in (None, "", [], {}):
        return "data_selected"
    if tag_name == "input" and input_type in {"radio", "checkbox"}:
        return f"input_{input_type}"
    if role in {"radio", "option"}:
        return f"role_{role}"
    return tag_name


def node_matches_selector(node: Any, selector: str) -> bool:
    if not selector:
        return False
    try:
        return bool(selector_matches(selector, node))
    except Exception:
        return False


def weak_variant_option_node_allowed(node: Any, *, container: Any, page_url: str) -> bool:
    if str(getattr(node, "name", "") or "").strip().lower() != "a":
        return True
    if not hasattr(node, "get"):
        return False
    if any(
        node.get(attr) not in (None, "", [], {})
        for attr in VARIANT_OPTION_ATTRIBUTE_NAMES
    ):
        return True
    if anchor_has_selected_variant_signal(node):
        return True
    if _anchor_has_inline_variant_option_signal(node, container=container):
        return True
    role = str(container.get("role") or "").strip().lower() if hasattr(container, "get") else ""
    if role == "radiogroup" and text_or_none(node.get("aria-label")):
        return True
    return anchor_is_variant_candidate(node, page_url=page_url)


def anchor_is_variant_candidate(node: Any, *, page_url: str) -> bool:
    href = text_or_none(node.get("href")) if hasattr(node, "get") else None
    if not href:
        return False
    return urlsplit(absolute_url(page_url, href)).path.rstrip("/") != urlsplit(
        page_url
    ).path.rstrip("/")


def anchor_has_selected_variant_signal(node: Any) -> bool:
    if not hasattr(node, "get"):
        return False
    for attr in VARIANT_SELECTED_SIGNAL_ATTRIBUTE_NAMES:
        raw = text_or_none(node.get(attr))
        if raw and raw.strip().lower() in VARIANT_SELECTED_SIGNAL_TRUE_VALUES:
            return True
    probe_parts: list[str] = []
    for attr_name in ("class", "id", "data-testid"):
        value = node.get(attr_name)
        if isinstance(value, list):
            probe_parts.extend(str(item) for item in value if item)
        elif value not in (None, "", [], {}):
            probe_parts.append(str(value))
    probe = clean_text(" ".join(probe_parts)).lower()
    return any(token in probe for token in VARIANT_SELECTED_SIGNAL_TOKENS)


def _node_attr_probe_parts(node: Any, attr_names: tuple[str, ...]) -> list[str]:
    parts: list[str] = []
    if not hasattr(node, "get"):
        return parts
    for attr_name in attr_names:
        value = node.get(attr_name)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
        elif value not in (None, "", [], {}):
            parts.append(str(value))
    return parts


def _anchor_has_inline_variant_option_signal(node: Any, *, container: Any) -> bool:
    option_label = text_or_none(
        node.get("title") or node.get("aria-label")
    ) or (
        clean_text(node.get_text(" ", strip=True)) if hasattr(node, "get_text") else None
    )
    if not option_label and hasattr(node, "select_one"):
        image = node.select_one("img[alt]")
        if image is not None and hasattr(image, "get"):
            option_label = text_or_none(image.get("alt"))
    if not option_label:
        return False
    node_probe_parts = _node_attr_probe_parts(
        node, ("class", "id", "data-testid", "title", "aria-label")
    )
    container_probe_parts = _node_attr_probe_parts(
        container, ("class", "id", "data-option-name", "aria-label")
    )
    probe = clean_text(" ".join([*node_probe_parts, *container_probe_parts])).lower()
    return any(token in probe for token in ("swatch", "size", "color", "colour", "variant"))
