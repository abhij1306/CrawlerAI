from __future__ import annotations

__all__ = (
    "variant_context_noise_tokens",
    "variant_node_in_noise_context",
    "variant_scope_roots",
    "select_variant_nodes",
)

from typing import Any

from soupsieve import match as selector_matches

from app.services.config.extraction_rules import (
    DETAIL_VARIANT_SCOPE_SELECTOR,
    VARIANT_CHOICE_GROUP_SELECTOR,
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH,
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT,
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK,
    VARIANT_SCOPE_MAX_ROOTS,
    VARIANT_SELECT_GROUP_SELECTOR,
)
from app.services.config.variant_migration_rules import (
    DETAIL_VARIANT_SOFT_SCOPE_SELECTOR,
    VARIANT_CONTEXT_NOISE_TOKENS,
    VARIANT_SOFT_SCOPE_FIELDSET_SIGNAL_SELECTOR,
    VARIANT_SOFT_SCOPE_MIN_RADIO_INPUTS,
    VARIANT_SOFT_SCOPE_MIN_RADIO_INPUTS_FALLBACK,
    VARIANT_SOFT_SCOPE_ROLE_OPTION_SELECTOR,
    VARIANT_SOFT_SCOPE_STRONG_NODE_SELECTOR,
)
from app.services.shared.field_coerce import clean_text
from app.services.runtime_metrics import incr as increment_runtime_metric

variant_context_noise_tokens = VARIANT_CONTEXT_NOISE_TOKENS
_variant_scope_selector = str(DETAIL_VARIANT_SCOPE_SELECTOR or "").strip()
_variant_soft_scope_selector = str(DETAIL_VARIANT_SOFT_SCOPE_SELECTOR or "").strip()
_VARIANT_DOM_CACHE_ATTR = "_crawler_variant_dom_cues_cache"


def _variant_dom_cache(soup: Any) -> dict[object, object]:
    cache = getattr(soup, _VARIANT_DOM_CACHE_ATTR, None)
    if isinstance(cache, dict):
        return cache
    cache = {}
    try:
        setattr(soup, _VARIANT_DOM_CACHE_ATTR, cache)
    except Exception:
        return {}
    return cache


def _variant_scope_max_roots() -> int | None:
    try:
        return (
            int(VARIANT_SCOPE_MAX_ROOTS)
            if VARIANT_SCOPE_MAX_ROOTS is not None
            else None
        )
    except (TypeError, ValueError):
        return None


def variant_node_in_noise_context(node: Any) -> bool:
    try:
        depth = max(0, int(VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH))
    except (TypeError, ValueError):
        try:
            depth = max(0, int(VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK))
        except (TypeError, ValueError):
            depth = VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT
    current = node
    for _ in range(depth):
        if current is None or not hasattr(current, "get"):
            return False
        parts: list[str] = []
        for attr_name in ("id", "class", "aria-label", "data-testid", "role"):
            value = current.get(attr_name)
            if isinstance(value, list):
                parts.extend(str(item) for item in value if item)
            elif value not in (None, "", [], {}):
                parts.append(str(value))
        probe = clean_text(" ".join(parts)).lower()
        if probe and any(token in probe for token in variant_context_noise_tokens):
            return True
        current = getattr(current, "parent", None)
    return False


def variant_scope_roots(soup: Any) -> list[Any]:
    if not hasattr(soup, "select") or not _variant_scope_selector:
        return []
    max_roots = _variant_scope_max_roots()
    cache = _variant_dom_cache(soup)
    cache_key = ("variant_scope_roots", max_roots)
    cached = cache.get(cache_key)
    if isinstance(cached, tuple):
        return list(cached)
    roots: list[Any] = []
    seen: set[int] = set()
    for node in soup.select(_variant_scope_selector):
        if id(node) in seen or variant_node_in_noise_context(node):
            continue
        if not (
            node.select(VARIANT_SELECT_GROUP_SELECTOR)
            or node.select(VARIANT_CHOICE_GROUP_SELECTOR)
            or node.select("input[type='radio'], input[type='checkbox']")
        ):
            continue
        roots.append(node)
        seen.add(id(node))
        if max_roots is not None and len(roots) >= max_roots:
            break
    soft_limit = (
        None if max_roots is None else max(0, max_roots - len(roots))
    )
    soft_roots = (
        _variant_soft_scope_roots(soup, max_roots=soft_limit)
        if soft_limit != 0
        else []
    )
    for node in soft_roots:
        if id(node) in seen or _node_is_within_any_root(node, roots):
            continue
        roots.append(node)
        seen.add(id(node))
        if max_roots is not None and len(roots) >= max_roots:
            break
    if roots:
        cache[cache_key] = tuple(roots)
        return roots
    if not soft_roots:
        increment_runtime_metric("variant_scope_miss")
    cache[cache_key] = tuple(roots)
    return roots


def _variant_soft_scope_roots(soup: Any, *, max_roots: int | None) -> list[Any]:
    if not hasattr(soup, "select") or not _variant_soft_scope_selector:
        return []
    try:
        min_radio_inputs = max(1, int(VARIANT_SOFT_SCOPE_MIN_RADIO_INPUTS))
    except (TypeError, ValueError):
        min_radio_inputs = VARIANT_SOFT_SCOPE_MIN_RADIO_INPUTS_FALLBACK
    roots: list[Any] = []
    seen: set[int] = set()
    for node in soup.select(_variant_soft_scope_selector):
        if id(node) in seen or variant_node_in_noise_context(node):
            continue
        if not _node_has_soft_variant_signal(node, min_radio_inputs=min_radio_inputs):
            continue
        roots.append(node)
        seen.add(id(node))
        if max_roots is not None and len(roots) >= max_roots:
            break
    return roots


def _node_has_soft_variant_signal(node: Any, *, min_radio_inputs: int) -> bool:
    if not hasattr(node, "select"):
        return False
    tag_name = str(getattr(node, "name", "") or "").strip().lower()
    if tag_name == "select":
        return len(node.find_all("option")) >= 2 if hasattr(node, "find_all") else False
    if tag_name == "fieldset":
        return bool(node.select(VARIANT_SOFT_SCOPE_FIELDSET_SIGNAL_SELECTOR))
    role = str(node.get("role") or "").strip().lower() if hasattr(node, "get") else ""
    if (
        role in {"radiogroup", "group"}
        and len(node.select(VARIANT_SOFT_SCOPE_ROLE_OPTION_SELECTOR))
        >= min_radio_inputs
    ):
        return True
    strong_nodes = node.select(VARIANT_SOFT_SCOPE_STRONG_NODE_SELECTOR)
    clean_nodes = [
        candidate
        for candidate in strong_nodes
        if not variant_node_in_noise_context(candidate)
    ]
    if len(clean_nodes) >= min_radio_inputs:
        return True
    return bool(node.select(VARIANT_SELECT_GROUP_SELECTOR))


def _node_is_within_any_root(node: Any, roots: list[Any]) -> bool:
    current = getattr(node, "parent", None)
    while current is not None:
        if any(current is root for root in roots):
            return True
        current = getattr(current, "parent", None)
    return False


def select_variant_nodes(soup: Any, selector: str) -> list[Any]:
    cache = _variant_dom_cache(soup)
    cache_key = ("select_variant_nodes", str(selector or ""))
    cached = cache.get(cache_key)
    if isinstance(cached, tuple):
        return list(cached)
    nodes: list[Any] = []
    seen: set[int] = set()
    for root in variant_scope_roots(soup):
        if not hasattr(root, "select"):
            continue
        if _node_matches_selector(root, selector) and not variant_node_in_noise_context(
            root
        ):
            nodes.append(root)
            seen.add(id(root))
        for node in root.select(selector):
            if id(node) in seen or variant_node_in_noise_context(node):
                continue
            nodes.append(node)
            seen.add(id(node))
    cache[cache_key] = tuple(nodes)
    return nodes


def _node_matches_selector(node: Any, selector: str) -> bool:
    try:
        return bool(selector_matches(selector, node))
    except Exception:
        return False
