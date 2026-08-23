from __future__ import annotations

# ruff: noqa: F403, F405
from .harness_runtime_test_support import *


@pytest.mark.regression
def test_acceptance_runner_uses_quality_verdict_for_curated_sites() -> None:
    site = {
        "name": "Catalog",
        "url": "https://example.com/catalog",
        "surface": "ecommerce_listing",
        "bucket": "must_pass",
        "quality_expectations": {"require_listing_noise_free": True},
    }
    result = {
        "quality_verdict": "usable_with_gaps",
    }

    assert expectation_met(site, result) is False


@pytest.mark.regression
def test_acceptance_runner_allows_bucketed_expected_failure_modes() -> None:
    site = {
        "name": "Blocked catalog",
        "url": "https://example.com/catalog",
        "surface": "ecommerce_listing",
        "bucket": "known_issue",
        "expected_failure_modes": ["listing_extraction_empty"],
    }
    result = {
        "failure_mode": "listing_extraction_empty",
    }

    assert expectation_met(site, result) is True


@pytest.mark.regression
def test_classify_failure_mode_buckets_spa_shell_failures() -> None:
    shell_404 = {
        "status_code": 404,
        "browser_diagnostics": {"browser_outcome": "low_content_shell"},
        "surface": "ecommerce_listing",
        "records": 0,
    }
    shell_low_content = {
        "status_code": 200,
        "browser_diagnostics": {"browser_outcome": "low_content_shell"},
        "surface": "ecommerce_listing",
        "records": 0,
    }
    readiness_timeout = {
        "status_code": 200,
        "browser_diagnostics": {
            "browser_outcome": "usable_content",
            "networkidle_timed_out": True,
        },
        "surface": "ecommerce_listing",
        "records": 0,
    }

    assert classify_failure_mode(shell_404) == "spa_shell_404"
    assert classify_failure_mode(shell_low_content) == "spa_shell_low_content"
    assert classify_failure_mode(readiness_timeout) == "spa_readiness_timeout"


@pytest.mark.regression
def test_classify_failure_mode_treats_uppercase_success_verdict_as_success() -> None:
    result = {
        "verdict": "SUCCESS",
        "browser_diagnostics": {},
        "records": 1,
        "sample_title": "Widget",
        "populated_fields": 3,
    }

    assert classify_failure_mode(result) == "success"
