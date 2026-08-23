from __future__ import annotations

# ruff: noqa: F403, F405
from .harness_runtime_test_support import *


@pytest.mark.regression
def test_classify_failure_mode_flags_missing_adapter_registration() -> None:
    result = {
        "ok": False,
        "platform_family": "ultipro_ukg",
        "surface": "job_listing",
        "adapter_name": None,
        "records": 0,
    }

    assert classify_failure_mode(result) == "adapter_not_registered"


@pytest.mark.regression
def test_classify_failure_mode_treats_browser_challenge_diagnostics_as_blocked() -> (
    None
):
    result = {
        "ok": False,
        "blocked": False,
        "browser_diagnostics": {
            "browser_outcome": "usable_content",
            "challenge_evidence": [
                "strong:captcha",
                "provider:cloudflare",
            ],
            "challenge_provider_hits": ["cloudflare"],
        },
        "surface": "ecommerce_listing",
        "records": 0,
    }

    assert classify_failure_mode(result) == "blocked"


@pytest.mark.regression
def test_challenge_summary_extracts_provider_and_evidence() -> None:
    diagnostics = {
        "browser_outcome": "challenge_page",
        "challenge_provider_hits": ["DataDome"],
        "challenge_element_hits": ["captcha-form"],
        "challenge_evidence": [
            "http_status:429",
            "title:Verifying your connection...",
            "provider:datadome",
        ],
    }

    assert harness_support._challenge_summary_from_diagnostics(diagnostics) == {
        "browser_outcome": "challenge_page",
        "provider": "datadome",
        "providers": ["datadome"],
        "elements": ["captcha-form"],
        "evidence": [
            "http_status:429",
            "title:Verifying your connection...",
            "provider:datadome",
        ],
    }


@pytest.mark.regression
def test_classify_failure_mode_rejects_placeholder_success_titles() -> None:
    result = {
        "verdict": "success",
        "records": 1,
        "sample_title": "Page Not Found",
        "populated_fields": 1,
        "surface": "ecommerce_listing",
    }

    assert classify_failure_mode(result) == "wrong_content_or_placeholder"


@pytest.mark.regression
def test_classify_failure_mode_rejects_oops_not_found_titles() -> None:
    result = {
        "verdict": "success",
        "records": 1,
        "sample_title": "Oops! The page you're looking for can't be found.",
        "populated_fields": 4,
        "surface": "ecommerce_detail",
    }

    assert classify_failure_mode(result) == "wrong_content_or_placeholder"


@pytest.mark.regression
def test_classify_failure_mode_reports_utility_chrome_as_success_reporting_only() -> (
    None
):
    result = {
        "verdict": "success",
        "records": 1,
        "sample_title": "Product Help",
        "sample_url": "https://example.com/help/product-help",
        "populated_fields": 3,
        "surface": "ecommerce_listing",
    }

    assert classify_failure_mode(result) == "success"


@pytest.mark.regression
def test_classify_failure_mode_rejects_detail_identity_mismatches() -> None:
    result = {
        "verdict": "success",
        "records": 1,
        "surface": "ecommerce_detail",
        "requested_url": "https://www.practicesoftwaretesting.com/product/practice-software-testing",
        "sample_title": "Practice Software Testing - Toolshop - v5.0",
        "sample_url": "https://www.practicesoftwaretesting.com/",
        "populated_fields": 4,
    }

    assert classify_failure_mode(result) == "detail_identity_mismatch"


@pytest.mark.regression
def test_classify_failure_mode_rejects_fragment_backed_detail_identity_mismatches() -> (
    None
):
    result = {
        "verdict": "success",
        "records": 1,
        "surface": "ecommerce_detail",
        "requested_url": "https://www.practicesoftwaretesting.com/#/product/01HB",
        "sample_title": "Practice Software Testing",
        "sample_url": "https://www.practicesoftwaretesting.com/",
        "populated_fields": 4,
    }

    assert classify_failure_mode(result) == "detail_identity_mismatch"


@pytest.mark.regression
def test_classify_failure_mode_rejects_same_site_wrong_product_slug() -> None:
    result = {
        "verdict": "success",
        "records": 1,
        "surface": "ecommerce_detail",
        "requested_url": "https://www.thriftbooks.com/w/the-pragmatic-programmer_david-thomas_andrew-hunt/286697/",
        "sample_title": "The Biggest Loser Fitness Program",
        "sample_url": "https://www.thriftbooks.com/w/the-biggest-loser-fitness-program_maggie-greenwood-robinson/286697/",
        "populated_fields": 9,
    }

    assert classify_failure_mode(result) == "detail_identity_mismatch"


@pytest.mark.regression
def test_classify_failure_mode_does_not_infer_detail_identity_mismatch_without_requested_url() -> (
    None
):
    result = {
        "verdict": "success",
        "records": 1,
        "surface": "ecommerce_detail",
        "sample_title": "Widget Prime",
        "sample_url": "https://example.com/",
        "populated_fields": 4,
    }

    assert classify_failure_mode(result) == "success"


@pytest.mark.regression
def test_acceptance_runner_requires_unbucketed_runs_to_succeed() -> None:
    site = {
        "name": "Catalog",
        "url": "https://example.com/catalog",
        "surface": "ecommerce_listing",
    }
    result = {
        "failure_mode": "listing_extraction_empty",
    }

    assert expectation_met(site, result) is False
