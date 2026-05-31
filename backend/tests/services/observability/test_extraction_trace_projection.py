"""Unit tests for projecting extraction internals into the RunTrace (Slice 3).

Validates that `_record_extraction_trace` reads the extractor's internal trace
fields (`_extraction_tiers`, `_dom_skip_decision`, `_field_sources`) and feeds
them into the RunTrace observe-only, including the no-op path for a
SimpleNamespace context without a trace.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.observability.run_trace import RunTrace
from app.services.pipeline.extraction_loop import _record_extraction_trace

pytestmark = pytest.mark.unit


def _context(trace: RunTrace | None) -> SimpleNamespace:
    return SimpleNamespace(trace=trace)


def _detail_record() -> dict:
    return {
        "url": "https://example.com/p/widget",
        "price": "49.99",
        "title": "Widget",
        "variants": [{"size": "M"}],
        "_extraction_tiers": {
            "completed": ["authoritative", "structured_data", "js_state", "dom"],
            "current": "dom",
        },
        "_dom_skip_decision": {
            "dom_skipped": False,
            "confidence": 0.55,
            "threshold": 0.7,
            "reason": "confidence_below_threshold",
        },
        "_field_sources": {
            "price": ["js_state"],
            "title": ["dom_h1"],
            "variants": ["dom_selector"],
        },
    }


def test_projects_completed_tiers_and_skip_decision():
    trace = RunTrace(
        run_id=1,
        url="https://example.com/p/widget",
        surface="ecommerce_detail",
        requested_fields=["price", "variants"],
    )
    _record_extraction_trace(_context(trace), [_detail_record()])
    payload = trace.to_dict(flagged=True)["extraction"]
    assert payload["completed_tiers"] == [
        "authoritative",
        "structured_data",
        "js_state",
        "dom",
    ]
    assert payload["dom_skipped"] is False
    assert payload["skip_decision"]["dom_completion_reason"] == "confidence_below_threshold"
    assert payload["skip_decision"]["confidence"] == pytest.approx(0.55)


def test_projects_high_value_field_winning_sources_only():
    trace = RunTrace(
        run_id=1,
        url="https://example.com/p/widget",
        surface="ecommerce_detail",
        requested_fields=["price", "variants"],
    )
    _record_extraction_trace(_context(trace), [_detail_record()])
    provenance = {
        entry["field"]: entry
        for entry in trace.to_dict(flagged=True)["extraction"]["field_provenance"]
    }
    # high-value fields recorded with their winning source
    assert provenance["price"]["winning_source"] == "js_state"
    assert provenance["variants"]["winning_source"] == "dom_selector"
    # title is a default canonical high-value field for ecommerce detail
    assert "title" in provenance


def test_skipped_dom_reflected_when_dom_absent_from_completed():
    record = _detail_record()
    record["_extraction_tiers"]["completed"] = [
        "authoritative",
        "structured_data",
        "js_state",
    ]
    record["_dom_skip_decision"] = {
        "dom_skipped": True,
        "confidence": 0.92,
        "threshold": 0.7,
        "reason": "confidence_cleared_no_dom_completion_needed",
    }
    trace = RunTrace(
        run_id=1,
        url="https://example.com/p/widget",
        surface="ecommerce_detail",
        requested_fields=["price"],
    )
    _record_extraction_trace(_context(trace), [record])
    extraction = trace.to_dict(flagged=True)["extraction"]
    assert "dom" not in extraction["completed_tiers"]
    assert extraction["dom_skipped"] is True


def test_noop_when_context_has_no_trace():
    ctx = SimpleNamespace()  # no .trace attribute
    # must not raise
    _record_extraction_trace(ctx, [_detail_record()])


def test_noop_when_no_records():
    trace = RunTrace(run_id=1, url="https://e.com", surface="ecommerce_detail")
    _record_extraction_trace(_context(trace), [])
    assert trace.to_dict()["extraction"]["completed_tiers"] == []
