from __future__ import annotations

from app.services.ucp_audit.catalog_checks import (
    build_metafield_coverage_report,
    build_taxonomy_consistency_report,
)
from app.services.ucp_audit.types import UCPSchemaScore


def schema_score(
    *,
    properties: list[dict[str, object]] | None = None,
    product_type: str | None = None,
) -> UCPSchemaScore:
    return UCPSchemaScore(
        url="https://example.com/p",
        product_jsonld_found=True,
        required_fields_present=[],
        recommended_fields_present=[],
        ucp_fields_present=[],
        completeness_score=0,
        missing_required=[],
        missing_recommended=[],
        raw_additional_properties=list(properties or []),
        raw_product_type=product_type,
        raw_offers=[],
    )


def test_metafield_coverage_flags_attribute_below_threshold() -> None:
    results = [
        schema_score(properties=[{"name": "size", "value": "M"}]),
        schema_score(properties=[]),
        schema_score(properties=[]),
        schema_score(properties=[]),
        schema_score(properties=[]),
    ]

    report = build_metafield_coverage_report(results)

    assert report.total_sampled == 5
    assert report.coverage_by_attribute["size"] == 0.2
    assert "size" in report.critical_gaps


def test_taxonomy_clusters_case_normalized_values() -> None:
    results = [
        schema_score(product_type="T-Shirt"),
        schema_score(product_type="t-shirt"),
        schema_score(product_type="Tee"),
    ]

    report = build_taxonomy_consistency_report(results)

    assert ["T-Shirt", "t-shirt"] in report.duplicate_clusters
    assert report.unique_raw_values == ["T-Shirt", "Tee", "t-shirt"]


def test_taxonomy_flags_shallow_categories() -> None:
    report = build_taxonomy_consistency_report([schema_score(product_type="Clothing")])

    assert report.shallow_categories == ["Clothing"]
