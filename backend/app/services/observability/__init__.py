"""Self-healing observability layer: per-run tracing and read-only auditing.

This package owns the RunTrace collector (per-run causal chain across acquire ->
extract -> normalize -> persist) and, in later slices, the from-scratch run
auditor. Everything here is observe-only: it must never mutate extraction output,
verdicts, selector memory, or domain contracts.
"""

from __future__ import annotations
