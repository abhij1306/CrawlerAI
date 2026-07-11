"""Native Anthropic web-search request and normalized response behavior."""

from __future__ import annotations

import pytest

from app.ai_visibility.anthropic import _payload, _raise_for_search_error
from app.ai_visibility.anthropic_parser import parse_anthropic_message
from app.ai_visibility.contracts import AnswerEngineRequest
from app.ai_visibility.gemini import AiVisibilityProviderError
from app.ai_visibility.runner import _dedup_citations

pytestmark = pytest.mark.unit


def test_dedup_citations_collapses_same_url_and_renumbers() -> None:
    # Providers cite one source per supported text span; the same URL repeats.
    raw = [
        {"ordinal": 0, "redirect_url": "https://savvysupporter.com.au/", "cited_text": "first"},
        {"ordinal": 1, "redirect_url": "https://nrlshop.com/", "cited_text": "n"},
        {"ordinal": 2, "redirect_url": "https://savvysupporter.com.au/", "cited_text": "second"},
        {"ordinal": 3, "redirect_url": "https://savvysupporter.com.au/", "cited_text": "third"},
    ]
    deduped = _dedup_citations(raw)
    urls = [c["redirect_url"] for c in deduped]
    assert urls == ["https://savvysupporter.com.au/", "https://nrlshop.com/"]
    # First occurrence's cited_text is kept; ordinals are dense.
    assert deduped[0]["cited_text"] == "first"
    assert [c["ordinal"] for c in deduped] == [0, 1]


def test_dedup_citations_keeps_urlless_by_domain_title() -> None:
    raw = [
        {"ordinal": 0, "redirect_url": "", "domain": "a.com", "title": "A"},
        {"ordinal": 1, "redirect_url": "", "domain": "b.com", "title": "B"},
        {"ordinal": 2, "redirect_url": "", "domain": "a.com", "title": "A"},
    ]
    deduped = _dedup_citations(raw)
    assert len(deduped) == 2


def test_payload_uses_native_web_search_and_top_level_system() -> None:
    request = AnswerEngineRequest(
        prompt="cheap baby clothes",
        system_instruction="Answer for Australia.",
        model="claude-sonnet-4-6",
        timeout_seconds=30,
    )
    payload = _payload(request, country_code="AU")
    # System instruction is a top-level field, not a chat message.
    assert payload["system"] == "Answer for Australia."
    assert payload["messages"] == [{"role": "user", "content": "cheap baby clothes"}]
    tool = payload["tools"][0]
    assert tool["type"] == "web_search_20250305"
    assert tool["name"] == "web_search"
    assert tool["user_location"] == {"type": "approximate", "country": "AU"}


def test_payload_omits_system_and_location_when_absent() -> None:
    request = AnswerEngineRequest(
        prompt="school uniforms",
        system_instruction="",
        model="claude-sonnet-4-6",
        timeout_seconds=30,
    )
    payload = _payload(request, country_code="")
    assert "system" not in payload
    assert "user_location" not in payload["tools"][0]


def test_parser_extracts_answer_citations_and_real_query() -> None:
    payload = {
        "id": "msg_1",
        "type": "message",
        "model": "claude-sonnet-4-6",
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": "Let me search."},
            {
                "type": "server_tool_use",
                "id": "srvtoolu_1",
                "name": "web_search",
                "input": {"query": "affordable baby clothes australia"},
            },
            {
                "type": "web_search_tool_result",
                "tool_use_id": "srvtoolu_1",
                "content": [
                    {
                        "type": "web_search_result",
                        "url": "https://www.bestandless.com.au/baby",
                        "title": "Best&Less baby",
                    }
                ],
            },
            {
                "type": "text",
                "text": "Best&Less is a great option.",
                "citations": [
                    {
                        "type": "web_search_result_location",
                        "url": "https://www.bestandless.com.au/baby",
                        "title": "Best&Less baby",
                        "cited_text": "Best&Less baby clothing from $5",
                    }
                ],
            },
        ],
        "usage": {
            "input_tokens": 40,
            "output_tokens": 60,
            "server_tool_use": {"web_search_requests": 1},
        },
    }
    result = parse_anthropic_message(
        payload,
        provider="anthropic",
        requested_model="claude-sonnet-4-6",
        latency_ms=12,
    )
    assert result.answer_text == "Let me search.\n\nBest&Less is a great option."
    assert result.search_used is True
    assert len(result.search_events) == 1
    # Unlike OpenRouter, Anthropic surfaces the real query text.
    assert result.search_events[0].query == "affordable baby clothes australia"
    assert result.provider_metadata["query_text_available"] is True
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.domain == "bestandless.com.au"
    assert citation.cited_text == "Best&Less baby clothing from $5"
    assert citation.start_index is None
    assert result.usage["total_input_tokens"] == 40
    assert result.usage["total_output_tokens"] == 60
    assert result.usage["total_tokens"] == 100
    assert result.usage["web_search_requests"] == 1


def test_search_error_raises_only_for_retryable_codes() -> None:
    rate_limited = {
        "content": [
            {
                "type": "web_search_tool_result",
                "tool_use_id": "srvtoolu_1",
                "content": {
                    "type": "web_search_tool_result_error",
                    "error_code": "too_many_requests",
                },
            }
        ]
    }
    with pytest.raises(AiVisibilityProviderError) as excinfo:
        _raise_for_search_error(rate_limited)
    assert excinfo.value.retryable is True

    # max_uses_exceeded is non-fatal: the partial answer should still parse.
    capped = {
        "content": [
            {
                "type": "web_search_tool_result",
                "tool_use_id": "srvtoolu_1",
                "content": {
                    "type": "web_search_tool_result_error",
                    "error_code": "max_uses_exceeded",
                },
            }
        ]
    }
    _raise_for_search_error(capped)  # must not raise
