"""Selector-free flat path->text representation used for grounding + learn-once."""

from app.extraction.representation.flat_map import (
    FlatMap,
    FlatMapEntry,
    GroundingResult,
    ScopedFlatMap,
    build_flat_map,
    build_scoped_flat_map,
    chunk_flat_map,
    flat_map_token_count,
    ground,
)

__all__ = [
    "FlatMap",
    "FlatMapEntry",
    "GroundingResult",
    "ScopedFlatMap",
    "build_flat_map",
    "build_scoped_flat_map",
    "chunk_flat_map",
    "flat_map_token_count",
    "ground",
]
