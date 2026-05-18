from __future__ import annotations

from app.services.ucp_audit.compliance_checks import (
    build_policy_readability_report,
    build_variant_fidelity_report,
)


def test_variant_fidelity_flags_collapsed_missing_sku_and_availability() -> None:
    report = build_variant_fidelity_report(
        [
            {
                "variants": [
                    {"price": 10, "currency": "USD", "sku": "", "availability": ""},
                    {"price": 10, "currency": "USD", "sku": "SKU-2", "availability": ""},
                ]
            }
        ]
    )

    assert report.products_with_variants_sampled == 1
    assert report.collapsed_offers_count == 1
    assert report.missing_sku_count == 1
    assert report.missing_availability_count == 2
    assert {finding.code for finding in report.findings} == {
        "variant_offers_collapsed",
        "variant_sku_missing",
        "variant_availability_missing",
    }


def test_policy_readability_scores_each_signal() -> None:
    report = build_policy_readability_report(
        structured_shipping_found=True,
        period_machine_readable=False,
        currency_value="USD",
        policy_page_http_accessible=True,
    )

    assert report.currency_is_iso4217 is True
    assert report.readability_score == 75
    assert [finding.code for finding in report.findings] == [
        "policy_return_period_missing"
    ]
