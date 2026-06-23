from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, PageElement, Tag

from app.core.records.field_policy import HTML_SECTION_FIELDS, normalize_requested_field

_HTML_TEXT_BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "details",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "section",
    "summary",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}


def html_to_text(value: str, *, preserve_block_breaks: bool = False) -> str:
    soup = BeautifulSoup(str(value or ""), "html.parser")
    for node in soup.find_all(["script", "style"]):
        node.decompose()
    for node in soup.find_all(_HTML_TEXT_BLOCK_TAGS):
        if not isinstance(node, Tag):
            continue
        if node.name == "br":
            node.replace_with(NavigableString("\n"))
            continue
        if node.contents:
            node.insert_before(NavigableString("\n"))
            node.append(NavigableString("\n"))
    rows = [
        " ".join(str(line or "").split()).strip()
        for line in soup.get_text("\n").splitlines()
    ]
    cleaned_rows = [row for row in rows if row]
    if preserve_block_breaks:
        return "\n".join(cleaned_rows).strip()
    return " ".join(cleaned_rows).strip()


def prune_html_tree(
    soup: BeautifulSoup,
    *,
    drop_tags: tuple[str, ...] | set[str],
    allowed_attrs: tuple[str, ...] | set[str] | None = None,
    attr_filter=None,
    preserve_tag=None,
) -> BeautifulSoup:
    allowed_attr_set = set(allowed_attrs or ())
    drop_tag_set = {str(tag).lower() for tag in drop_tags}
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()
    for node in soup.find_all(True):
        if not isinstance(node, Tag):
            continue
        tag_name = str(node.name or "").lower()
        if tag_name in drop_tag_set and not (preserve_tag and preserve_tag(node)):
            node.decompose()
            continue
        attrs = node.attrs
        if not isinstance(attrs, dict):
            node.attrs = {}
            continue
        node.attrs = {
            key: value
            for key, value in attrs.items()
            if (key in allowed_attr_set if allowed_attrs is not None else True)
            and (attr_filter(key, value) if attr_filter else True)
        }
    return soup


def embedded_state_payloads(
    document,
    *,
    selector: str,
    global_keys: tuple[str, ...],
    max_scripts: int,
    max_script_chars: int,
    exclude_node: Callable[[object], bool] | None = None,
) -> Iterable[tuple[str, object]]:
    seen_nodes: set[int] = set()
    for index, node in enumerate(document.safe_css(selector)[:max_scripts]):
        seen_nodes.add(node.identity())
        if exclude_node is not None and exclude_node(node):
            continue
        text = str(node.text(separator="", strip=True) or "")[:max_script_chars]
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            continue
        state_key = str(node.attribute("id") or "application_json").strip()
        yield f"/embedded/{state_key}/{index}", data
    remaining = max(0, max_scripts - len(seen_nodes))
    for index, node in enumerate(document.safe_css("script")[:max_scripts]):
        if remaining <= 0 or node.identity() in seen_nodes:
            continue
        remaining -= 1
        if exclude_node is not None and exclude_node(node):
            continue
        text = str(node.text(separator="", strip=True) or "")[:max_script_chars]
        yield from _assigned_state_payloads(text, global_keys, index)


def _assigned_state_payloads(
    text: str, global_keys: tuple[str, ...], script_index: int
) -> Iterable[tuple[str, object]]:
    decoder = json.JSONDecoder()
    for state_key in global_keys:
        pattern = re.compile(
            rf"(?<![\w$])(?:window\s*\.\s*)?{re.escape(state_key)}\s*=\s*"
        )
        for match in pattern.finditer(text):
            try:
                value, _ = decoder.raw_decode(text[match.end() :])
            except (TypeError, ValueError):
                continue
            yield f"/embedded/{state_key}/{script_index}", value
            break


def bounded_json_objects(
    value: object,
    *,
    max_depth: int,
    max_nodes: int,
    max_list_items: int,
) -> Iterable[tuple[str, object]]:
    stack: list[tuple[str, object, int]] = [("", value, 0)]
    visited = 0
    while stack and visited < max_nodes:
        path, current, depth = stack.pop()
        visited += 1
        if isinstance(current, dict):
            yield path, current
            if depth >= max_depth:
                continue
            stack.extend(
                (f"{path}/{key}", child, depth + 1)
                for key, child in reversed(list(current.items()))
            )
        elif isinstance(current, list) and depth < max_depth:
            stack.extend(
                (f"{path}/{index}", child, depth + 1)
                for index, child in reversed(list(enumerate(current[:max_list_items])))
            )


def extract_job_sections(html: str) -> dict[str, str]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    mapped: dict[str, str] = {}
    for heading in soup.find_all(["h2", "h3", "strong"]):
        heading_text = " ".join(heading.get_text(" ", strip=True).split()).strip()
        if not heading_text:
            continue
        section = normalize_requested_field(heading_text)
        if section not in HTML_SECTION_FIELDS:
            continue
        collected: list[str] = []
        for sibling in _iter_page_siblings(heading.next_siblings):
            sibling_name = getattr(sibling, "name", "")
            if sibling_name in {"h1", "h2", "h3", "strong"}:
                break
            text = (
                sibling.get_text(" ", strip=True)
                if hasattr(sibling, "get_text")
                else str(sibling)
            )
            cleaned = " ".join(str(text or "").split()).strip()
            if cleaned:
                collected.append(cleaned)
        value = " ".join(collected).strip()
        if not value:
            continue
        combined_parts = (
            [mapped_value, value] if (mapped_value := mapped.get(section)) else [value]
        )
        combined = " ".join(
            piece for piece in combined_parts if str(piece or "").strip()
        )
        mapped[section] = " ".join(combined.split()).strip()
    return mapped


def _iter_page_siblings(
    siblings: Iterator[PageElement],
) -> Iterator[Tag | NavigableString]:
    for sibling in siblings:
        if isinstance(sibling, (Tag, NavigableString)):
            yield sibling
