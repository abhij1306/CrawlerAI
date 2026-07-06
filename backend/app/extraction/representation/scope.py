from __future__ import annotations

from dataclasses import dataclass

from app.core.config.evaluation import (
    EXTRACTION_V3_CHUNK_TARGET_TOKENS,
    EXTRACTION_V3_FLAT_MAP_CORE_ANCHORS,
    EXTRACTION_V3_MAX_INPUT_TOKENS,
    EXTRACTION_V3_SCOPED_MIN_TOKENS,
)
from app.extraction.documents import HtmlDocument
from app.extraction.representation.flat_map import (
    FlatMap,
    build_flat_map,
    chunk_flat_map,
    flat_map_token_count,
)


@dataclass(frozen=True, slots=True)
class ScopedFlatMap:
    flat_map: FlatMap
    token_count: int
    scope_path: str | None
    fallback_reason: str | None
    chunks: tuple[FlatMap, ...] = ()
    vision_recommended: bool = False


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


def _cap(
    flat_map: FlatMap, *, scope_path: str | None, fallback_reason: str | None
) -> ScopedFlatMap:
    token_count = flat_map_token_count(flat_map)
    if token_count <= EXTRACTION_V3_MAX_INPUT_TOKENS:
        return ScopedFlatMap(
            flat_map=flat_map,
            token_count=token_count,
            scope_path=scope_path,
            fallback_reason=fallback_reason,
        )
    chunks = chunk_flat_map(flat_map, target_tokens=EXTRACTION_V3_CHUNK_TARGET_TOKENS)
    capped = chunks[0] if chunks else flat_map
    reason = fallback_reason or "full_flat_map_above_token_cap"
    if fallback_reason:
        reason = f"{fallback_reason};full_flat_map_above_token_cap"
    return ScopedFlatMap(
        flat_map=capped,
        token_count=flat_map_token_count(capped),
        scope_path=scope_path,
        fallback_reason=reason,
        chunks=chunks,
        vision_recommended=True,
    )


def _best_product_scope_path(document: HtmlDocument) -> str | None:
    candidates = [
        node
        for node in document.nodes()
        if node.tag() in {"main", "article", "section", "div"}
        and not node.is_hidden()
    ]
    scored: list[tuple[int, int, str]] = []
    for node in candidates:
        text = " ".join(node.text().split())
        lowered = text.casefold()
        score = sum(1 for anchor in EXTRACTION_V3_FLAT_MAP_CORE_ANCHORS if anchor in lowered)
        if node.tag() in {"main", "article"}:
            score += 2
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
