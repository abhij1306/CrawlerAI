"""Unit tests for the offline extraction evaluation harness.

Uses tiny inline fixtures (small HTML strings + expected fact dicts) to prove
the scorer's precision/recall/grounding/boundary math and the comparator's
pass/fail logic. Fully deterministic, no network, no LLM.
"""

from __future__ import annotations

import pytest

from eval.corpus import FixtureCase
from eval.run import compare, run_extractor
from eval.score import score_surface

pytestmark = pytest.mark.unit

_SURFACE = "ecommerce_listing"

# One fixture: two products in the source HTML.
_HTML = (
    "<ul>"
    "<li class='p'><span class='t'>Red Shoe</span><span class='pr'>$10</span></li>"
    "<li class='p'><span class='t'>Blue Hat</span><span class='pr'>$20</span></li>"
    "</ul>"
)

_EXPECTED = [
    {"title": "Red Shoe", "price": "$10"},
    {"title": "Blue Hat", "price": "$20"},
]


def _case() -> FixtureCase:
    return FixtureCase(stem="fixture-1", html=_HTML, expected_facts=_EXPECTED)


def test_perfect_extraction_scores_one() -> None:
    report = score_surface(_SURFACE, [_case()], [list(_EXPECTED)])
    assert report.field_precision == 1.0
    assert report.field_recall == 1.0
    assert report.boundary_correctness == 1.0
    assert report.exact_match_rate == 1.0
    assert report.hallucination_count == 0
    assert report.grounding_rate == 1.0


def test_known_tp_fp_fn_precision_recall() -> None:
    # Produced: Red Shoe correct title; price wrong (FP + FN for price);
    # second record missing entirely (FN for its two fields).
    produced = [
        [{"title": "Red Shoe", "price": "$99"}],
    ]
    # Note wrong record count is intentional here, but focus on field metrics.
    report = score_surface(_SURFACE, [_case()], produced)

    # title: 1 TP, 0 FP, 1 FN (second record's title missing)
    assert report.per_field["title"]["tp"] == 1
    assert report.per_field["title"]["fp"] == 0
    assert report.per_field["title"]["fn"] == 1
    # price: 0 TP (produced $99 not expected), 1 FP ($99), 2 FN ($10 + $20)
    assert report.per_field["price"]["tp"] == 0
    assert report.per_field["price"]["fp"] == 1
    assert report.per_field["price"]["fn"] == 2

    # Aggregate micro-average: TP=1, FP=1, FN=3
    assert report.field_precision == pytest.approx(1 / 2)
    assert report.field_recall == pytest.approx(1 / 4)


def test_value_absent_from_source_is_hallucination() -> None:
    # "Green Sock" never appears in _HTML -> flagged as hallucination.
    produced = [
        [
            {"title": "Red Shoe", "price": "$10"},
            {"title": "Green Sock", "price": "$20"},
        ]
    ]
    report = score_surface(_SURFACE, [_case()], produced)
    assert report.emitted_value_count == 4
    assert report.hallucination_count == 1
    assert report.grounding_rate == pytest.approx(3 / 4)


def test_wrong_record_count_fails_boundary_correctness() -> None:
    produced = [
        [{"title": "Red Shoe", "price": "$10"}],  # only 1 record vs expected 2
    ]
    report = score_surface(_SURFACE, [_case()], produced)
    assert report.produced_record_count == 1
    assert report.expected_record_count == 2
    assert report.boundary_correctness == 0.0


def test_run_extractor_drives_callable_over_fixtures() -> None:
    def extractor(_html: str) -> list[dict]:
        return list(_EXPECTED)

    report = run_extractor(extractor, _SURFACE, cases=[_case()])
    assert report["field_precision"] == 1.0
    assert report["fixture_count"] == 1
    assert report["surface"] == _SURFACE


def test_compare_passes_when_candidate_matches_or_beats_baseline() -> None:
    def perfect(_html: str) -> list[dict]:
        return list(_EXPECTED)

    baseline = run_extractor(perfect, _SURFACE, cases=[_case()])
    candidate = run_extractor(perfect, _SURFACE, cases=[_case()])
    result = compare(candidate, baseline)
    assert result.passed is True
    assert result.reasons == []


def test_compare_fails_when_candidate_regresses() -> None:
    def perfect(_html: str) -> list[dict]:
        return list(_EXPECTED)

    def worse(_html: str) -> list[dict]:
        # Drops the second record -> lower recall + boundary correctness.
        return [{"title": "Red Shoe", "price": "$10"}]

    baseline = run_extractor(perfect, _SURFACE, cases=[_case()])
    candidate = run_extractor(worse, _SURFACE, cases=[_case()])
    result = compare(candidate, baseline)
    assert result.passed is False
    assert any("field_recall" in r for r in result.reasons)
    assert any("boundary_correctness" in r for r in result.reasons)


def test_compare_fails_on_increased_hallucination() -> None:
    def clean(_html: str) -> list[dict]:
        return list(_EXPECTED)

    def hallucinating(_html: str) -> list[dict]:
        return [
            {"title": "Red Shoe", "price": "$10"},
            {"title": "Purple Ghost", "price": "$20"},  # not in source HTML
        ]

    baseline = run_extractor(clean, _SURFACE, cases=[_case()])
    candidate = run_extractor(hallucinating, _SURFACE, cases=[_case()])
    result = compare(candidate, baseline)
    assert result.passed is False
    assert any("hallucination_count" in r for r in result.reasons)
