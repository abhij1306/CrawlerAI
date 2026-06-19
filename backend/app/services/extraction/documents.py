from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode


@dataclass(frozen=True)
class HtmlNode:
    artifact_id: str
    node: LexborNode

    def css(self, selector: str) -> tuple[HtmlNode, ...]:
        return tuple(HtmlNode(self.artifact_id, node) for node in self.node.css(selector))

    def css_first(self, selector: str) -> HtmlNode | None:
        node = self.node.css_first(selector)
        return HtmlNode(self.artifact_id, node) if node is not None else None

    def text(self, *, separator: str = " ", strip: bool = True) -> str:
        return self.node.text(separator=separator, strip=strip)

    def attribute(self, name: str) -> str | None:
        value = self.node.attributes.get(name)
        return str(value) if value is not None else None

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
        self._parser = LexborHTMLParser(html)

    def css(self, selector: str) -> tuple[HtmlNode, ...]:
        return tuple(HtmlNode(self.artifact_id, node) for node in self._parser.css(selector))

    def css_first(self, selector: str) -> HtmlNode | None:
        node = self._parser.css_first(selector)
        return HtmlNode(self.artifact_id, node) if node is not None else None

    def text(self) -> str:
        return self._parser.text(separator=" ", strip=True)

    def html(self) -> str:
        return self._html


@dataclass(frozen=True)
class JsonDocument:
    artifact_id: str
    value: Any


class DocumentStore:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self._payloads = dict(payloads)
        self._html_cache: dict[str, HtmlDocument] = {}
        self._json_cache: dict[str, JsonDocument] = {}

    def html(self, artifact_id: str) -> HtmlDocument:
        if artifact_id not in self._html_cache:
            self._html_cache[artifact_id] = HtmlDocument(artifact_id, self.text(artifact_id))
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
