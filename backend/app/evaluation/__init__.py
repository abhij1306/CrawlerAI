"""Offline evaluation of the extraction cascade.

This package observes extraction; it is not part of the extraction runtime and
must never be imported by the hot path. The runtime compact representation is
owned by ``app.extraction.model_runtime``; this package only decorates it with
offline labels and runs adapters/benchmarks.
"""

from app.evaluation.schema import EvaluationCase, GroundedLabel

__all__ = ["EvaluationCase", "GroundedLabel"]
