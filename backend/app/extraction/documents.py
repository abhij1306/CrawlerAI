from __future__ import annotations

import json
import hashlib
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode


logger = logging.getLogger(__name__)


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
        pieces: list[str] = []
        child = self.node.child
        while child is not None:
            if child.is_text_node:
                text = str(child.text() or "").strip()
                if text:
                    pieces.append(text)
            child = child.next
        return " ".join(" ".join(pieces).split())

    def tag(self) -> str:
        return str(self.node.tag or "").lower()

    def parent(self) -> HtmlNode | None:
        parent = self.node.parent
        return HtmlNode(self.artifact_id, parent) if parent is not None else None

    def attribute(self, name: str) -> str | None:
        if name not in self.node.attributes:
            return None
        value = self.node.attributes.get(name)
        return "" if value is None else str(value)

    def attributes(self) -> Mapping[str, str]:
        return {str(key): str(value) for key, value in self.node.attributes.items()}

    def identity(self) -> int:
        return int(self.node.mem_id)

    def dom_path(self) -> str:
        parts: list[str] = []
        current: LexborNode | None = self.node
        while current is not None:
            tag = str(current.tag or "").lower()
            if not tag or tag.startswith("-"):
                break
            parent = current.parent
            index = 1
            if parent is not None:
                for sibling in parent.iter():
                    if sibling is current:
                        break
                    if (
                        sibling.parent is parent
                        and str(sibling.tag or "").lower() == tag
                    ):
                        index += 1
            parts.append(f"{tag}[{index}]")
            current = parent
        return "/" + "/".join(reversed(parts))

    def json(self) -> object:
        text = self.text()
        try:
            return json.loads(text) if text.strip() else None
        except json.JSONDecodeError:
            return None

    def ancestors(self) -> tuple[HtmlNode, ...]:
        nodes: list[HtmlNode] = []
        current = self.node.parent
        while current is not None:
            nodes.append(HtmlNode(self.artifact_id, current))
            current = current.parent
        return tuple(nodes)

    def siblings(self) -> tuple[HtmlNode, ...]:
        parent = self.node.parent
        if parent is None:
            return ()
        return tuple(
            HtmlNode(self.artifact_id, node)
            for node in parent.iter()
            if node.parent is parent and node is not self.node
        )

    def following_siblings(self) -> tuple[HtmlNode, ...]:
        nodes: list[HtmlNode] = []
        current = self.node.next
        while current is not None:
            nodes.append(HtmlNode(self.artifact_id, current))
            current = current.next
        return tuple(nodes)

    def html(self) -> str:
        return str(self.node.html or "")

    def stable_locator(self) -> str:
        tag = str(self.node.tag or "*")
        node_id = self.attribute("id")
        if node_id:
            return f"{tag}#{node_id}"
        classes = " ".join((self.attribute("class") or "").split()[:3])
        return f"{tag}.{classes}" if classes else tag

    def is_hidden(self) -> bool:
        if self.attribute("hidden") is not None:
            return True
        aria_hidden = (self.attribute("aria-hidden") or "").strip().lower()
        if aria_hidden == "true":
            return True
        style = (self.attribute("style") or "").replace(" ", "").lower()
        return "display:none" in style or "visibility:hidden" in style


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
        pieces: list[str] = []
        for node in root.traverse(include_text=True):
            if not node.is_text_node:
                continue
            parent = node.parent
            hidden = False
            while parent is not None:
                if str(parent.tag or "").lower() in {"script", "style", "noscript"}:
                    hidden = True
                    break
                parent = parent.parent
            if not hidden:
                text = str(node.text() or "").strip()
                if text:
                    pieces.append(text)
        return " ".join(" ".join(pieces).split())

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
    lowered_html: str
    document: HtmlDocument
    visible_text: str
    normalized_text: str
    title_text: str
    h1_present: bool

    @classmethod
    def from_html(cls, html: str) -> HtmlAnalysis:
        text = str(html or "")
        document = HtmlDocument("html", text)
        visible_text = document.visible_text()
        title = document.css_first("title")
        return cls(
            html=text,
            lowered_html=text.lower(),
            document=document,
            visible_text=visible_text,
            normalized_text=" ".join(visible_text.split()),
            title_text=" ".join((title.text() if title else "").split()),
            h1_present=document.css_first("h1") is not None,
        )

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
