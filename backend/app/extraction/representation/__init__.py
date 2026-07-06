"""Flat page representation and grounding primitives for extraction V3."""

from app.extraction.representation.flat_map import FlatMap, FlatMapEntry, build_flat_map
from app.extraction.representation.grounding import GroundingResult, ground
from app.extraction.representation.scope import ScopedFlatMap, build_scoped_flat_map

__all__ = [
    "FlatMap",
    "FlatMapEntry",
    "GroundingResult",
    "ScopedFlatMap",
    "build_flat_map",
    "build_scoped_flat_map",
    "ground",
]
