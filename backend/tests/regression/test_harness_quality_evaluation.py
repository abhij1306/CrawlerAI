from __future__ import annotations

# ruff: noqa: F403, F405
from .harness_runtime_test_support import *
from harness.artifact_quality_cases import _first_mapping
from harness.quality_evaluator import build_acceptance_gate_report


@pytest.mark.regression
def test_artifact_mapping_normalization_preserves_direct_mappings() -> None:
    mapping = {"price": "captured_published"}

    assert _first_mapping(mapping) is mapping
    assert _first_mapping([mapping]) is mapping
    assert _first_mapping([]) == {}


@pytest.mark.regression
def test_acceptance_gate_keeps_unknown_reopened_issue_ids() -> None:
    report = build_acceptance_gate_report(
        {"gate_result": "passed", "reopened_issue_ids": ["QD-03", "CUSTOM-01"]}
    )

    assert report["quality_clean"] is False
    assert report["unresolved_issue_ids"] == ("QD-03", "CUSTOM-01")


@pytest.mark.regression
def test_evaluate_quality_flags_shell_false_success() -> None:
    site = {
        "url": "https://www.uniqlo.com/in/en/products/E474244-000/01",
        "surface": "ecommerce_detail",
        "quality_expectations": {
            "require_identity": True,
            "require_price": True,
            "expect_variants": True,
            "require_semantic_variant_labels": True,
            "require_variant_price": True,
        },
    }
    result = {
        "surface": "ecommerce_detail",
        "requested_url": "https://www.uniqlo.com/in/en/products/E474244-000/01",
        "sample_title": "UNIQLO - LifeWear",
        "sample_url": "https://www.uniqlo.com/in/en/products/E474244-000/01",
        "populated_fields": 6,
        "sample_semantics": {
            "price_present": False,
            "variant_count": 0,
            "variants_with_axes_count": 0,
            "variants_all_have_axes": False,
            "variants_with_price_count": 0,
            "legacy_variant_keys_present": False,
        },
        "failure_mode": "success",
        "sample_records": [],
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "bad_output"
    assert quality["observed_failure_mode"] == "shell_false_success"
    assert quality["quality_checks"]["identity_ok"] is False


@pytest.mark.regression
def test_evaluate_quality_does_not_call_error_shell_success() -> None:
    site = {
        "url": "https://www.newbalance.com/pd/example.html",
        "surface": "ecommerce_detail",
        "quality_expectations": {"require_identity": True},
    }
    result = {
        "surface": "ecommerce_detail",
        "requested_url": "https://www.newbalance.com/pd/example.html",
        "sample_title": "",
        "sample_url": "",
        "populated_fields": 0,
        "sample_semantics": {"price_present": False, "variant_count": 0},
        "failure_mode": "error",
        "sample_records": [],
    }

    quality = evaluate_quality(site, result)

    assert quality["observed_failure_mode"] == "error"


@pytest.mark.regression
def test_evaluate_quality_flags_axis_pollution_as_gap() -> None:
    site = {
        "url": "https://www.gymshark.com/products/example",
        "surface": "ecommerce_detail",
        "quality_expectations": {
            "require_identity": True,
            "require_price": True,
            "expect_variants": True,
            "require_semantic_variant_labels": True,
            "require_variant_price": True,
        },
    }
    result = {
        "surface": "ecommerce_detail",
        "requested_url": "https://www.gymshark.com/products/example",
        "sample_title": "Everyday Seamless Leggings",
        "sample_url": "https://www.gymshark.com/products/example",
        "populated_fields": 20,
        "sample_semantics": {
            "price_present": True,
            "variant_count": 7,
            "variants_with_axes_count": 0,
            "variants_all_have_axes": False,
            "variants_with_price_count": 7,
            "legacy_variant_keys_present": False,
        },
        "failure_mode": "success",
        "sample_records": [],
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "usable_with_gaps"
    assert quality["observed_failure_mode"] == "axis_pollution"
    assert quality["quality_checks"]["identity_ok"] is True
    assert quality["quality_checks"]["variant_labels_ok"] is False


@pytest.mark.regression
def test_evaluate_quality_flags_audit_price_magnitude_anomaly() -> None:
    site = {
        "surface": "ecommerce_detail",
        "quality_expectations": {
            "require_identity": True,
            "require_price": True,
            "require_price_sane": True,
        },
    }
    result = {
        "surface": "ecommerce_detail",
        "requested_url": "https://example.com/products/food-processor",
        "sample_title": "KitchenAid Food Processor",
        "sample_url": "https://example.com/products/food-processor",
        "populated_fields": 8,
        "sample_record_data": {
            "title": "KitchenAid Food Processor",
            "url": "https://example.com/products/food-processor",
            "price": "22999.00",
            "currency": "USD",
        },
        "sample_semantics": {"price_present": True},
        "failure_mode": "success",
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "bad_output"
    assert quality["observed_failure_mode"] == "price_magnitude_anomaly"
    assert quality["quality_checks"]["price_sane_ok"] is False


@pytest.mark.regression
def test_evaluate_quality_flags_audit_category_pollution() -> None:
    site = {
        "surface": "ecommerce_detail",
        "quality_expectations": {"require_clean_category": True},
    }
    result = {
        "surface": "ecommerce_detail",
        "requested_url": "https://example.com/products/shoe",
        "sample_title": "Stan Smith Shoes",
        "sample_url": "https://example.com/products/shoe",
        "populated_fields": 8,
        "sample_record_data": {
            "title": "Stan Smith Shoes",
            "url": "https://example.com/products/shoe",
            "category": "Back > Home > Men > Shoes",
            "price": "99.99",
        },
        "sample_semantics": {"price_present": True},
        "failure_mode": "success",
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "bad_output"
    assert quality["observed_failure_mode"] == "category_pollution"
    assert quality["quality_checks"]["category_clean_ok"] is False


@pytest.mark.regression
def test_evaluate_quality_flags_audit_long_text_pollution() -> None:
    site = {
        "surface": "ecommerce_detail",
        "quality_expectations": {"require_clean_long_text": True},
    }
    result = {
        "surface": "ecommerce_detail",
        "requested_url": "https://example.com/products/duvet",
        "sample_title": "Cotton Duvet",
        "sample_url": "https://example.com/products/duvet",
        "populated_fields": 8,
        "sample_record_data": {
            "title": "Cotton Duvet",
            "url": "https://example.com/products/duvet",
            "description": "Choose from Same Day Delivery, Drive Up or Order Pickup",
            "price": "49.99",
        },
        "sample_semantics": {"price_present": True},
        "failure_mode": "success",
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "bad_output"
    assert quality["observed_failure_mode"] == "long_text_pollution"
    assert quality["quality_checks"]["long_text_clean_ok"] is False


@pytest.mark.regression
def test_evaluate_quality_flags_audit_variant_and_system_artifacts() -> None:
    site = {
        "surface": "ecommerce_detail",
        "quality_expectations": {
            "require_clean_variants": True,
            "require_clean_system_fields": True,
        },
    }
    result = {
        "surface": "ecommerce_detail",
        "requested_url": "https://example.com/products/jacket",
        "sample_title": "Leather Jacket",
        "sample_url": "https://example.com/products/jacket",
        "populated_fields": 10,
        "sample_record_data": {
            "title": "Leather Jacket",
            "url": "https://example.com/products/jacket",
            "price": "1500.00",
            "sku": "COPY-1720644688978",
            "product_type": "inline",
            "variant_axes": {"discount": ["20%"]},
            "variants": [{"option_values": {"discount": "20%"}}],
        },
        "sample_semantics": {
            "price_present": True,
            "variant_count": 1,
            "variants_with_axes_count": 0,
            "variants_all_have_axes": False,
            "variants_with_price_count": 1,
            "legacy_variant_keys_present": True,
        },
        "failure_mode": "success",
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "bad_output"
    assert quality["observed_failure_mode"] == "variant_artifact_pollution"
    assert quality["quality_checks"]["variant_artifacts_ok"] is False
    assert quality["quality_checks"]["system_artifacts_ok"] is False


@pytest.mark.regression
def test_evaluate_quality_accepts_canonical_flat_variant_transport_fields() -> None:
    site = {
        "surface": "ecommerce_detail",
        "quality_expectations": {"require_clean_variants": True},
    }
    result = {
        "surface": "ecommerce_detail",
        "requested_url": "https://example.com/products/jacket",
        "sample_title": "Leather Jacket",
        "sample_url": "https://example.com/products/jacket",
        "populated_fields": 10,
        "sample_record_data": {
            "title": "Leather Jacket",
            "url": "https://example.com/products/jacket",
            "price": "1500.00",
            "variants": [
                {
                    "fit": "Slim",
                    "sku": "JACKET-S",
                    "barcode": "123456789012",
                    "size": "S",
                    "price": "1500.00",
                    "currency": "USD",
                }
            ],
        },
        "sample_semantics": {"price_present": True, "variant_count": 1},
        "failure_mode": "success",
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_checks"]["variant_artifacts_ok"] is True


@pytest.mark.regression
def test_evaluate_quality_flags_cross_cutting_detail_invariants() -> None:
    site = {
        "surface": "ecommerce_detail",
        "quality_expectations": {
            "require_clean_category": True,
            "require_clean_long_text": True,
            "require_clean_variants": True,
            "require_variant_currency_parity": True,
            "require_identifier_shapes": True,
            "require_title_not_internal_token": True,
        },
    }
    result = {
        "surface": "ecommerce_detail",
        "requested_url": "https://example.com/products/widget",
        "sample_title": "specifications",
        "sample_url": "https://example.com/products/widget",
        "populated_fields": 10,
        "sample_record_data": {
            "title": "specifications",
            "url": "https://example.com/products/widget",
            "category": "Shop by Shoes > Best Sellers > specifications",
            "description": "Shipping and Returns Orders may take up to 48 business hours.",
            "barcode": "ABC123",
            "gender": "default",
            "currency": "USD",
            "variants": [{"size": "M", "price": "19.99", "currency": "EUR"}],
        },
        "sample_semantics": {"price_present": True, "variant_count": 1},
        "failure_mode": "success",
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "bad_output"
    assert quality["quality_checks"]["category_clean_ok"] is False
    assert quality["quality_checks"]["long_text_clean_ok"] is False
    assert quality["quality_checks"]["variant_currency_parity_ok"] is False
    assert quality["quality_checks"]["variant_artifacts_ok"] is True
    assert quality["quality_checks"]["identifier_shapes_ok"] is False
    assert quality["quality_checks"]["title_token_ok"] is False
    assert quality["observed_failure_mode"] == "category_pollution"


@pytest.mark.regression
def test_evaluate_quality_flags_listing_chrome_noise() -> None:
    site = {
        "url": "https://www.customink.com/products/sweatshirts/hoodies/71",
        "surface": "ecommerce_listing",
        "quality_expectations": {
            "require_listing_noise_free": True,
            "require_price": True,
        },
    }
    result = {
        "surface": "ecommerce_listing",
        "sample_records": [
            {
                "title": "Customer Reviews",
                "url": "https://www.customink.com/reviews",
                "populated_fields": 3,
                "price_present": False,
            }
        ],
        "sample_title": "Customer Reviews",
        "sample_url": "https://www.customink.com/reviews",
        "sample_looks_like_utility_chrome": True,
        "failure_mode": "success",
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "bad_output"
    assert quality["observed_failure_mode"] == "listing_chrome_noise"


@pytest.mark.regression
def test_evaluate_quality_flags_listing_sample_window_without_real_product_rows() -> (
    None
):
    site = {
        "url": "https://www.customink.com/products/sweatshirts/hoodies/71",
        "surface": "ecommerce_listing",
        "quality_expectations": {
            "require_listing_noise_free": True,
            "require_price": True,
        },
    }
    result = {
        "surface": "ecommerce_listing",
        "sample_title": "Diversity & Belonging",
        "sample_url": "https://www.customink.com/equity-for-all",
        "records": 14,
        "populated_fields": 2,
        "sample_records": [
            {
                "title": "Diversity & Belonging",
                "url": "https://www.customink.com/equity-for-all",
                "populated_fields": 2,
                "price_present": False,
            },
            {
                "title": "Customer Reviews",
                "url": "https://www.customink.com/reviews",
                "populated_fields": 2,
                "price_present": False,
            },
            {
                "title": "Customer Photos",
                "url": "https://www.customink.com/photos",
                "populated_fields": 2,
                "price_present": False,
            },
        ],
        "sample_semantics": {
            "price_present": False,
            "variant_count": 0,
            "variants_with_axes_count": 0,
            "variants_all_have_axes": False,
            "variants_with_price_count": 0,
            "legacy_variant_keys_present": False,
        },
        "failure_mode": "success",
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "bad_output"
    assert quality["observed_failure_mode"] == "listing_chrome_noise"
    assert quality["quality_checks"]["listing_noise_ok"] is False


@pytest.mark.regression
def test_evaluate_quality_accepts_non_utility_listing_rows_without_price_when_field_coverage_is_strong() -> (
    None
):
    site = {
        "url": "https://www.sigmaaldrich.com/IN/en/products/chemistry-and-biochemicals/biochemicals/antibiotics",
        "surface": "ecommerce_listing",
        "quality_expectations": {
            "require_listing_noise_free": True,
        },
    }
    result = {
        "surface": "ecommerce_listing",
        "sample_title": "Antibiotic Antimycotic Solution (100×), Stabilized",
        "sample_url": "https://www.sigmaaldrich.com/IN/en/product/sigma/a5955",
        "records": 8,
        "populated_fields": 3,
        "sample_records": [
            {
                "title": "Antibiotic Antimycotic Solution (100×), Stabilized",
                "url": "https://www.sigmaaldrich.com/IN/en/product/sigma/a5955",
                "populated_fields": 3,
                "price_present": False,
            },
            {
                "title": "Puromycin dihydrochloride from Streptomyces alboniger",
                "url": "https://www.sigmaaldrich.com/IN/en/product/sigma/p8833",
                "populated_fields": 3,
                "price_present": False,
            },
            {
                "title": "Ampicillin sodium salt",
                "url": "https://www.sigmaaldrich.com/IN/en/product/sigma/a5354",
                "populated_fields": 3,
                "price_present": False,
            },
        ],
        "sample_semantics": {
            "price_present": False,
            "variant_count": 0,
            "variants_with_axes_count": 0,
            "variants_all_have_axes": False,
            "variants_with_price_count": 0,
            "legacy_variant_keys_present": False,
        },
        "failure_mode": "success",
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "good"
    assert quality["observed_failure_mode"] == "control_good"
    assert quality["quality_checks"]["listing_noise_ok"] is True


@pytest.mark.regression
def test_evaluate_quality_does_not_flag_job_account_slug_as_utility() -> None:
    site = {
        "name": "EU Remote Jobs",
        "url": "https://euremotejobs.com/",
        "surface": "job_listing",
        "quality_expectations": {"require_listing_noise_free": True},
    }
    result = {
        "status": "completed",
        "verdict": "success",
        "records": 1,
        "sample_records": [
            {
                "title": "Account Manager: Generator Customers",
                "url": "https://euremotejobs.com/job/account-manager-generator-customers/",
                "populated_fields": 7,
                "price_present": False,
            }
        ],
        "sample_semantics": {
            "price_present": False,
            "variant_count": 0,
            "variants_with_axes_count": 0,
            "variants_all_have_axes": False,
            "variants_with_price_count": 0,
            "legacy_variant_keys_present": False,
        },
        "failure_mode": "success",
    }

    quality = evaluate_quality(site, result)

    assert quality["quality_verdict"] == "bad_output"
    assert quality["observed_failure_mode"] == "bad_output"
    assert quality["quality_checks"]["listing_noise_ok"] is True
