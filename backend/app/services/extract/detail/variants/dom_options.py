from __future__ import annotations

__all__ = (
    "node_state_matches",
    "node_attr_is_truthy",
    "variant_option_availability",
    "variant_option_url",
    "merge_variant_option_state",
    "variant_option_image_url",
)

import re
from typing import Any

from app.services.shared.field_coerce import absolute_url, clean_text, text_or_none


def node_state_matches(node: Any, *tokens: str) -> bool:
    if not hasattr(node, "get"):
        return False
    class_attr = node.get("class")
    probe = (
        [str(value) for value in class_attr]
        if isinstance(class_attr, list)
        else re.split(r"\s+", str(class_attr or ""))
    )
    class_names = {clean_text(value).lower() for value in probe if clean_text(value)}
    return any(token.lower() in class_names for token in tokens)


def node_attr_is_truthy(node: Any, *attr_names: str) -> bool:
    if not hasattr(node, "get"):
        return False
    for attr_name in attr_names:
        value = node.get(attr_name)
        if value in (None, "", [], {}, False):
            continue
        if value is True:
            return True
        normalized = str(value).strip().lower()
        if normalized in {"", "false", "0", "none"}:
            continue
        return True
    return False


def variant_option_availability(
    *, node: Any, label_node: Any | None
) -> tuple[str | None, int | None]:
    attr_probe_parts: list[str] = []
    text_probe_parts: list[str] = []
    for candidate in (
        node,
        label_node,
        getattr(node, "parent", None),
        getattr(label_node, "parent", None) if label_node is not None else None,
    ):
        if candidate is None or not hasattr(candidate, "get"):
            continue
        class_attr = candidate.get("class")
        if isinstance(class_attr, list):
            attr_probe_parts.extend(str(value) for value in class_attr if value)
        elif class_attr not in (None, "", [], {}):
            attr_probe_parts.append(str(class_attr))
        for attr_name in ("aria-label", "data-testid", "name", "id"):
            value = candidate.get(attr_name)
            if value not in (None, "", [], {}):
                attr_probe_parts.append(str(value))
        if hasattr(candidate, "get_text"):
            text_probe_parts.append(candidate.get_text(" ", strip=True))
    attr_probe = clean_text(" ".join(attr_probe_parts)).lower()
    text_probe = clean_text(" ".join(text_probe_parts)).lower()
    if any(
        token in attr_probe
        for token in ("outstock", "out-stock", "soldout", "sold-out", "unavailable")
    ):
        return "out_of_stock", 0
    stock_match = re.search(r"\b(\d+)\s+left\b", text_probe)
    if stock_match:
        quantity = int(stock_match.group(1))
        return ("in_stock" if quantity > 0 else "out_of_stock"), quantity
    if "out of stock" in text_probe or "sold out" in text_probe:
        return "out_of_stock", 0
    if "in stock" in text_probe or "available" in text_probe:
        return "in_stock", None
    return None, None


def variant_option_url(
    *,
    container: Any,
    node: Any,
    label_node: Any | None,
    page_url: str,
) -> str | None:
    attr_names = (
        "href",
        "data-href",
        "data-url",
        "data-product-url",
        "data-target-url",
        "data-link",
        "data-variant-url",
    )
    candidates: list[Any] = [node, label_node]
    if hasattr(node, "find_parent"):
        parent_anchor = node.find_parent("a", href=True)
        if parent_anchor is not None:
            candidates.append(parent_anchor)
    if label_node is not None and hasattr(label_node, "find_parent"):
        parent_anchor = label_node.find_parent("a", href=True)
        if parent_anchor is not None:
            candidates.append(parent_anchor)
    if hasattr(node, "find"):
        anchor = node.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    if label_node is not None and hasattr(label_node, "find"):
        anchor = label_node.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    if hasattr(container, "find"):
        anchor = container.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    for candidate in candidates:
        if candidate is None or not hasattr(candidate, "get"):
            continue
        for attr_name in attr_names:
            raw = candidate.get(attr_name)
            url = text_or_none(raw)
            if url:
                return absolute_url(page_url, url)
    return None


def merge_variant_option_state(
    entry: dict[str, object],
    *,
    container: Any,
    node: Any,
    page_url: str,
    label_node: Any | None = None,
) -> None:
    selected = (
        node_state_matches(
            node, "selected", "active", "current", "highlight", "checked"
        )
        or node_attr_is_truthy(
            node,
            "checked",
            "aria-checked",
        )
        or text_or_none(
            getattr(node, "get", lambda *_args, **_kwargs: None)("data-state")
        )
        == "checked"
    )
    entry["selected"] = bool(selected)
    availability, stock_quantity = variant_option_availability(
        node=node, label_node=label_node
    )
    if availability and entry.get("availability") in (None, "", [], {}):
        entry["availability"] = availability
    if stock_quantity is not None and entry.get("stock_quantity") in (None, "", [], {}):
        entry["stock_quantity"] = stock_quantity
    option_url = variant_option_url(
        container=container,
        node=node,
        label_node=label_node,
        page_url=page_url,
    )
    if option_url and entry.get("url") in (None, "", [], {}):
        entry["url"] = option_url
    image_url = variant_option_image_url(
        node=node,
        label_node=label_node,
        page_url=page_url,
    )
    if image_url and entry.get("image_url") in (None, "", [], {}):
        entry["image_url"] = image_url


def variant_option_image_url(
    *,
    node: Any,
    label_node: Any | None,
    page_url: str,
) -> str | None:
    for candidate in (node, label_node):
        if candidate is None or not hasattr(candidate, "find"):
            continue
        image = candidate.find("img")
        if image is None or not hasattr(image, "get"):
            continue
        raw_url = image.get("src") or image.get("data-src")
        if text_or_none(raw_url):
            return absolute_url(page_url, raw_url)
    return None
