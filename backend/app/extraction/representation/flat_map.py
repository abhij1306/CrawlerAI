from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from selectolax.lexbor import LexborNode

from app.core.config.evaluation import EXTRACTION_V3_FLAT_MAP_EXCLUDED_TAGS
from app.extraction.documents import HtmlDocument


@dataclass(frozen=True, slots=True)
class FlatMapEntry:
    path: str
    text: str


FlatMap = OrderedDict[str, str]


def build_flat_map(document: HtmlDocument, *, root_path: str | None = None) -> FlatMap:
    """Build an ordered absolute-path to text map for text-bearing DOM nodes."""
    root = _root_node(document, root_path)
    entries: list[FlatMapEntry] = []
    if root is None:
        return OrderedDict()
    for node in root.traverse(include_text=False):
        if _excluded(node):
            continue
        direct_text = _direct_text(node)
        if direct_text:
            entries.append(FlatMapEntry(path=_absolute_path(node), text=direct_text))
    return OrderedDict((entry.path, entry.text) for entry in entries)


def flat_map_token_count(flat_map: FlatMap) -> int:
    return sum(
        _rough_token_count(path) + _rough_token_count(text)
        for path, text in flat_map.items()
    )


def chunk_flat_map(flat_map: FlatMap, *, target_tokens: int) -> tuple[FlatMap, ...]:
    chunks: list[FlatMap] = []
    current: FlatMap = OrderedDict()
    current_tokens = 0
    for path, text in flat_map.items():
        entry_tokens = _rough_token_count(path) + _rough_token_count(text)
        if current and current_tokens + entry_tokens > target_tokens:
            chunks.append(current)
            current = OrderedDict()
            current_tokens = 0
        current[path] = text
        current_tokens += entry_tokens
    if current:
        chunks.append(current)
    return tuple(chunks)


def _root_node(document: HtmlDocument, root_path: str | None) -> LexborNode | None:
    if root_path:
        for node in document.nodes():
            if node.dom_path() == root_path:
                return node.node
    body = document.css_first("body")
    if body is not None:
        return body.node
    html = document.css_first("html")
    return html.node if html is not None else None


def _excluded(node: LexborNode) -> bool:
    tag = str(node.tag or "").lower()
    if (
        not tag
        or tag.startswith("-")
        or tag == "#document"
        or tag in EXTRACTION_V3_FLAT_MAP_EXCLUDED_TAGS
    ):
        return True
    parent = node.parent
    while parent is not None:
        parent_tag = str(parent.tag or "").lower()
        if parent_tag in EXTRACTION_V3_FLAT_MAP_EXCLUDED_TAGS:
            return True
        parent = parent.parent
    return False


def _direct_text(node: LexborNode) -> str:
    pieces: list[str] = []
    child = node.child
    while child is not None:
        if child.is_text_node:
            text = str(child.text() or "").strip()
            if text:
                pieces.append(text)
        child = child.next
    return " ".join(" ".join(pieces).split())


def _absolute_path(node: LexborNode) -> str:
    parts: list[str] = []
    current: LexborNode | None = node
    while current is not None:
        tag = str(current.tag or "").lower()
        if not tag or tag.startswith("-"):
            break
        if tag == "#document":
            current = current.parent
            continue
        parent = current.parent
        parent_tag = str(parent.tag or "").lower() if parent is not None else ""
        index = 1
        if parent is not None and parent_tag != "#document":
            sibling = parent.child
            while sibling is not None:
                if _same_node(sibling, current):
                    break
                sibling_tag = str(sibling.tag or "").lower()
                if _same_node(sibling.parent, parent) and sibling_tag == tag:
                    index += 1
                sibling = sibling.next
        parts.append(f"{tag}[{index}]")
        current = parent
    return "/" + "/".join(reversed(parts))


def _rough_token_count(value: str) -> int:
    compact = " ".join(str(value or "").split())
    if not compact:
        return 0
    return max(1, (len(compact) + 3) // 4)


def _same_node(left: LexborNode | None, right: LexborNode | None) -> bool:
    if left is None or right is None:
        return left is right
    return int(left.mem_id) == int(right.mem_id)
