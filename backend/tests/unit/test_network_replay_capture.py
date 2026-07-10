from __future__ import annotations

import json
from types import SimpleNamespace

from app.acquisition.browser_capture import _safe_replay_request_json


def _request(payload: object) -> SimpleNamespace:
    return SimpleNamespace(
        method="POST",
        headers={"content-type": "application/json"},
        post_data=json.dumps(payload),
    )


def test_graphql_query_request_is_captured_without_headers() -> None:
    captured = _safe_replay_request_json(
        _request(
            {
                "operationName": "Product",
                "variables": {"sku": "ABC-123"},
                "query": "query Product($sku: String!) { product(sku: $sku) { name } }",
            }
        ),
        endpoint_type="graphql",
    )

    assert captured == {
        "operationName": "Product",
        "variables": {"sku": "ABC-123"},
        "query": "query Product($sku: String!) { product(sku: $sku) { name } }",
    }


def test_graphql_mutation_or_sensitive_variables_are_never_captured() -> None:
    assert (
        _safe_replay_request_json(
            _request({"query": "mutation Add { addToCart { id } }"}),
            endpoint_type="graphql",
        )
        is None
    )


def test_generic_json_post_template_is_captured_for_non_graphql_job_apis() -> None:
    captured = _safe_replay_request_json(
        _request({"page": 1, "sort": "postedDateDesc", "filters": []}),
        endpoint_type="generic_json",
    )

    assert captured == {"page": 1, "sort": "postedDateDesc", "filters": []}
    assert (
        _safe_replay_request_json(
            _request(
                {"query": "query Q { me { id } }", "variables": {"email": "x@y.test"}}
            ),
            endpoint_type="graphql",
        )
        is None
    )
