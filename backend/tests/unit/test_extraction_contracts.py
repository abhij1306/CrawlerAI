from __future__ import annotations

import pytest

from app.services.domain_selector_health import (
    CRITICAL_FIELDS_BY_SURFACE,
    SelectorHealthSnapshot,
)
from app.services.extract.contracts import (
    CandidateSet,
    ExtractionResult,
    ExtractionWarning,
    RuntimeMetrics,
)


@pytest.mark.unit
def test_extraction_contracts_serialize_cleanly() -> None:
    candidate_set = CandidateSet(
        surface="ecommerce_detail",
        page_url="https://example.com/p",
    )
    evidence_id = candidate_set.add(
        field_name="title",
        value="Cotton Shirt",
        source="dom",
        extraction_tier="dom",
        candidate_index=0,
        confidence=0.9,
    )
    result = ExtractionResult(
        surface="ecommerce_detail",
        page_url="https://example.com/p",
        record={"title": "Cotton Shirt"},
        candidates=candidate_set,
        warnings=[ExtractionWarning(code="missing_price", message="price missing")],
    )

    payload = result.model_dump(mode="json")

    assert payload["record"]["title"] == "Cotton Shirt"
    assert payload["candidates"]["candidates"][0]["source"] == "dom"
    assert evidence_id == "ev_000001"
    assert candidate_set.as_graph()["field_evidence"][evidence_id]["field_name"] == "title"


@pytest.mark.unit
def test_candidate_set_records_semantic_conflict_and_resolution_reasons() -> None:
    candidate_set = CandidateSet(
        surface="ecommerce_detail",
        page_url="https://example.com/p",
    )
    adapter_id = candidate_set.add(
        field_name="price",
        value="19.99",
        source="adapter",
        extraction_tier="authoritative",
        candidate_index=0,
        source_locator="adapter:price",
    )
    json_ld_id = candidate_set.add(
        field_name="price",
        value="29.99",
        source="json_ld",
        extraction_tier="structured_data",
        candidate_index=1,
        source_locator="json_ld:offers.price",
    )

    summary = candidate_set.record_resolution(
        field_name="price",
        winning_evidence_ids=[adapter_id],
        resolver_rule="source_priority",
    )
    graph = candidate_set.as_graph()

    assert summary["conflict_count"] == 1
    assert graph["field_decisions"]["price"]["winning_evidence_ids"] == [adapter_id]
    assert graph["field_decisions"]["price"]["rejected_candidates"] == [
        {"evidence_id": json_ld_id, "reason": "lower_source_priority"}
    ]
    assert graph["field_evidence"][json_ld_id]["source_locator"] == (
        "json_ld:offers.price"
    )
    assert candidate_set.field_sources("price") == ["adapter", "json_ld"]
    assert candidate_set.winning_field_sources("price") == ["adapter"]


@pytest.mark.unit
def test_candidate_set_records_graph_transform() -> None:
    candidate_set = CandidateSet(
        surface="ecommerce_detail",
        page_url="https://example.com/p",
    )

    transform_id = candidate_set.record_transform(
        field_name="price",
        before_value="190.00",
        after_value="310.00",
        rule_id="parent_price_from_unanimous_variant_price",
        input_evidence_ids=["ev_000001"],
        output_source="detail_price_core",
    )

    graph = candidate_set.as_graph()

    assert transform_id == "tx_000001"
    assert graph["field_transforms"] == [
        {
            "transform_id": "tx_000001",
            "field_name": "price",
            "entity_ref": "product",
            "before_value": "190.00",
            "after_value": "310.00",
            "rule_id": "parent_price_from_unanimous_variant_price",
            "input_evidence_ids": ["ev_000001"],
            "output_source": "detail_price_core",
            "metadata": {},
        }
    ]


@pytest.mark.unit
def test_selector_health_and_runtime_metrics_serialize_cleanly() -> None:
    snapshot = SelectorHealthSnapshot(
        domain="example.com",
        surface="ecommerce_detail",
        field_name="price",
        selector="[itemprop=price]",
        critical=True,
    )
    metrics = RuntimeMetrics(counters={"browser_fetch": 2})

    assert "price" in CRITICAL_FIELDS_BY_SURFACE["ecommerce_detail"]
    assert snapshot.model_dump(mode="json")["critical"] is True
    assert metrics.model_dump(mode="json") == {"counters": {"browser_fetch": 2}}
