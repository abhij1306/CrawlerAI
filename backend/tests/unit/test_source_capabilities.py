from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.acquisition.source_capabilities import (
    DETAIL_FIELD_FAMILIES,
    attach_source_capability_diagnostics,
    build_source_capability_diagnostics,
)

pytestmark = pytest.mark.unit


@dataclass
class _Result:
    html: str
    network_payloads: list[dict[str, object]]
    status_code: int = 200
    blocked: bool = False
    browser_diagnostics: dict[str, object] = field(default_factory=dict)
    acquisition_diagnostics: dict[str, object] = field(default_factory=dict)


def test_usable_html_can_coexist_with_unavailable_product_source() -> None:
    report = build_source_capability_diagnostics(
        html=(
            '<html><script type="application/ld+json">{}</script>'
            "<h1>Product</h1></html>"
        ),
        network_payloads=[
            {
                "endpoint_type": "product_api",
                "status": 403,
                "url": "https://example.test/product-api",
            }
        ],
    )

    assert report["html_present"] is True
    assert report["structured_data_present"] is True
    assert report["product_data_source_observed"] is True
    assert report["product_data_source_succeeded"] is False
    assert report["product_data_source_unavailable"] is True
    assert report["affected_field_families"] == (
        "price",
        "currency",
        "availability",
        "variants",
    )


def test_successful_product_source_prevents_false_unavailable_classification() -> None:
    report = build_source_capability_diagnostics(
        html="<html><h1>Product</h1></html>",
        network_payloads=[
            {"endpoint_type": "product_api", "status": 403},
            {"endpoint_type": "product_api", "status": 200},
        ],
    )

    assert report["product_data_source_observed"] is True
    assert report["product_data_source_succeeded"] is True
    assert report["product_data_source_unavailable"] is False
    assert report["affected_field_families"] == ()


def test_generic_json_failure_does_not_claim_product_source_unavailable() -> None:
    report = build_source_capability_diagnostics(
        html="<html><h1>Product</h1></html>",
        network_payloads=[
            {"endpoint_type": "generic_json", "status": 500},
        ],
    )

    assert report["product_data_source_observed"] is False
    assert report["product_data_source_unavailable"] is False
    assert report["affected_field_families"] == ()


def test_attach_preserves_existing_acquisition_diagnostics() -> None:
    result = _Result(
        html="<html><h1>Product</h1></html>",
        network_payloads=[
            {"endpoint_type": "product_api", "status": 403},
        ],
        acquisition_diagnostics={"plan_id": "plan-1"},
    )

    attach_source_capability_diagnostics(result)

    assert result.acquisition_diagnostics["plan_id"] == "plan-1"
    capabilities = result.acquisition_diagnostics["source_capabilities"]
    assert isinstance(capabilities, dict)
    assert capabilities["product_data_source_unavailable"] is True


def test_http_error_marks_source_unavailable_without_terminal_shell() -> None:
    report = build_source_capability_diagnostics(
        html="<html><h1>Missing product</h1></html>",
        network_payloads=[],
        status_code=404,
        browser_outcome="usable_content",
    )

    assert report["terminal_shell"] is False
    assert report["product_data_source_unavailable"] is True
    assert report["affected_field_families"] == (
        "price",
        "currency",
        "availability",
        "variants",
    )


@pytest.mark.parametrize(
    ("browser_outcome", "blocked"),
    [("challenge_page", False), ("low_content_shell", False), (None, True)],
)
def test_blocked_browser_outcomes_remain_terminal_shells(
    browser_outcome: str | None,
    blocked: bool,
) -> None:
    report = build_source_capability_diagnostics(
        html="<html></html>",
        network_payloads=[],
        browser_outcome=browser_outcome,
        blocked=blocked,
    )

    assert report["terminal_shell"] is True
    assert report["product_data_source_unavailable"] is True
    assert report["affected_field_families"] == DETAIL_FIELD_FAMILIES


def test_attach_reads_browser_outcome_from_production_diagnostics_shape() -> None:
    result = _Result(
        html="<html></html>",
        network_payloads=[],
        browser_diagnostics={"browser_outcome": "low_content_shell"},
    )

    attach_source_capability_diagnostics(result)

    capabilities = result.acquisition_diagnostics["source_capabilities"]
    assert isinstance(capabilities, dict)
    assert capabilities["terminal_shell"] is True
    assert capabilities["affected_field_families"] == DETAIL_FIELD_FAMILIES
