"""run_health_verdict: in-flight verdict_counts drive the same failure signal.

Fixed-size progress patches carry ``verdict_counts`` (not the full
``url_verdicts`` list), so run health must derive failures from counts while a
run is in flight instead of defaulting every running run to "healthy".
"""

from __future__ import annotations

import pytest

from app.persistence.publish.verdict import run_health_verdict


@pytest.mark.unit
def test_verdict_counts_drive_in_flight_health() -> None:
    summary = {"url_count": 10, "verdict_counts": {"success": 4, "error": 6}}
    health = run_health_verdict(summary)
    assert health["failure_count"] == 6
    assert health["url_count"] == 10
    assert health["failure_rate"] == 0.6
    assert health["status"] == "failed"


@pytest.mark.unit
def test_verdict_counts_degraded_band() -> None:
    summary = {"url_count": 10, "verdict_counts": {"success": 9, "blocked": 1}}
    health = run_health_verdict(summary)
    assert health["failure_count"] == 1
    assert health["status"] == "degraded"


@pytest.mark.unit
def test_verdict_counts_healthy_when_failures_below_threshold() -> None:
    summary = {"url_count": 100, "verdict_counts": {"success": 98, "blocked": 2}}
    health = run_health_verdict(summary)
    assert health["failure_count"] == 2
    assert health["status"] == "healthy"


@pytest.mark.unit
def test_verdict_counts_partial_is_not_a_failure() -> None:
    summary = {"url_count": 4, "verdict_counts": {"partial": 4}}
    health = run_health_verdict(summary)
    assert health["failure_count"] == 0
    assert health["status"] == "healthy"


@pytest.mark.unit
def test_url_verdicts_list_wins_over_counts() -> None:
    summary = {
        "url_count": 3,
        "url_verdicts": ["success", "success", "success"],
        "verdict_counts": {"error": 3},
    }
    health = run_health_verdict(summary)
    assert health["failure_count"] == 0
    assert health["status"] == "healthy"


@pytest.mark.unit
def test_no_verdict_data_keeps_legacy_healthy_default() -> None:
    health = run_health_verdict({"url_count": 5})
    assert health["failure_count"] == 0
    assert health["status"] == "healthy"


@pytest.mark.unit
def test_malformed_count_values_are_ignored() -> None:
    summary = {
        "url_count": 2,
        "verdict_counts": {"success": "not-a-number", "error": 1},
    }
    health = run_health_verdict(summary)
    assert health["failure_count"] == 1
    assert health["url_count"] == 2
