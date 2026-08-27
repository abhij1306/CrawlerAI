from __future__ import annotations

from collections.abc import Iterable

from app.core.config import extraction_rules as rules
from app.core.config.extraction_rules import (
    DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS,
    DETAIL_DOM_PRODUCT_ROOT_POSITIVE_SELECTORS,
    DETAIL_DOM_PRODUCT_ROOT_SELECTORS,
    DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS,
    DETAIL_TEXT_SCOPE_OVERLAY_TOKENS,
    DETAIL_TEXT_SCOPE_PRIORITY_TOKENS,
)
from app.extraction.documents import HtmlDocument, HtmlNode


def product_root_nodes(doc: HtmlDocument) -> tuple[HtmlNode, ...]:
    roots: list[HtmlNode] = []
    seen: set[int] = set()
    for selector in DETAIL_DOM_PRODUCT_ROOT_SELECTORS:
        for node in doc.safe_css(selector):
            identity = node.identity()
            if identity in seen or node_context_excluded(node):
                continue
            if not any(
                node.safe_css(positive)
                for positive in DETAIL_DOM_PRODUCT_ROOT_POSITIVE_SELECTORS
            ):
                continue
            roots.append(node)
            seen.add(identity)
    return tuple(roots)


def root_selector_nodes(
    roots: tuple[HtmlNode, ...], selectors: tuple[str, ...], limit: int | None = None
) -> Iterable[HtmlNode]:
    return (
        node
        for root in roots
        for selector in selectors
        for node in root.safe_css(selector)[:limit]
    )


def node_within_roots(node: HtmlNode, root_ids: set[int]) -> bool:
    return node.identity() in root_ids or any(
        ancestor.identity() in root_ids for ancestor in node.ancestors()
    )


def node_context_excluded(node: HtmlNode) -> bool:
    context_nodes = tuple(_component_ancestors(node))
    context = " ".join(
        str(current.attribute(attribute) or "").casefold()
        for current in context_nodes
        for attribute in rules.DETAIL_DOM_IMAGE_SCOPE_ATTRIBUTES
    )
    tokens = (*DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS, *DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS)
    matched = {token for token in tokens if token in context}
    if matched and matched <= DETAIL_TEXT_SCOPE_OVERLAY_TOKENS:
        return not any(token in context for token in DETAIL_TEXT_SCOPE_PRIORITY_TOKENS)
    return bool(matched)


def _component_ancestors(node: HtmlNode) -> Iterable[HtmlNode]:
    yield node
    for ancestor in node.ancestors()[:8]:
        if ancestor.tag() in {"body", "html"}:
            break
        yield ancestor
