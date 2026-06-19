from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Pattern

from selectolax.lexbor import LexborHTMLParser


@dataclass(frozen=True, slots=True)
class ScriptTextNode:
    script_id: str
    script_type: str
    text: str


def iter_script_text_nodes(html: str) -> list[ScriptTextNode]:
    parser = LexborHTMLParser(str(html or ""))
    nodes: list[ScriptTextNode] = []
    for node in parser.css("script"):
        attributes = getattr(node, "attributes", {}) or {}
        text = str(node.text(strip=True) or "")
        if not text:
            continue
        nodes.append(
            ScriptTextNode(
                script_id=str(attributes.get("id") or "").strip(),
                script_type=str(attributes.get("type") or "").strip(),
                text=text,
            )
        )
    # VTEX and similar frameworks embed state inside
    # <template data-varname="__STATE__"><script>{...}</script></template>.
    # HTML spec treats <template> content as an inert document fragment,
    # so DOM parsers (selectolax/lexbor) cannot traverse inside it.
    # Extract via regex on the raw HTML string.
    nodes.extend(_extract_template_script_nodes(html))
    return nodes


_TEMPLATE_SCRIPT_RE = re.compile(
    r"<template\b[^>]*?\bdata-(?:varname|state|id)=[\"']([^\"']+)[\"'][^>]*>"
    r"\s*<script[^>]*>(.*?)</script>\s*</template>",
    re.DOTALL | re.IGNORECASE,
)


def _extract_template_script_nodes(html: str) -> list[ScriptTextNode]:
    """Extract script content from <template data-varname="..."> elements."""
    nodes: list[ScriptTextNode] = []
    for match in _TEMPLATE_SCRIPT_RE.finditer(html):
        varname = match.group(1).strip()
        text = match.group(2).strip()
        if not varname or not text:
            continue
        nodes.append(
            ScriptTextNode(
                script_id=varname,
                script_type="",
                text=text,
            )
        )
    return nodes


async def iter_script_text_nodes_async(html: str) -> list[ScriptTextNode]:
    return await asyncio.to_thread(iter_script_text_nodes, html)


def extract_script_text_by_id(html: str, script_id: str) -> str | None:
    normalized_id = str(script_id or "").strip().lower()
    if not normalized_id:
        return None
    for node in iter_script_text_nodes(html):
        if node.script_id.lower() != normalized_id:
            continue
        cleaned = node.text.strip()
        return cleaned or None
    return None


def find_script_regex_matches(
    html: str,
    pattern: str | Pattern[str],
) -> list[str]:
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
    matches: list[str] = []
    for node in iter_script_text_nodes(html):
        for match in compiled.finditer(node.text):
            if match.lastindex:
                matches.append(match.group(1))
            else:
                matches.append(match.group(0))
    return matches


def find_first_script_text_matching(
    html: str,
    pattern: str | Pattern[str],
) -> str | None:
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
    for node in iter_script_text_nodes(html):
        if compiled.search(node.text):
            return node.text
    return None
