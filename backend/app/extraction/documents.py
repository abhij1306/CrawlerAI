from __future__ import annotations

import json
import hashlib
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode


logger = logging.getLogger(__name__)

_NON_VISIBLE_TAGS = {"script", "style", "noscript"}


def _collapsed_visible_text(root: LexborNode) -> str:
    # Whitespace-collapsed text under ``root``, skipping text inside
    # script/style/noscript so CSS/JS source never leaks into scraped text.
    pieces: list[str] = []
    for node in root.traverse(include_text=True):
        if not node.is_text_node:
            continue
        parent = node.parent
        hidden = False
        while parent is not None:
            if str(parent.tag or "").lower() in _NON_VISIBLE_TAGS:
                hidden = True
                break
            parent = parent.parent
        if not hidden:
            text = str(node.text() or "").strip()
            if text:
                pieces.append(text)
    return " ".join(" ".join(pieces).split())


# ``HtmlNode`` helper groups, extracted as module-level functions over the raw
# lexbor node so the public wrapper class below stays a thin artifact_id-aware
# shell. Kept in this module because selectolax usage is confined to
# documents.py by the extraction architecture tests.
def _node_direct_text(node: LexborNode) -> str:
    pieces: list[str] = []
    child = node.child
    while child is not None:
        if child.is_text_node:
            text = str(child.text() or "").strip()
            if text:
                pieces.append(text)
        child = child.next
    return " ".join(" ".join(pieces).split())


def _node_child_elements(node: LexborNode) -> tuple[LexborNode, ...]:
    # Direct element children (no text/comment nodes), in document order.
    return tuple(
        child
        for child in node.iter()
        if not child.is_text_node
        and str(child.tag or "")
        and not str(child.tag).startswith("-")
    )


def _node_previous_element(node: LexborNode) -> LexborNode | None:
    sibling = node.prev
    while sibling is not None and str(sibling.tag or "").startswith("-"):
        sibling = sibling.prev
    return sibling


def _node_attribute(node: LexborNode, name: str) -> str | None:
    if name not in node.attributes:
        return None
    value = node.attributes.get(name)
    return "" if value is None else str(value)


def _node_dom_path(node: LexborNode) -> str:
    parts: list[str] = []
    current: LexborNode | None = node
    while current is not None:
        tag = str(current.tag or "").lower()
        if not tag or tag.startswith("-"):
            break
        parent = current.parent
        index = 1
        if parent is not None:
            # Selectolax returns a fresh wrapper per access, so nodes must be
            # compared by mem_id (address), never `is`. parent.iter() yields
            # the direct children in document order.
            current_id = int(current.mem_id)
            for sibling in parent.iter():
                if int(sibling.mem_id) == current_id:
                    break
                if str(sibling.tag or "").lower() == tag:
                    index += 1
        parts.append(f"{tag}[{index}]")
        current = parent
    return "/" + "/".join(reversed(parts))


def _node_json(node: LexborNode) -> object:
    text = node.text(separator=" ", strip=True)
    try:
        return json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        return None


def _node_ancestors(node: LexborNode) -> tuple[LexborNode, ...]:
    nodes: list[LexborNode] = []
    current = node.parent
    while current is not None:
        nodes.append(current)
        current = current.parent
    return tuple(nodes)


def _node_siblings(node: LexborNode) -> tuple[LexborNode, ...]:
    parent = node.parent
    if parent is None:
        return ()
    return tuple(
        sibling
        for sibling in parent.iter()
        if sibling.parent is parent and sibling is not node
    )


def _node_following_siblings(node: LexborNode) -> tuple[LexborNode, ...]:
    nodes: list[LexborNode] = []
    current = node.next
    while current is not None:
        nodes.append(current)
        current = current.next
    return tuple(nodes)


def _node_stable_locator(node: LexborNode) -> str:
    tag = str(node.tag or "*")
    node_id = _node_attribute(node, "id")
    if node_id:
        return f"{tag}#{node_id}"
    classes = " ".join((_node_attribute(node, "class") or "").split()[:3])
    return f"{tag}.{classes}" if classes else tag


def _node_is_hidden(node: LexborNode) -> bool:
    if _node_attribute(node, "hidden") is not None:
        return True
    aria_hidden = (_node_attribute(node, "aria-hidden") or "").strip().lower()
    if aria_hidden == "true":
        return True
    style = (_node_attribute(node, "style") or "").replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style


@dataclass(frozen=True)
class HtmlNode:
    artifact_id: str
    node: LexborNode

    def css(self, selector: str) -> tuple[HtmlNode, ...]:
        return tuple(
            HtmlNode(self.artifact_id, node) for node in self.node.css(selector)
        )

    def safe_css(self, selector: str) -> tuple[HtmlNode, ...]:
        try:
            return self.css(selector)
        except Exception:
            logger.debug(
                "CSS selector evaluation failed for %r", selector, exc_info=True
            )
            return ()

    def css_first(self, selector: str) -> HtmlNode | None:
        node = self.node.css_first(selector)
        return HtmlNode(self.artifact_id, node) if node is not None else None

    def text(self, *, separator: str = " ", strip: bool = True) -> str:
        return self.node.text(separator=separator, strip=strip)

    def direct_text(self) -> str:
        return _node_direct_text(self.node)

    def content_text(self) -> str:
        # Like text(), but excludes text inside script/style/noscript. Inline
        # <style>/<script> blocks otherwise leak CSS/JS source (e.g. a selector
        # string) into scraped titles. Shares the walk with visible_text().
        return _collapsed_visible_text(self.node)

    def child_elements(self) -> tuple[HtmlNode, ...]:
        return tuple(
            HtmlNode(self.artifact_id, child)
            for child in _node_child_elements(self.node)
        )

    def tag(self) -> str:
        return str(self.node.tag or "").lower()

    def parent(self) -> HtmlNode | None:
        parent = self.node.parent
        return HtmlNode(self.artifact_id, parent) if parent is not None else None

    def previous_element(self) -> HtmlNode | None:
        sibling = _node_previous_element(self.node)
        return HtmlNode(self.artifact_id, sibling) if sibling is not None else None

    def attribute(self, name: str) -> str | None:
        return _node_attribute(self.node, name)

    def attributes(self) -> Mapping[str, str]:
        return {str(key): str(value) for key, value in self.node.attributes.items()}

    def identity(self) -> int:
        return int(self.node.mem_id)

    def dom_path(self) -> str:
        return _node_dom_path(self.node)

    def json(self) -> object:
        return _node_json(self.node)

    def ancestors(self) -> tuple[HtmlNode, ...]:
        return tuple(
            HtmlNode(self.artifact_id, node) for node in _node_ancestors(self.node)
        )

    def siblings(self) -> tuple[HtmlNode, ...]:
        return tuple(
            HtmlNode(self.artifact_id, node) for node in _node_siblings(self.node)
        )

    def following_siblings(self) -> tuple[HtmlNode, ...]:
        return tuple(
            HtmlNode(self.artifact_id, node)
            for node in _node_following_siblings(self.node)
        )

    def html(self) -> str:
        return str(self.node.html or "")

    def stable_locator(self) -> str:
        return _node_stable_locator(self.node)

    def is_hidden(self) -> bool:
        return _node_is_hidden(self.node)


class HtmlDocument:
    def __init__(self, artifact_id: str, html: str) -> None:
        self.artifact_id = artifact_id
        self._html = html
        self.content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
        self._parser = LexborHTMLParser(html)

    def css(self, selector: str) -> tuple[HtmlNode, ...]:
        return tuple(
            HtmlNode(self.artifact_id, node) for node in self._parser.css(selector)
        )

    def css_first(self, selector: str) -> HtmlNode | None:
        node = self._parser.css_first(selector)
        return HtmlNode(self.artifact_id, node) if node is not None else None

    def nodes(self) -> tuple[HtmlNode, ...]:
        return self.css("*")

    def safe_css(self, selector: str) -> tuple[HtmlNode, ...]:
        try:
            return self.css(selector)
        except Exception:
            logger.debug(
                "CSS selector evaluation failed for %r", selector, exc_info=True
            )
            return ()

    def text(self) -> str:
        return self._parser.text(separator=" ", strip=True)

    def visible_text(self) -> str:
        root = self._parser.body or self._parser.root
        if root is None:
            return ""
        return _collapsed_visible_text(root)

    def html(self) -> str:
        return self._html

    def matches_html(self, html: str) -> bool:
        text = str(html or "")
        return (
            self.content_hash == hashlib.sha256(text.encode("utf-8")).hexdigest()
            and self._html == text
        )


@dataclass(frozen=True, slots=True)
class HtmlAnalysis:
    html: str
    document: HtmlDocument
    visible_text: str
    normalized_text: str
    title_text: str
    h1_present: bool
    # Lazily computed lowercase copy of ``html`` — many analyses never need
    # it, so the second full-page string is only materialized (and cached) on
    # first access instead of being retained eagerly alongside the parser.
    _lowered_html: str | None = field(
        default=None, init=False, repr=False, compare=False
    )

    @classmethod
    def from_html(cls, html: str) -> HtmlAnalysis:
        text = str(html or "")
        document = HtmlDocument("html", text)
        visible_text = document.visible_text()
        title = document.css_first("title")
        return cls(
            html=text,
            document=document,
            visible_text=visible_text,
            normalized_text=" ".join(visible_text.split()),
            title_text=" ".join((title.text() if title else "").split()),
            h1_present=document.css_first("h1") is not None,
        )

    @property
    def lowered_html(self) -> str:
        lowered = self._lowered_html
        if lowered is None:
            lowered = self.html.lower()
            object.__setattr__(self, "_lowered_html", lowered)
        return lowered

    def matches_html(self, html: str) -> bool:
        return self.document.matches_html(html)


@dataclass(frozen=True)
class JsonDocument:
    artifact_id: str
    value: Any


class DocumentStore:
    def __init__(
        self,
        payloads: dict[str, Any],
        *,
        html_documents: Mapping[str, HtmlDocument] | None = None,
    ) -> None:
        self._payloads = dict(payloads)
        self._html_cache = {
            artifact_id: document
            for artifact_id, document in (html_documents or {}).items()
            if document.matches_html(str(self._payloads.get(artifact_id) or ""))
        }
        self._json_cache: dict[str, JsonDocument] = {}

    def html(self, artifact_id: str) -> HtmlDocument:
        if artifact_id not in self._html_cache:
            self._html_cache[artifact_id] = HtmlDocument(
                artifact_id, self.text(artifact_id)
            )
        return self._html_cache[artifact_id]

    def json(self, artifact_id: str) -> JsonDocument:
        if artifact_id not in self._json_cache:
            value = self._payloads.get(artifact_id)
            if isinstance(value, str):
                value = json.loads(value)
            self._json_cache[artifact_id] = JsonDocument(artifact_id, value)
        return self._json_cache[artifact_id]

    def text(self, artifact_id: str) -> str:
        return str(self._payloads.get(artifact_id) or "")

    def artifact_ids(self) -> Iterable[str]:
        return tuple(self._payloads)
