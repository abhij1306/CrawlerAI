"""Observability layer: self-contained per-URL diagnose + deterministic run report.

This package builds the per-URL ``diagnose.json`` (``diagnose.py``) and folds
those artifacts into a single run-level ``report.json`` (``run_report.py``).
Everything here is observe-only: it must never mutate extraction output,
verdicts, selector memory, or domain contracts.
"""

from __future__ import annotations
