from __future__ import annotations

from collections import defaultdict

from app.services.config import ucp_audit as config
from app.services.data_enrichment.deterministic import load_taxonomy_index
from app.services.ucp_audit.types import (
    MetafieldCoverageReport,
    TaxonomyConsistencyReport,
    UCPSchemaScore,
)


def build_metafield_coverage_report(
    results: list[UCPSchemaScore],
) -> MetafieldCoverageReport:
    total = len(results)
    counts = {item: 0 for item in config.UCP_CRITICAL_ATTRIBUTES}
    for result in results:
        names = _property_names(result.raw_additional_properties)
        for attribute in counts:
            if attribute in names:
                counts[attribute] += 1
    coverage = {
        key: (round(value / total, 4) if total else 0.0)
        for key, value in counts.items()
    }
    gaps = [
        key
        for key, value in coverage.items()
        if value < config.UCP_METAFIELD_COVERAGE_THRESHOLD
    ]
    return MetafieldCoverageReport(
        total_sampled=total,
        coverage_by_attribute=coverage,
        critical_gaps=gaps,
        worst_product_types=_worst_product_types(results),
    )


def build_taxonomy_consistency_report(
    results: list[UCPSchemaScore],
) -> TaxonomyConsistencyReport:
    load_taxonomy_index()
    values = [
        value
        for value in (result.raw_product_type for result in results)
        if value not in (None, "")
    ]
    clusters = _duplicate_clusters(values)
    shallow = [value for value in values if _depth(value) < config.UCP_CATEGORY_DEPTH_MIN]
    penalties = len(clusters) + len(shallow)
    total = max(1, len(values))
    score = max(0, int(100 - ((penalties / total) * 100)))
    return TaxonomyConsistencyReport(
        unique_raw_values=sorted(set(values)),
        duplicate_clusters=clusters,
        shallow_categories=shallow,
        consistency_score=score,
    )


def _property_names(properties: list[dict]) -> set[str]:
    names: set[str] = set()
    for item in properties:
        name = str(item.get(config.JSON_LD_NAME_FIELD) or "").strip().casefold()
        if name:
            names.add(name)
    return names


def _worst_product_types(results: list[UCPSchemaScore]) -> list[str]:
    values = [
        str(result.raw_product_type or "").strip()
        for result in results
        if str(result.raw_product_type or "").strip()
        and result.raw_additional_properties == []
    ]
    return sorted(set(values))


def _duplicate_clusters(values: list[str]) -> list[list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for value in values:
        grouped[value.strip().casefold()].append(value)
    return [items for items in grouped.values() if len(set(items)) > 1]


def _depth(value: str) -> int:
    depth = 1 if str(value or "").strip() else 0
    for separator in config.UCP_CATEGORY_DEPTH_SEPARATORS:
        depth += str(value or "").count(separator)
    return depth
