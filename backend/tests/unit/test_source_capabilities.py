from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.acquisition.source_capabilities import (
    attach_source_capability_diagnostics,
    build_source_capability_diagnostics,
)

pytestmark = pytest.mark.unit


@dataclass
class _Result:
    html: str
    network_payloads: list[dict[str, object]]
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
