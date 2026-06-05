"""Small BeautifulSoup DOM query helpers shared by extraction modules."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any

from bs4 import BeautifulSoup, Tag
from soupsieve import SelectorSyntaxError

__all__ = (
    "iter_tag_children",
    "node_text",
    "safe_find",
    "safe_select",
    "walk_ancestors",
)

logger = logging.getLogger(__name__)

DomNode = BeautifulSoup | Tag


def safe_select(root: Any, selector: str) -> list[Tag]:
    if not selector or not hasattr(root, "select"):
        return []
    try:
        return [node for node in root.select(selector) if isinstance(node, Tag)]
    except SelectorSyntaxError:
        logger.warning("Skipping invalid css selector: %s", selector)
        return []


def safe_find(root: Any, *args: Any, **kwargs: Any) -> Any | None:
    if not hasattr(root, "find"):
        return None
    return root.find(*args, **kwargs)


def node_text(node: Any, separator: str = " ", *, strip: bool = True) -> str:
    if not hasattr(node, "get_text"):
        return ""
    return str(node.get_text(separator, strip=strip))


def iter_tag_children(node: Any) -> Iterator[Tag]:
    for child in getattr(node, "children", ()) or ():
        if isinstance(child, Tag):
            yield child


def walk_ancestors(
    node: DomNode,
    predicate: Callable[[DomNode, int], bool],
    *,
    max_depth: int | None = None,
    stop_at: Callable[[DomNode, int], bool] | None = None,
    include_self: bool = True,
) -> DomNode | None:
    current: Any = node if include_self else getattr(node, "parent", None)
    depth = 0
    while isinstance(current, (BeautifulSoup, Tag)):
        if max_depth is not None and depth >= max_depth:
            return None
        if stop_at is not None and stop_at(current, depth):
            return None
        if predicate(current, depth):
            return current
        current = getattr(current, "parent", None)
        depth += 1
    return None
