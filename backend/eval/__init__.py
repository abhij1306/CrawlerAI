"""Deterministic, offline evaluation harness for extraction surfaces.

This package builds the machinery used to gate per-surface selector deletion.
It is intentionally free of any network I/O and any LLM invocation: given
fixture HTML pages and paired ground-truth labels, it scores an extractor's
produced facts against expectations and compares a candidate report against a
baseline report.

Per-surface fixtures and baselines are authored later; this package only
provides the reusable machinery (corpus loading, scoring, run/compare).
"""

from __future__ import annotations

from eval.corpus import FixtureCase, load_surface_corpus
from eval.run import CompareResult, compare, run_extractor
from eval.score import SurfaceReport, score_surface

__all__ = [
    "CompareResult",
    "FixtureCase",
    "SurfaceReport",
    "compare",
    "load_surface_corpus",
    "run_extractor",
    "score_surface",
]
