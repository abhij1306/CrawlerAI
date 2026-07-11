"""Slice 1: Gemini Interactions parser against the real saved fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai_visibility.gemini_parser import parse_interaction, sanitize_metadata

pytestmark = pytest.mark.unit

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "gemini_interactions_grounded.json"
)


def _load() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _parse(payload: dict):
    return parse_interaction(
        payload, provider="gemini", model="gemini-2.5-flash", latency_ms=1234
    )


def test_fixture_extracts_queries_and_citations() -> None:
    result = _parse(_load())
    # The live probe returned exactly 2 fanout queries and 18 citations.
    assert result.search_used is True
    assert [e.query for e in result.search_events] == [
        "cheapest school uniforms Australia",
        "affordable school uniforms online Australia",
    ]
    assert len(result.citations) == 18
    assert result.answer_text
    assert result.latency_ms == 1234


def test_citation_domain_comes_from_title_not_redirect_url() -> None:
    result = _parse(_load())
    first = result.citations[0]
    assert "grounding-api-redirect" in first.url  # redirect, not publisher
    assert first.domain == "beanstalkmums.com.au"  # publisher from title
    domains = {c.domain for c in result.citations}
    assert "bestandless.com.au" in domains
    assert {"kmart.com.au", "target.com.au", "bigw.com.au"} <= domains


def test_citation_offsets_slice_answer_text() -> None:
    result = _parse(_load())
    for citation in result.citations:
        if citation.start_index is not None and citation.end_index is not None:
            assert 0 <= citation.start_index < citation.end_index
            assert citation.end_index <= len(result.answer_text)
            assert citation.cited_text


def test_camelcase_offsets_accepted() -> None:
    payload = {
        "model": "gemini-2.5-flash",
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": "Kmart is a good option for uniforms.",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc",
                                "title": "kmart.com.au",
                                "startIndex": 0,
                                "endIndex": 5,
                            }
                        ],
                    }
                ],
            },
            {
                "type": "google_search_call",
                "arguments": {"queries": ["kmart uniforms"]},
            },
        ],
    }
    result = _parse(payload)
    assert result.citations[0].start_index == 0
    assert result.citations[0].end_index == 5
    assert result.citations[0].cited_text == "Kmart"


def test_out_of_range_offsets_are_dropped_to_none() -> None:
    payload = {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": "short",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://x/redirect",
                                "title": "example.com",
                                "start_index": 100,
                                "end_index": 200,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    result = _parse(payload)
    citation = result.citations[0]
    assert citation.start_index is None
    assert citation.end_index is None
    assert citation.cited_text == ""
    assert citation.domain == "example.com"


def test_search_not_used_is_valid_result() -> None:
    payload = {
        "model": "gemini-2.5-flash",
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {"type": "text", "text": "From memory only.", "annotations": []}
                ],
            }
        ],
    }
    result = _parse(payload)
    assert result.search_used is False
    assert result.search_events == ()
    assert result.answer_text == "From memory only."


def test_sanitize_metadata_strips_signatures_and_thoughts() -> None:
    payload = _load()
    meta = sanitize_metadata(payload)
    blob = json.dumps(meta)
    assert "signature" not in blob
    assert meta["status"] == "completed"
    assert "usage" in meta
    assert "thought" not in meta["step_types"]
    assert meta["evidence_steps"]
    assert any(step["type"] == "model_output" for step in meta["evidence_steps"])


def test_search_call_grouping_is_preserved() -> None:
    payload = {
        "steps": [
            {
                "type": "google_search_call",
                "id": "call-7",
                "arguments": {"queries": ["first query", "second query"]},
            }
        ]
    }
    result = _parse(payload)
    assert [event.call_id for event in result.search_events] == ["call-7", "call-7"]
    assert [event.query_sequence for event in result.search_events] == [0, 1]


def test_direct_url_citation_shape_keeps_publisher_host() -> None:
    payload = {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": "Best&Less has uniforms.",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://www.bestandless.com.au/schoolwear",
                                "title": "Schoolwear",
                                "start_index": 0,
                                "end_index": 9,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    result = _parse(payload)
    assert result.citations[0].url == "https://www.bestandless.com.au/schoolwear"


def test_parser_drops_thought_steps_from_answer() -> None:
    payload = {
        "steps": [
            {"type": "thought", "signature": "SECRET", "content": [{"text": "hidden"}]},
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "visible", "annotations": []}],
            },
        ]
    }
    result = _parse(payload)
    assert result.answer_text == "visible"
    assert "hidden" not in result.answer_text
