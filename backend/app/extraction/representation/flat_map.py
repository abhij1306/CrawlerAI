from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
from typing import Any
import unicodedata
from typing import Literal

from app.core.config.evaluation import (
    EXTRACTION_V3_CHUNK_TARGET_TOKENS,
    EXTRACTION_V3_FLAT_MAP_CORE_ANCHORS,
    EXTRACTION_V3_FLAT_MAP_EXCLUDED_TAGS,
    EXTRACTION_V3_GROUNDING_CURRENCY_SYMBOLS,
    EXTRACTION_V3_MAX_INPUT_TOKENS,
    EXTRACTION_V3_SCOPED_MIN_TOKENS,
)
from app.extraction.documents import HtmlDocument


@dataclass(frozen=True, slots=True)
class FlatMapEntry:
    path: str
    text: str


FlatMap = OrderedDict[str, str]


@dataclass(frozen=True, slots=True)
class GroundingResult:
    grounded: bool
    match_type: Literal["exact", "normalized", "none"]
    source_path: str | None = None


@dataclass(frozen=True, slots=True)
class ScopedFlatMap:
    flat_map: FlatMap
    token_count: int
    scope_path: str | None
    fallback_reason: str | None
    chunks: tuple[FlatMap, ...] = ()
    vision_recommended: bool = False


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


def build_scoped_flat_map(document: HtmlDocument) -> ScopedFlatMap:
    scope_path = _best_product_scope_path(document)
    scoped = build_flat_map(document, root_path=scope_path)
    scoped_tokens = flat_map_token_count(scoped)
    if scoped_tokens >= EXTRACTION_V3_SCOPED_MIN_TOKENS and _has_anchor(scoped):
        return _cap(scoped, scope_path=scope_path, fallback_reason=None)
    full = build_flat_map(document)
    reason = (
        "scoped_region_missing_core_anchors"
        if scoped_tokens >= EXTRACTION_V3_SCOPED_MIN_TOKENS
        else "scoped_region_below_min_tokens"
    )
    return _cap(full, scope_path=None, fallback_reason=reason)


def ground(
    value: object,
    flat_map: FlatMap,
    sources: tuple[str, ...] | list[str] | None = None,
) -> GroundingResult:
    text = str(value or "").strip()
    if not text:
        return GroundingResult(False, "none", None)
    paths = tuple(sources or flat_map.keys())
    exact = _find_exact(text, flat_map, paths)
    if exact is not None:
        return GroundingResult(True, "exact", exact)
    normalized_values = _normalize_forms(text)
    for path in paths:
        source_text = flat_map.get(path)
        if source_text is None:
            continue
        source_forms = _normalize_forms(source_text)
        if any(
            normalized and any(normalized in source for source in source_forms)
            for normalized in normalized_values
        ):
            return GroundingResult(True, "normalized", path)
    return GroundingResult(False, "none", None)


def _cap(
    flat_map: FlatMap, *, scope_path: str | None, fallback_reason: str | None
) -> ScopedFlatMap:
    token_count = flat_map_token_count(flat_map)
    if token_count <= EXTRACTION_V3_MAX_INPUT_TOKENS:
        return ScopedFlatMap(flat_map, token_count, scope_path, fallback_reason)
    chunks = chunk_flat_map(flat_map, target_tokens=EXTRACTION_V3_CHUNK_TARGET_TOKENS)
    capped = chunks[0] if chunks else flat_map
    reason = fallback_reason or "full_flat_map_above_token_cap"
    if fallback_reason:
        reason = f"{fallback_reason};full_flat_map_above_token_cap"
    return ScopedFlatMap(
        capped,
        flat_map_token_count(capped),
        scope_path,
        reason,
        chunks,
        True,
    )


def _best_product_scope_path(document: HtmlDocument) -> str | None:
    candidates = [
        node
        for node in document.nodes()
        if node.tag() in {"main", "article", "section", "div"} and not node.is_hidden()
    ]
    scored: list[tuple[int, int, str]] = []
    for node in candidates:
        text = " ".join(node.text().split())
        score = sum(
            1
            for anchor in EXTRACTION_V3_FLAT_MAP_CORE_ANCHORS
            if anchor in text.casefold()
        ) + (2 if node.tag() in {"main", "article"} else 0)
        if score:
            scored.append((score, min(len(text), 50000), node.dom_path()))
    if not scored:
        main = document.css_first("main")
        return main.dom_path() if main is not None else None
    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    return scored[0][2]


def _has_anchor(flat_map: FlatMap) -> bool:
    text = " ".join(flat_map.values()).casefold()
    return any(anchor in text for anchor in EXTRACTION_V3_FLAT_MAP_CORE_ANCHORS)


def _find_exact(text: str, flat_map: FlatMap, paths: tuple[str, ...]) -> str | None:
    needle = text.casefold()
    return next(
        (
            path
            for path in paths
            if (source := flat_map.get(path)) is not None
            and needle in source.casefold()
        ),
        None,
    )


def _normalize_forms(value: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    for symbol, replacement in EXTRACTION_V3_GROUNDING_CURRENCY_SYMBOLS.items():
        text = text.replace(symbol, f" {replacement} ")
    text = re.sub(r"(?<=\d)[,\s](?=\d{3}\b)", "", text)
    text = re.sub(r"(?<=\d)\.(?=\d{2}\b)", "", text)
    base = re.sub(r"[^a-z0-9]+", "", text)
    forms = [base] if base else []
    for token in re.findall(r"\d+(?:[.,]\d+)?", str(value or "")):
        clean = token.replace(",", "")
        if "." not in clean:
            forms.append(clean)
            continue
        whole, cents = clean.split(".", 1)
        if not cents.strip("0"):
            forms.append(whole)
        forms.append(f"{whole}{cents}")
    return tuple(dict.fromkeys(form for form in forms if form))


def _root_node(document: HtmlDocument, root_path: str | None) -> Any | None:
    if root_path:
        for node in document.nodes():
            if node.dom_path() == root_path:
                return node.node
    body = document.css_first("body")
    if body is not None:
        return body.node
    html = document.css_first("html")
    return html.node if html is not None else None


def _excluded(node: Any) -> bool:
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


def _direct_text(node: Any) -> str:
    pieces: list[str] = []
    child = node.child
    while child is not None:
        if child.is_text_node:
            text = str(child.text() or "").strip()
            if text:
                pieces.append(text)
        child = child.next
    return " ".join(" ".join(pieces).split())


def _absolute_path(node: Any) -> str:
    parts: list[str] = []
    current: Any | None = node
    while current is not None:
        tag = str(current.tag or "").lower()
        if not tag or tag.startswith("-"):
            break
        if tag == "#document":
            current = current.parent
            continue
        parent = current.parent
        index = _same_tag_sibling_index(current, parent, tag)
        parts.append(f"{tag}[{index}]")
        current = parent
    return "/" + "/".join(reversed(parts))


def _same_tag_sibling_index(current: Any, parent: Any | None, tag: str) -> int:
    if parent is None or str(parent.tag or "").lower() == "#document":
        return 1
    index = 1
    sibling = parent.child
    while sibling is not None and not _same_node(sibling, current):
        if _same_node(sibling.parent, parent) and str(sibling.tag or "").lower() == tag:
            index += 1
        sibling = sibling.next
    return index


def _rough_token_count(value: str) -> int:
    compact = " ".join(str(value or "").split())
    if not compact:
        return 0
    return max(1, (len(compact) + 3) // 4)


def _same_node(left: Any | None, right: Any | None) -> bool:
    if left is None or right is None:
        return left is right
    return int(left.mem_id) == int(right.mem_id)
