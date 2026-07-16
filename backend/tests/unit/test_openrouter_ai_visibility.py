"""OpenRouter native-search request and normalized response behavior."""

from __future__ import annotations

import pytest

from app.ai_visibility.contracts import AnswerEngineRequest
from app.ai_visibility.openrouter import _native_model_matches_surface, _payload
from app.ai_visibility.openrouter_parser import parse_openrouter_completion

pytestmark = pytest.mark.unit


def test_payload_requests_native_search_and_country_location() -> None:
    request = AnswerEngineRequest(
        prompt="cheap baby clothes",
        system_instruction="Answer for Australia.",
        model="openai/gpt-5.4",
        timeout_seconds=30,
    )
    payload = _payload(request, country_code="AU")
    assert payload["messages"] == [
        {"role": "system", "content": "Answer for Australia."},
        {"role": "user", "content": "cheap baby clothes"},
    ]
    tool = payload["tools"][0]
    assert tool["type"] == "openrouter:web_search"
    assert tool["parameters"]["engine"] == "native"
    assert tool["parameters"]["user_location"]["country"] == "AU"


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        ("openrouter_openai", "openai/gpt-5.4", True),
        ("openrouter_openai", "openai/gpt-4o", False),
        ("openrouter_anthropic", "anthropic/claude-sonnet-4.6", True),
        ("openrouter_anthropic", "openai/gpt-5.4", False),
    ],
)
def test_native_surface_model_allowlist(
    provider: str, model: str, expected: bool
) -> None:
    assert _native_model_matches_surface(provider, model) is expected


def test_parser_extracts_annotations_and_search_count_without_fake_queries() -> None:
    payload = {
        "id": "gen-1",
        "model": "openai/gpt-5.4",
        "provider": "OpenAI",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Best&Less is one option.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url_citation": {
                                "url": "https://www.bestandless.com.au/baby",
                                "title": "Best&Less baby clothing",
                                "start_index": 0,
                                "end_index": 9,
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 30,
            "total_tokens": 50,
            "server_tool_use": {"web_search_requests": 2},
        },
    }
    result = parse_openrouter_completion(
        payload,
        provider="openrouter_openai",
        requested_model="openai/gpt-5.4",
        latency_ms=10,
    )
    assert result.search_used is True
    assert len(result.search_events) == 2
    assert all(event.query == "" for event in result.search_events)
    assert result.citations[0].domain == "bestandless.com.au"
    assert result.provider_metadata["query_text_available"] is False
    assert result.provider_metadata["routed_provider"] == "OpenAI"


def _completion_payload(usage: dict, *, with_citation: bool) -> dict:
    annotations = (
        [
            {
                "type": "url_citation",
                "url_citation": {
                    "url": "https://www.bestandless.com.au/baby",
                    "title": "Best&Less baby clothing",
                },
            }
        ]
        if with_citation
        else []
    )
    return {
        "id": "gen-2",
        "model": "openai/gpt-5.4",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Best&Less is one option.",
                    "annotations": annotations,
                },
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 30,
            "total_tokens": 50,
            **usage,
        },
    }


def test_search_count_reads_server_tool_use_details_key() -> None:
    # OpenRouter reports the native web-search count under this key in practice;
    # the parser must not silently treat it as zero searches.
    result = parse_openrouter_completion(
        _completion_payload(
            {"server_tool_use_details": {"web_search_requests": 3}}, with_citation=True
        ),
        provider="openrouter_openai",
        requested_model="openai/gpt-5.4",
        latency_ms=10,
    )
    assert result.usage["web_search_requests"] == 3
    assert result.search_used is True
    assert len(result.search_events) == 3


def test_search_used_falls_back_to_citation_presence() -> None:
    # No counter reported, but url_citation annotations prove search ran.
    result = parse_openrouter_completion(
        _completion_payload({}, with_citation=True),
        provider="openrouter_openai",
        requested_model="openai/gpt-5.4",
        latency_ms=10,
    )
    assert result.usage["web_search_requests"] == 0
    assert result.search_used is True


def test_search_used_false_without_search_or_citations() -> None:
    result = parse_openrouter_completion(
        _completion_payload({}, with_citation=False),
        provider="openrouter_openai",
        requested_model="openai/gpt-5.4",
        latency_ms=10,
    )
    assert result.search_used is False
