from __future__ import annotations

from .collection import add_candidate, candidate_fingerprint
from .finalization import finalize_candidate_value
from .scoring import record_score
from .structured_payloads import collect_structured_candidates

__all__ = [
    "add_candidate",
    "candidate_fingerprint",
    "collect_structured_candidates",
    "finalize_candidate_value",
    "record_score",
]
