from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable

from app.extraction.documents import HtmlDocument


def _document(value: str | HtmlDocument, artifact_id: str = "html") -> HtmlDocument:
    if isinstance(value, HtmlDocument):
        return HtmlDocument(value.artifact_id, value.html())
    return HtmlDocument(artifact_id, str(value or ""))


def html_to_text(
    value: str | HtmlDocument, *, preserve_block_breaks: bool = False
) -> str:
    document = _document(value)
    for node in document.safe_css("script, style"):
        node.node.decompose()
    separator = "\n" if preserve_block_breaks else " "
    text = document._parser.text(separator=separator, strip=True)
    rows = [" ".join(line.split()).strip() for line in text.splitlines()]
    cleaned = [row for row in rows if row]
    return ("\n" if preserve_block_breaks else " ").join(cleaned).strip()


def prune_html_tree(
    document: HtmlDocument,
    *,
    drop_tags: tuple[str, ...] | set[str],
    allowed_attrs: tuple[str, ...] | set[str] | None = None,
    attr_filter=None,
    preserve_tag=None,
) -> HtmlDocument:
    allowed = set(allowed_attrs or ())
    for node in document.safe_css(", ".join(sorted(set(drop_tags)))):
        if preserve_tag and preserve_tag(node):
            continue
        node.node.decompose()
    for node in document.safe_css("*"):
        attrs = dict(node.node.attributes)
        for key, value in attrs.items():
            disallowed_name = allowed_attrs is not None and key not in allowed
            rejected_value = not disallowed_name and bool(
                attr_filter and not attr_filter(key, value)
            )
            if disallowed_name or rejected_value:
                del node.node.attributes[key]
    return document


def embedded_state_payloads(
    document,
    *,
    selector: str,
    global_keys: tuple[str, ...],
    json_call_keys: tuple[str, ...] = (),
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
        yield from _json_call_state_payloads(text, json_call_keys, index)


def _assigned_state_payloads(
    text: str, global_keys: tuple[str, ...], script_index: int
) -> Iterable[tuple[str, object]]:
    decoder = json.JSONDecoder()
    seen_offsets: set[int] = set()
    for state_key in global_keys:
        pattern = re.compile(
            rf"(?<![\w$])(?:window\s*\.\s*)?{re.escape(state_key)}\s*=\s*"
        )
        for match in pattern.finditer(text):
            payload = _decode_assigned_json(text, match.end(), decoder)
            if payload is None:
                continue
            seen_offsets.add(match.end())
            yield f"/embedded/{state_key}/{script_index}", payload
            break
    dotted = re.compile(
        r"(?<![\w$])(?:window\s*\.\s*)?"
        r"(?P<key>[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*){2,})"
        r"\s*=\s*"
    )
    for match in dotted.finditer(text):
        if match.end() in seen_offsets:
            continue
        payload = _decode_assigned_json(text, match.end(), decoder)
        if payload is None:
            continue
        state_key = ".".join(part.strip() for part in match.group("key").split("."))
        yield f"/embedded/{state_key}/{script_index}", payload


def _json_call_state_payloads(
    text: str, json_call_keys: tuple[str, ...], script_index: int
) -> Iterable[tuple[str, object]]:
    decoder = json.JSONDecoder()
    for state_key in json_call_keys:
        parts = tuple(part for part in state_key.split(".") if part)
        if len(parts) != 2:
            continue
        carrier, method = (re.escape(part) for part in parts)
        pattern = re.compile(
            rf"(?<![\w$]){carrier}\s*\.\s*{method}\s*\(",
        )
        for match in pattern.finditer(text):
            payload = _decode_call_json(text, match.end(), decoder)
            if payload is None:
                continue
            yield f"/embedded/{state_key}/{script_index}", payload


def _decode_assigned_json(
    text: str, offset: int, decoder: json.JSONDecoder
) -> object | None:
    remainder = text[offset:].lstrip()
    if not remainder.startswith(("{", "[")):
        return None
    try:
        value, _ = decoder.raw_decode(remainder)
    except (TypeError, ValueError):
        return None
    return value


def _decode_call_json(
    text: str, offset: int, decoder: json.JSONDecoder
) -> object | None:
    remainder = text[offset:].lstrip()
    if not remainder.startswith(("{", "[")):
        return None
    try:
        value, end = decoder.raw_decode(remainder)
    except (TypeError, ValueError):
        return None
    tail = remainder[end:].lstrip()
    if not tail.startswith(")"):
        return None
    return value


def bounded_json_objects(
    value: object, *, max_depth: int, max_nodes: int, max_list_items: int
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
