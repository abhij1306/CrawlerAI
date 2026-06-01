"""Unit tests for the RunTrace collector (Slice 1).

Pure, no DB: validate the trace contract, no-op behavior when disabled, tiering,
high-value field gating, and bounded candidate capture.
"""

from __future__ import annotations

import pytest

from app.services.config import observability as obs_config
from app.services.observability.run_trace import (
    NullRunTrace,
    RunTrace,
    high_value_fields,
    new_run_trace,
)

pytestmark = pytest.mark.unit


def _trace(**kwargs) -> RunTrace:
    base = {
        "run_id": 7,
        "url": "https://example.com/p/widget",
        "surface": "ecommerce_detail",
        "requested_fields": ["price", "variants"],
    }
    base.update(kwargs)
    return RunTrace(**base)


def _field_provenance(trace: RunTrace, field: str):
    for entry in trace.to_dict(flagged=True)["extraction"]["field_provenance"]:
        if entry["field"] == field:
            return entry
    raise AssertionError(f"Field provenance not found: {field}")


def test_high_value_fields_unions_requested_and_defaults():
    fields = high_value_fields("ecommerce_detail", ["variants"])
    assert "variants" in fields
    # default canonical repair targets for ecommerce detail include price/title/image
    assert "price" in fields
    assert "title" in fields


def test_high_value_fields_falls_back_to_floor_when_empty():
    fields = high_value_fields("", None)
    assert tuple(fields) == obs_config.HIGH_VALUE_FIELD_FLOOR


def test_acquire_events_are_ordered_with_sequence():
    trace = _trace()
    trace.record_acquire_event("navigation", detail={"strategy": "domcontentloaded"})
    trace.record_acquire_event("readiness_probe", detail={"is_ready": True})
    payload = trace.to_dict()
    timeline = payload["acquire_timeline"]
    assert [e["kind"] for e in timeline] == ["navigation", "readiness_probe"]
    assert [e["sequence"] for e in timeline] == [1, 2]


def test_skip_dom_decision_is_captured():
    trace = _trace()
    trace.record_skip_dom_decision(
        dom_skipped=True,
        confidence=0.82,
        threshold=0.7,
        dom_completion_reason="confidence_above_threshold",
    )
    extraction = trace.to_dict(flagged=True)["extraction"]
    assert extraction["dom_skipped"] is True
    assert extraction["skip_decision"]["confidence"] == pytest.approx(0.82)
    assert extraction["skip_decision"]["threshold"] == pytest.approx(0.7)


def test_extraction_rejection_reason_is_captured():
    trace = _trace()
    trace.record_extraction_rejection("detail_identity_mismatch")

    extraction = trace.to_dict(flagged=True)["extraction"]

    assert extraction["rejection_reason"] == "detail_identity_mismatch"


def test_field_candidate_only_records_high_value_fields():
    trace = _trace(requested_fields=["price"])
    trace.record_field_candidate(
        "price", source="js_state", won=True, value_preview="49.99"
    )
    trace.record_field_candidate(
        "footer_link", source="dom_selector", won=False, value_preview="noise"
    )
    provenance = {
        entry["field"]: entry
        for entry in trace.to_dict(flagged=True)["extraction"]["field_provenance"]
    }
    assert "price" in provenance
    assert "footer_link" not in provenance
    assert provenance["price"]["winning_source"] == "js_state"


def test_detail_diagnostic_fields_are_traced_when_not_requested():
    trace = _trace(requested_fields=["price"])
    trace.record_field_candidate(
        "variants", source="embedded_json", won=True, value_preview=""
    )
    trace.record_field_state(
        "variants", value=None, candidate_sources=["embedded_json"]
    )

    payload = trace.to_dict()
    provenance = {
        entry["field"]: entry
        for entry in payload["extraction"]["field_provenance"]
    }

    assert "variants" in payload["diagnostic_fields"]
    assert provenance["variants"]["winning_source"] == "embedded_json"
    assert provenance["variants"]["present"] is False
    assert provenance["variants"]["note"] == "candidate_source_without_public_value"


def test_candidate_losers_are_bounded_per_field():
    trace = _trace(requested_fields=["price"])
    trace.record_field_candidate("price", source="js_state", won=True)
    for i in range(obs_config.MAX_CANDIDATE_LOSERS_PER_FIELD + 5):
        trace.record_field_candidate(
            "price",
            source=f"dom_{i}",
            won=False,
            reject_reason="lower_priority",
        )
    price = _field_provenance(trace, "price")
    # winner + capped losers
    assert len(price["candidates"]) == obs_config.MAX_CANDIDATE_LOSERS_PER_FIELD + 1


def test_repeated_winning_candidates_are_ignored():
    trace = _trace(requested_fields=["price"])
    trace.record_field_candidate("price", source="adapter", won=True)
    trace.record_field_candidate("price", source="dom", won=True)

    price = _field_provenance(trace, "price")
    assert price["winning_source"] == "adapter"
    assert [candidate["source"] for candidate in price["candidates"]] == ["adapter"]


def test_full_tier_on_non_success_verdict():
    trace = _trace(requested_fields=["price"])
    trace.record_field_candidate("price", source="dom", won=True, value_preview="5")
    trace.record_field_candidate(
        "price", source="js_state", won=False, reject_reason="lost"
    )
    trace.record_verdict("empty")
    payload = trace.to_dict()
    assert payload["tier"] == obs_config.TRACE_TIER_FULL
    price = payload["extraction"]["field_provenance"][0]
    # full tier keeps the losing candidate list
    assert any(not c["won"] for c in price["candidates"])


def test_light_tier_on_success_drops_losers():
    trace = _trace(requested_fields=["price"])
    trace.record_field_candidate("price", source="dom", won=True, value_preview="5")
    trace.record_field_candidate(
        "price", source="js_state", won=False, reject_reason="lost"
    )
    trace.record_verdict("success")
    payload = trace.to_dict()
    assert payload["tier"] == obs_config.TRACE_TIER_LIGHT
    price = payload["extraction"]["field_provenance"][0]
    assert "candidates" not in price
    assert price["winning_source"] == "dom"


def test_flag_forces_full_tier_even_on_success():
    trace = _trace(requested_fields=["price"])
    trace.record_field_candidate("price", source="dom", won=True)
    trace.record_field_candidate("price", source="js_state", won=False)
    trace.record_verdict("success")
    payload = trace.to_dict(flagged=True)
    assert payload["tier"] == obs_config.TRACE_TIER_FULL


def test_null_trace_is_noop_and_serializes_empty_timeline():
    null = NullRunTrace()
    null.record_acquire_event("navigation")
    null.record_field_candidate("price", source="dom", won=True)
    null.record_verdict("empty")
    payload = null.to_dict()
    assert payload["acquire_timeline"] == []
    assert payload["extraction"]["completed_tiers"] == []


def test_factory_returns_null_when_disabled(monkeypatch):
    monkeypatch.setattr(obs_config, "RUN_TRACE_ENABLED", False)
    trace = new_run_trace(run_id=1, url="https://e.com", surface="ecommerce_detail")
    assert isinstance(trace, NullRunTrace)


def test_factory_returns_real_trace_when_enabled(monkeypatch):
    monkeypatch.setattr(obs_config, "RUN_TRACE_ENABLED", True)
    trace = new_run_trace(run_id=1, url="https://e.com", surface="ecommerce_detail")
    assert isinstance(trace, RunTrace)
    assert not isinstance(trace, NullRunTrace)
