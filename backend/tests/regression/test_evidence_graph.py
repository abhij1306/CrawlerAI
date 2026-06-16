from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.export.schema import build_source_trace
from app.services.extract.contracts import CandidateSet
from app.services.extract.detail.assembly.final_cleanup import (
    repair_ecommerce_detail_record_quality,
)
from app.services.extract.detail.assembly.record_assembly import build_detail_record
from app.services.extract.detail.validation import validate_product_evidence


@pytest.mark.regression
def test_detail_record_emits_index_aligned_candidate_evidence() -> None:
    record = build_detail_record(
        """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "Widget Prime",
              "offers": {"@type": "Offer", "price": "19.99", "priceCurrency": "USD"}
            }
            </script>
          </head>
          <body><main><h1>Widget Prime</h1></main></body>
        </html>
        """,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        ["title", "price", "currency"],
        adapter_records=[{"title": "Widget Prime"}],
    )

    graph = record.get("_evidence_graph")
    assert isinstance(graph, dict)
    title_graph = [
        evidence
        for evidence in graph["field_evidence"].values()
        if evidence["field_name"] == "title"
    ]
    assert [evidence["candidate_index"] for evidence in title_graph] == list(
        range(len(title_graph))
    )
    assert all(evidence["source_locator"] for evidence in title_graph)
    assert record["_field_evidence"]["title"]["winning_evidence_ids"]
    assert record["_field_evidence"]["title"]["conflict_count"] >= 0


@pytest.mark.regression
def test_source_trace_exposes_evidence_summary_without_public_data_leak() -> None:
    record = {
        "source_url": "https://example.com/products/widget",
        "url": "https://example.com/products/widget",
        "title": "Widget",
        "_source": "json_ld",
        "_field_sources": {"title": ["json_ld"]},
        "_field_evidence": {
            "title": {
                "winning_evidence_ids": ["ev_1"],
                "candidate_count": 2,
                "rejected_candidate_count": 1,
                "conflict_count": 0,
                "validation_finding_ids": ["vf_1"],
                "resolver_rule": "source_priority",
                "llm_used": False,
            }
        },
        "_evidence_graph": {"field_evidence": {"ev_1": {"field_name": "title"}}},
        "_validation_findings": [
            {"finding_id": "vf_1", "rule_id": "TEST_RULE", "severity": "low"}
        ],
        "_transforms": [
            {
                "rule_id": "VARIANT_CONSENSUS_TO_PRODUCT",
                "field_name": "color",
                "before": "Brown",
                "after": "Jet Black",
            }
        ],
    }
    acquisition = SimpleNamespace(
        method="test",
        status_code=200,
        final_url="https://example.com/products/widget",
        blocked=False,
        adapter_name=None,
        adapter_source_type=None,
        network_payloads=[],
        browser_diagnostics={},
    )

    trace = build_source_trace(
        acquisition,
        record,
        data={"url": record["url"], "title": record["title"]},
    )

    title_trace = trace["field_discovery"]["title"]
    assert title_trace["winning_evidence_ids"] == ["ev_1"]
    assert title_trace["candidate_count"] == 2
    assert trace["extraction"]["review_bucket"] == []
    assert trace["extraction"]["validation_findings"][0]["finding_id"] == "vf_1"
    assert trace["extraction"]["transforms"][0]["rule_id"] == (
        "VARIANT_CONSENSUS_TO_PRODUCT"
    )
    assert "_evidence_graph" not in trace


@pytest.mark.regression
def test_missing_product_knowledge_becomes_reviewable_evidence_finding() -> None:
    findings = validate_product_evidence(
        {
            "title": "Mens Nano Puff Insulated Jacket",
            "url": "https://example.com/product/jacket",
        }
    )

    assert {finding["rule_id"] for finding in findings} == {
        "MISSING_PRODUCT_OFFER_EVIDENCE",
        "INSUFFICIENT_DETAIL_EVIDENCE",
    }


@pytest.mark.regression
def test_validation_findings_link_field_evidence() -> None:
    record = build_detail_record(
        "<html><body><h1>Widget Prime</h1></body></html>",
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        ["title", "price", "currency"],
    )

    findings = record["_validation_findings"]
    assert all(finding["evidence_ids"] == [] for finding in findings)
    linked_title_findings = set(
        record["_field_evidence"]["title"].get("validation_finding_ids") or []
    )
    assert linked_title_findings.isdisjoint(
        finding["finding_id"] for finding in findings
    )


@pytest.mark.regression
def test_semantic_losing_candidate_enters_review_bucket() -> None:
    record = build_detail_record(
        """
        <html>
          <head>
            <script type="application/ld+json">
            {"@type": "Product", "name": "Structured Widget"}
            </script>
          </head>
          <body><h1>DOM Widget</h1></body>
        </html>
        """,
        "https://example.com/products/widget",
        "ecommerce_detail",
        ["title"],
        adapter_records=[{"title": "Adapter Widget"}],
    )

    assert record["_field_evidence"]["title"]["conflict_count"] > 0
    assert record["_field_sources"]["title"] == ["adapter"]
    assert any(
        row["key"] == "title" and row["value"] != record["title"]
        for row in record["_review_bucket"]
    )


@pytest.mark.regression
def test_detail_price_repair_is_recorded_in_evidence_graph_transform() -> None:
    record = {
        "title": "Widget Prime",
        "price": "190.00",
        "currency": "USD",
        "variants": [
            {"sku": "W-1", "size": "S", "price": "310.00", "currency": "USD"},
            {"sku": "W-2", "size": "M", "price": "310.00", "currency": "USD"},
        ],
        "_field_evidence": {"price": {"winning_evidence_ids": ["ev_000001"]}},
    }
    evidence_builder = CandidateSet(
        surface="ecommerce_detail",
        page_url="https://example.com/products/widget-prime",
    )

    repair_ecommerce_detail_record_quality(
        record,
        evidence_builder=evidence_builder,
        html="",
        page_url="https://example.com/products/widget-prime",
    )
    transforms = evidence_builder.as_graph()["field_transforms"]

    assert record["price"] == "310.00"
    assert any(
        transform["field_name"] == "price"
        and transform["before_value"] == "190.00"
        and transform["after_value"] == "310.00"
        for transform in transforms
    )


@pytest.mark.regression
def test_detail_variants_have_graph_only_row_lineage() -> None:
    record = build_detail_record(
        "<html><body><h1>Widget Prime</h1></body></html>",
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        ["title", "variants"],
        adapter_records=[
            {
                "title": "Widget Prime",
                "variants": [{"sku": "W-1", "size": "S"}, {"sku": "W-2", "size": "M"}],
            }
        ],
    )

    assert all("row_lineage" not in row for row in record["variants"])
    assert record["_evidence_graph"]["row_lineage"]
