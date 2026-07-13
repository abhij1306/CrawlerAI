"""Flat page representation and grounding primitives for extraction V3."""

from app.extraction.representation.flat_map import (
    FlatMap,
    FlatMapEntry,
    GroundingResult,
    ScopedFlatMap,
    build_flat_map,
    build_scoped_flat_map,
    ground,
)

__all__ = [
    "FlatMap",
    "FlatMapEntry",
    "GroundingResult",
    "ScopedFlatMap",
    "build_flat_map",
    "build_scoped_flat_map",
    "ground",
]
