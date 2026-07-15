"""Run an extractor over a surface's fixtures and compare against a baseline.

``run_extractor`` drives an extractor callable across a surface's loaded
corpus and returns the scorer's report as a plain dict (suitable for JSON
serialization into ``backend/eval/reports``). ``compare`` decides pass/fail for
a candidate report against a baseline report.

A candidate passes for a surface when, within a small config-sourced delta
tolerance, it is:

* ``>=`` baseline on ``field_precision``,
* ``>=`` baseline on ``field_recall``,
* ``>=`` baseline on ``boundary_correctness``, and
* ``<=`` baseline on ``hallucination_count`` (never emits more ungrounded
  values than the baseline did).

Everything here is deterministic and offline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config.evaluation import (
    EVAL_HARNESS_MIN_RATE_DELTA,
)
from eval.corpus import FixtureCase, Record, load_surface_corpus
from eval.score import score_surface

# An extractor takes a fixture's raw HTML and returns the records it produced.
ExtractorCallable = Callable[[str], list[Record]]


def run_extractor(
    extractor_callable: ExtractorCallable,
    surface: str,
    *,
    root: Path | None = None,
    cases: list[FixtureCase] | None = None,
) -> dict:
    """Run ``extractor_callable`` over ``surface`` fixtures and emit a report.

    Args:
        extractor_callable: Callable invoked once per fixture with the fixture
            HTML; must return the list of records it extracted.
        surface: Surface key to load and score.
        root: Optional corpus root override forwarded to the loader.
        cases: Optional pre-loaded fixtures (skips disk loading; used by tests
            with inline fixtures).

    Returns:
        The scorer's report as a dict.
    """
    corpus = cases if cases is not None else load_surface_corpus(surface, root=root)
    produced_by_fixture = [extractor_callable(case.html) for case in corpus]
    report = score_surface(surface, corpus, produced_by_fixture)
    return report.to_dict()


@dataclass
class CompareResult:
    """Outcome of comparing a candidate report against a baseline for a surface."""

    surface: str
    passed: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"surface": self.surface, "passed": self.passed, "reasons": self.reasons}


def compare(
    candidate_report: dict,
    baseline_report: dict,
    *,
    rate_delta: float = EVAL_HARNESS_MIN_RATE_DELTA,
) -> CompareResult:
    """Return pass/fail for a candidate report against a baseline report.

    A rate metric may drop by at most ``rate_delta`` (absorbing float noise)
    before it counts as a regression. Hallucination count must not increase.

    Args:
        candidate_report: Report dict from :func:`run_extractor` for the
            candidate extractor.
        baseline_report: Report dict for the current baseline.
        rate_delta: Allowed downward slack on rate metrics; defaults to the
            config-sourced :data:`EVAL_HARNESS_MIN_RATE_DELTA`.

    Returns:
        A :class:`CompareResult` with ``passed`` and human-readable reasons for
        any regression.
    """
    surface = candidate_report.get("surface", baseline_report.get("surface", ""))
    reasons: list[str] = []

    for metric in ("field_precision", "field_recall", "boundary_correctness"):
        candidate_value = float(candidate_report[metric])
        baseline_value = float(baseline_report[metric])
        if candidate_value < baseline_value - rate_delta:
            reasons.append(
                f"{metric} regressed: candidate={candidate_value:.6f} < "
                f"baseline={baseline_value:.6f} (tolerance={rate_delta:g})"
            )

    candidate_hallucinations = int(candidate_report["hallucination_count"])
    baseline_hallucinations = int(baseline_report["hallucination_count"])
    if candidate_hallucinations > baseline_hallucinations:
        reasons.append(
            f"hallucination_count regressed: candidate={candidate_hallucinations} > "
            f"baseline={baseline_hallucinations}"
        )

    return CompareResult(surface=surface, passed=not reasons, reasons=reasons)
