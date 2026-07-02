"""Offline evaluation of the extraction cascade.

This package *observes* extraction; it is not part of the extraction runtime
and must never be imported by the hot path. Slice 0.1 freezes a deterministic
baseline over a completed offline run; Slice 0.2 adds the evaluation and
grounded-label schema consumed by release gating.
"""

from app.evaluation.schema import EvaluationCase, GroundedLabel

__all__ = ["EvaluationCase", "GroundedLabel"]
