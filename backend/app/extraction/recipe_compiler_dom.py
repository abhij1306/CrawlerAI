"""DOM-specific grounding for executable extraction recipes."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from app.core.config.extraction_rules import DETAIL_IMAGE_SRCSET_ATTRS
from app.core.config.locale_format_rules import locale_hint_from_page_url, parse_money
from app.core.shared.field_coerce_price import extract_currency_code
from app.core.shared.url_utils import largest_srcset_url
from app.extraction.contracts import Evidence, ExtractionRequest
from app.extraction.documents import HtmlDocument, HtmlNode
from app.extraction.recipe_compiler_grounding import _comparable_value

GroundedDom = tuple[str, str | None, str, str]


def _ground_detail_dom(request: ExtractionRequest, row: Evidence, field: str) -> GroundedDom | None:
    loaded = _load_document(request, row.artifact_id)
    if loaded is None:
        return None
    artifact_id, document = loaded
    target = _comparable_value(request, field, row.value)
    result = _located_binding(request, _located_node(document, row), field, target, artifact_id)
    if result is not None:
        return result
    for finder in (
        _semantic_attribute_binding,
        _named_attribute_binding,
        _any_attribute_binding,
        _text_binding,
    ):
        result = finder(request, document, field, target, artifact_id)
        if result is not None:
            return result
    return None


def _load_document(request: ExtractionRequest, artifact_id: str) -> tuple[str, HtmlDocument] | None:
    artifacts = request.capture.artifacts
    store = request.artifact_reader.document_store
    try:
        if artifact_id not in {item.artifact_id for item in artifacts}:
            raise KeyError(artifact_id)
        return artifact_id, store.html(artifact_id)
    except (KeyError, ValueError):
        html_types = {"rendered_html", "http_html"}
        fallback = next(
            (item for item in artifacts if item.artifact_type in html_types), None
        )
        if fallback is None:
            return None
        return fallback.artifact_id, store.html(fallback.artifact_id)


def _located_node(document: HtmlDocument, row: Evidence) -> HtmlNode | None:
    if row.locator.kind == "css_selector":
        return document.css_first(row.locator.value)
    return next(
        (node for node in document.css("*") if node.dom_path() == row.locator.value), None
    )


def _binding_result(node, attribute, artifact_id, transform) -> GroundedDom:
    return _dom_path_to_css(node.dom_path()), attribute, artifact_id, transform


def _located_binding(request, node, field, target, artifact_id) -> GroundedDom | None:
    if node is None:
        return None
    text = node.content_text()
    if field in {"price", "original_price"}:
        parsed = parse_money(text, locale_hint=locale_hint_from_page_url(request.capture.final_url))
        if parsed is not None and _comparable_value(request, field, parsed) == target:
            return _binding_result(node, None, artifact_id, "dom_price")
    if field == "currency":
        currency = extract_currency_code(text)
        if currency and _comparable_value(request, field, currency) == target:
            return _binding_result(node, None, artifact_id, "dom_currency")
    if _comparable_value(request, field, text) == target:
        return _binding_result(node, None, artifact_id, "canonical")
    return None


def _semantic_attribute_binding(request, document, field, target, artifact_id) -> GroundedDom | None:
    for item in document.css("*"):
        for attribute, raw_value in item.attributes().items():
            transform = _semantic_attribute_transform(request, field, attribute, raw_value, target)
            if transform:
                return _binding_result(item, attribute, artifact_id, transform)
    return None


def _semantic_attribute_transform(request, field, attribute, raw_value, target):
    if field == "color" and attribute in {"href", "value", "data-url"}:
        query = parse_qs(urlsplit(urljoin(request.capture.final_url, raw_value)).query)
        name = next(
            (key for key, values in query.items() if values and _comparable_value(request, field, values[0]) == target),
            None,
        )
        return f"query_param:{name}" if name else None
    if field != "availability" or attribute != "data-json":
        return None
    normalized = _attribute_availability(raw_value)
    if _comparable_value(request, field, normalized) == target:
        return "attribute_json_availability"
    return None


def _attribute_availability(raw_value: str) -> str | None:
    try:
        state = json.loads(raw_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    selectable = state.get("selectable") if isinstance(state, dict) else None
    if selectable in {False, 0, "0", "false", "False"}:
        return "out_of_stock"
    return "in_stock" if selectable in {True, 1, "1", "true", "True"} else None


def _named_attribute_binding(request, document, field, target, artifact_id) -> GroundedDom | None:
    attributes = ("content", "title", "alt", "href", "src", "data-brand")
    for attribute in attributes:
        for item in document.css(f"[{attribute}]"):
            value = item.attribute(attribute) or ""
            if _comparable_value(request, field, value) == target:
                return _binding_result(item, attribute, artifact_id, "canonical")
            transform = _derived_text_transform(value, target)
            if transform:
                return _binding_result(item, attribute, artifact_id, transform)
    return None


def _any_attribute_binding(request, document, field, target, artifact_id) -> GroundedDom | None:
    for item in document.css("*"):
        for attribute, value in item.attributes().items():
            transform = "canonical"
            if attribute in DETAIL_IMAGE_SRCSET_ATTRS:
                value, transform = largest_srcset_url(value), "largest_srcset"
            if _comparable_value(request, field, value) == target:
                return _binding_result(item, attribute, artifact_id, transform)
    return None


def _text_binding(request, document, field, target, artifact_id) -> GroundedDom | None:
    nodes = tuple(document.css("body *"))
    candidates = (
        node
        for node in nodes
        if _comparable_value(request, field, node.content_text()) == target
    )
    if node := max(candidates, key=lambda item: item.dom_path().count("/"), default=None):
        return _binding_result(node, None, artifact_id, "canonical")
    for node in nodes:
        transform = _derived_text_transform(node.content_text(), target)
        if transform:
            return _binding_result(node, None, artifact_id, transform)
    return None


def _derived_text_transform(value: str, target: str) -> str | None:
    text = " ".join(value.split())
    if ":" in text and text.partition(":")[2].strip().casefold() == target:
        return "after_colon"
    registered = re.match(r"^(.+?®)(?:\s|$)", text)
    if registered and registered.group(1).casefold() == target:
        return "registered_prefix"
    first = text.split(" ", 1)[0].strip("'\"") if text else ""
    if first.casefold() == target:
        return "first_token"
    stripped = re.sub(r"^[^A-Za-z0-9]+", "", text).strip()
    if stripped.casefold() == target:
        return "strip_leading_symbols"
    start = text.casefold().find(target)
    if target and start >= 0:
        return f"substring:{start}:{len(target)}"
    last = text.rsplit(" ", 1)[-1].strip("'\"") if text else ""
    if last.casefold() == target:
        return "last_token"
    target_words = target.split()
    source_words = text.casefold().split()
    if target_words and source_words[: len(target_words)] == target_words:
        return f"prefix_words:{len(target_words)}"
    if text.rsplit("/", 1)[-1].casefold() == target:
        return "path_leaf_title"
    return None


def _dom_pattern(paths: list[str]) -> str:
    parts = [
        [part for part in path.strip("/").split("/") if not part.startswith("#")]
        for path in paths
    ]
    if len({len(path) for path in parts}) != 1:
        return ""
    result: list[str] = []
    for values in zip(*parts, strict=True):
        tags = [value.split("[", 1)[0] for value in values]
        if len(set(tags)) != 1:
            return ""
        indexes = [value.removeprefix(tags[0]).strip("[]") for value in values]
        result.append(
            tags[0] if len(set(indexes)) > 1 else f"{tags[0]}:nth-of-type({indexes[0]})"
        )
    return " > ".join(result)


def _dom_path_to_css(path: str) -> str:
    return _dom_pattern([path])


def _relative_css(root: str, absolute: str) -> str:
    return absolute.removeprefix(root).removeprefix(" > ") or "."
