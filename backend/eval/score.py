"""Deterministic scoring of produced facts against ground-truth labels.

The scorer is pure and offline. Given a surface's fixtures (HTML + expected
records) and the records an extractor produced for each fixture, it computes:

* **Per-field precision / recall** — produced field values are matched against
  expected field values within the same record position. A produced value that
  matches an expected value is a true positive (TP); a produced value with no
  matching expected value is a false positive (FP); an expected value with no
  matching produced value is a false negative (FN). Precision = TP / (TP + FP),
  recall = TP / (TP + FN). Both aggregate (micro-averaged over all fields) and
  per-field breakdowns are reported.

* **Grounding proxy** — every emitted string value must appear as a substring
  of its source fixture HTML. A value that does not is counted as a
  hallucination. ``grounding_rate`` is the fraction of emitted values that are
  grounded.

* **Listing boundary correctness** — for each fixture the produced record count
  is compared to the labeled record count. ``boundary_correctness`` is the
  fraction of fixtures whose counts match exactly. ``exact_match_rate`` is the
  fraction of position-aligned records that equal their expected record exactly.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field

from eval.corpus import FieldValue, FixtureCase, Record


def _as_value_list(value: FieldValue) -> list[str]:
    """Coerce a field value (string or list of strings) to a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


@dataclass
class FieldMetrics:
    """Precision/recall accounting for a single field across a surface."""

    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return 1.0 if denom == 0 else self.tp / denom

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return 1.0 if denom == 0 else self.tp / denom


@dataclass
class SurfaceReport:
    """Aggregate metrics for one surface's evaluation run."""

    surface: str
    fixture_count: int
    # Micro-averaged over every field occurrence.
    field_precision: float
    field_recall: float
    # Per-field breakdown: field name -> {"precision", "recall", "tp", "fp", "fn"}.
    per_field: dict[str, dict[str, float]] = field(default_factory=dict)
    # Grounding proxy.
    emitted_value_count: int = 0
    hallucination_count: int = 0
    grounding_rate: float = 1.0
    # Listing boundary correctness.
    boundary_correctness: float = 1.0
    exact_match_rate: float = 1.0
    produced_record_count: int = 0
    expected_record_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _count_field_matches(
    produced: list[str],
    expected: list[str],
    metrics: FieldMetrics,
) -> None:
    """Update ``metrics`` with multiset TP/FP/FN for one record+field."""
    produced_counts = Counter(produced)
    expected_counts = Counter(expected)
    tp = sum((produced_counts & expected_counts).values())
    metrics.tp += tp
    metrics.fp += sum(produced_counts.values()) - tp
    metrics.fn += sum(expected_counts.values()) - tp


def score_surface(
    surface: str,
    cases: list[FixtureCase],
    produced_by_fixture: list[list[Record]],
) -> SurfaceReport:
    """Score produced records for a surface against its labeled fixtures.

    Args:
        surface: Surface key being scored.
        cases: Fixtures (HTML + expected records) for the surface.
        produced_by_fixture: Records an extractor produced, aligned by fixture
            index with ``cases`` (``produced_by_fixture[i]`` corresponds to
            ``cases[i]``).

    Returns:
        A :class:`SurfaceReport` with per-field, grounding, and boundary metrics.
    """
    if len(produced_by_fixture) != len(cases):
        raise ValueError(
            "produced_by_fixture length "
            f"({len(produced_by_fixture)}) must match cases length ({len(cases)})"
        )

    per_field: dict[str, FieldMetrics] = {}
    emitted_value_count = 0
    hallucination_count = 0
    fixtures_with_correct_boundary = 0
    total_aligned_records = 0
    exact_record_matches = 0
    produced_record_total = 0
    expected_record_total = 0

    for case, produced_records in zip(cases, produced_by_fixture, strict=True):
        expected_records = case.expected_facts
        produced_record_total += len(produced_records)
        expected_record_total += len(expected_records)

        # Listing boundary correctness (per fixture).
        if len(produced_records) == len(expected_records):
            fixtures_with_correct_boundary += 1

        # Position-aligned precision/recall + exact-match accounting.
        record_span = max(len(produced_records), len(expected_records))
        for index in range(record_span):
            produced_rec = (
                produced_records[index] if index < len(produced_records) else {}
            )
            expected_rec = (
                expected_records[index] if index < len(expected_records) else {}
            )
            total_aligned_records += 1
            if produced_rec == expected_rec:
                exact_record_matches += 1

            for field_name in set(produced_rec) | set(expected_rec):
                metrics = per_field.setdefault(field_name, FieldMetrics())
                produced_vals = (
                    _as_value_list(produced_rec[field_name])
                    if field_name in produced_rec
                    else []
                )
                expected_vals = (
                    _as_value_list(expected_rec[field_name])
                    if field_name in expected_rec
                    else []
                )
                _count_field_matches(produced_vals, expected_vals, metrics)

        # Grounding proxy: every emitted string value must be a substring of the
        # fixture HTML.
        for produced_rec in produced_records:
            for raw_value in produced_rec.values():
                for value in _as_value_list(raw_value):
                    emitted_value_count += 1
                    if value not in case.html:
                        hallucination_count += 1

    total_tp = sum(m.tp for m in per_field.values())
    total_fp = sum(m.fp for m in per_field.values())
    total_fn = sum(m.fn for m in per_field.values())
    field_precision = (
        1.0 if (total_tp + total_fp) == 0 else total_tp / (total_tp + total_fp)
    )
    field_recall = (
        1.0 if (total_tp + total_fn) == 0 else total_tp / (total_tp + total_fn)
    )

    grounding_rate = (
        1.0
        if emitted_value_count == 0
        else (emitted_value_count - hallucination_count) / emitted_value_count
    )
    boundary_correctness = (
        1.0 if not cases else fixtures_with_correct_boundary / len(cases)
    )
    exact_match_rate = (
        1.0
        if total_aligned_records == 0
        else exact_record_matches / total_aligned_records
    )

    return SurfaceReport(
        surface=surface,
        fixture_count=len(cases),
        field_precision=field_precision,
        field_recall=field_recall,
        per_field={
            name: {
                "precision": m.precision,
                "recall": m.recall,
                "tp": m.tp,
                "fp": m.fp,
                "fn": m.fn,
            }
            for name, m in sorted(per_field.items())
        },
        emitted_value_count=emitted_value_count,
        hallucination_count=hallucination_count,
        grounding_rate=grounding_rate,
        boundary_correctness=boundary_correctness,
        exact_match_rate=exact_match_rate,
        produced_record_count=produced_record_total,
        expected_record_count=expected_record_total,
    )
