from __future__ import annotations

import pytest
import httpx

from app.services.config.ucp_audit import (
    D_UCP1_ID,
    D_UCP3_ID,
    D_UCP4_ID,
    D_UCP5_ID,
    D_UCP6_ID,
    FINDING_MANIFEST_INVALID,
    FINDING_SIGNING_KEYS_MISSING,
    FINDING_TRANSPORT_NEGOTIATION_INCOMPLETE,
    FINDING_TRANSPORT_UNREACHABLE,
)
from app.services.ucp_audit import protocol_checks
from app.services.ucp_audit.protocol_checks import (
    build_protocol_dimensions,
    probe_transports,
)
from app.services.ucp_audit.types import (
    UCPFinding,
    UCPManifestResult,
    UCPSchemaProbe,
    UCPTransportProbe,
)


class DummyAsyncClient:
    def __init__(self, *, options_resp=None, get_resp=None, post_resp=None):
        self.options_resp = options_resp
        self.get_resp = get_resp
        self.post_resp = post_resp
        self.post_headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def options(self, endpoint: str, *, headers: dict):
        del endpoint, headers
        return self.options_resp

    async def get(self, endpoint: str, *, headers: dict):
        del endpoint, headers
        return self.get_resp

    async def post(self, endpoint: str, *, json: dict, headers: dict):
        del endpoint, json
        self.post_headers = headers
        return self.post_resp


def _response(method: str, url: str, status: int, payload: dict, headers: dict | None = None):
    return httpx.Response(
        status,
        json=payload,
        headers=headers or {},
        request=httpx.Request(method, url),
    )


def _dimension(dimensions, dimension_id: str):
    for item in dimensions:
        if item.dimension_id == dimension_id:
            return item
    raise AssertionError(f"Missing dimension {dimension_id}")


def _finding(findings, code: str):
    for item in findings:
        if item.code == code:
            return item
    raise AssertionError(f"Missing finding {code}")


@pytest.mark.component
def test_transport_profile_required_scores_partial() -> None:
    manifest = UCPManifestResult(
        manifest_found=True,
        manifest_valid=True,
        services_declared=["dev.ucp.shopping"],
        transport_entries=[
            {
                "service": "dev.ucp.shopping",
                "transport": "mcp",
                "endpoint": "https://example.com/api/ucp/mcp",
            }
        ],
    )
    dimensions = build_protocol_dimensions(
        manifest,
        [
            UCPTransportProbe(
                service="dev.ucp.shopping",
                transport="mcp",
                endpoint="https://example.com/api/ucp/mcp",
                reachable=True,
                negotiated=False,
                profile_required=True,
                status_code=422,
            )
        ],
        [],
    )

    transport = _dimension(dimensions, D_UCP3_ID)

    assert transport.score == 70
    assert transport.findings[0].code == FINDING_TRANSPORT_NEGOTIATION_INCOMPLETE


@pytest.mark.component
def test_profile_required_scans_error_data() -> None:
    assert protocol_checks._profile_required(
        {
            "error": {
                "code": -32001,
                "message": "ucp discovery failed",
                "data": {
                    "code": "invalid_profile_url",
                    "content": "Unable to fetch agent profile: Missing profile uri",
                },
            }
        }
    )
    assert protocol_checks._profile_required(
        {"error": {"code": -32001, "message": "profile missing"}}
    )
    assert not protocol_checks._profile_required(
        {"error": {"code": -32001, "message": "internal error"}}
    )
    assert not protocol_checks._profile_required({})


@pytest.mark.component
def test_discovery_dimension_splits_signing_keys_from_manifest_validity() -> None:
    valid_missing_keys = UCPManifestResult(
        manifest_found=True,
        manifest_valid=True,
        final_url="https://example.com/.well-known/ucp",
        response_headers={"cache-control": "public, max-age=300"},
        signing_keys_errors=["Missing required array: signing_keys"],
    )
    invalid_structure = UCPManifestResult(
        manifest_found=True,
        manifest_valid=False,
        final_url="https://example.com/.well-known/ucp",
        response_headers={"cache-control": "public, max-age=300"},
        errors=["Missing required object: ucp.services"],
    )

    dimensions = build_protocol_dimensions(valid_missing_keys, [], [])
    discovery = _dimension(dimensions, D_UCP1_ID)

    assert discovery.score == 80
    assert [item.code for item in discovery.findings] == [FINDING_SIGNING_KEYS_MISSING]

    dimensions = build_protocol_dimensions(invalid_structure, [], [])
    discovery = _dimension(dimensions, D_UCP1_ID)

    assert discovery.score == 40
    assert discovery.findings[0].code == FINDING_MANIFEST_INVALID


@pytest.mark.component
def test_status_allows_warnings_at_high_score() -> None:
    finding = UCPFinding(
        code="warning",
        dimension_id=D_UCP3_ID,
        severity="warning",
    )

    assert protocol_checks._status(100, [finding]) == "warning"
    assert protocol_checks._status(100, []) == "pass"
    assert protocol_checks._status(80, []) == "pass"


@pytest.mark.asyncio
@pytest.mark.component
async def test_probe_transports_treats_embedded_schema_as_schema_dependent() -> None:
    manifest = UCPManifestResult(
        transport_entries=[
            {
                "service": "dev.ucp.shopping",
                "transport": "embedded",
                "schema": "https://ucp.dev/embedded.openrpc.json",
            }
        ]
    )

    probes = await probe_transports(manifest)

    assert probes[0].transport == "embedded"
    assert probes[0].reachable is False
    assert probes[0].negotiated is False
    assert probes[0].schema_url == "https://ucp.dev/embedded.openrpc.json"


@pytest.mark.component
def test_contract_dimensions_validate_payload_schema_groups() -> None:
    manifest = UCPManifestResult(
        manifest_found=True,
        manifest_valid=True,
        services_declared=["dev.ucp.shopping"],
        capabilities_declared=[
            "dev.ucp.shopping.catalog.search",
            "dev.ucp.shopping.catalog.lookup",
            "dev.ucp.shopping.cart",
            "dev.ucp.shopping.checkout",
            "dev.ucp.shopping.order",
            "dev.ucp.shopping.fulfillment",
            "dev.ucp.shopping.discount",
        ],
        payment_handlers=["com.google.pay"],
    )
    schema_probes = [
        UCPSchemaProbe(
            url="https://ucp.dev/catalog_search.json",
            reachable=True,
            valid_json=True,
            schema_valid=True,
            field_results={
                "catalog": {
                    "product_id": True,
                    "title": True,
                    "price": True,
                    "currency": True,
                    "availability": True,
                }
            },
        ),
        UCPSchemaProbe(
            url="https://ucp.dev/cart.json",
            reachable=True,
            valid_json=True,
            schema_valid=True,
            field_results={
                "cart_checkout": {
                    "cart_id": True,
                    "line_items": True,
                    "total": True,
                    "currency": True,
                }
            },
        ),
        UCPSchemaProbe(
            url="https://ucp.dev/order.json",
            reachable=True,
            valid_json=True,
            schema_valid=True,
            field_results={
                "order_policy": {
                    "order_id": True,
                    "status": True,
                    "fulfillment": True,
                }
            },
        ),
    ]

    dimensions = build_protocol_dimensions(manifest, [], schema_probes)
    scores = {item.dimension_id: item.score for item in dimensions}

    assert scores[D_UCP4_ID] == 100
    assert scores[D_UCP5_ID] == 100
    assert scores[D_UCP6_ID] == 100


@pytest.mark.component
def test_transport_incomplete_uses_reachable_only_and_best_score() -> None:
    manifest = UCPManifestResult(
        manifest_found=True,
        manifest_valid=True,
        transport_entries=[
            {"service": "dev.ucp.shopping", "transport": "mcp", "endpoint": "https://a"},
            {"service": "dev.ucp.shopping", "transport": "mcp", "endpoint": "https://b"},
        ],
    )

    dimensions = build_protocol_dimensions(
        manifest,
        [
            UCPTransportProbe(
                service="dev.ucp.shopping",
                transport="mcp",
                endpoint="https://a",
                reachable=True,
                negotiated=True,
            ),
            UCPTransportProbe(
                service="dev.ucp.shopping",
                transport="mcp",
                endpoint="https://b",
                reachable=False,
                negotiated=False,
            ),
        ],
        [],
    )
    transport = _dimension(dimensions, D_UCP3_ID)

    assert transport.score == 100
    assert FINDING_TRANSPORT_NEGOTIATION_INCOMPLETE not in [
        item.code for item in transport.findings
    ]

    dimensions = build_protocol_dimensions(
        manifest,
        [
            UCPTransportProbe(
                service="dev.ucp.shopping",
                transport="mcp",
                endpoint="https://a",
                reachable=True,
                negotiated=True,
            ),
            UCPTransportProbe(
                service="dev.ucp.shopping",
                transport="mcp",
                endpoint="https://b",
                reachable=True,
                negotiated=False,
            ),
        ],
        [],
    )
    transport = _dimension(dimensions, D_UCP3_ID)

    finding = _finding(
        transport.findings,
        FINDING_TRANSPORT_NEGOTIATION_INCOMPLETE,
    )
    assert finding.evidence[0]["endpoint"] == "https://b"


@pytest.mark.component
def test_transport_unreachable_does_not_emit_negotiation_incomplete() -> None:
    manifest = UCPManifestResult(
        manifest_found=True,
        manifest_valid=True,
        transport_entries=[
            {"service": "dev.ucp.shopping", "transport": "mcp", "endpoint": "https://a"}
        ],
    )

    dimensions = build_protocol_dimensions(
        manifest,
        [
            UCPTransportProbe(
                service="dev.ucp.shopping",
                transport="mcp",
                endpoint="https://a",
                reachable=False,
                negotiated=False,
            )
        ],
        [],
    )
    transport = _dimension(dimensions, D_UCP3_ID)
    codes = [item.code for item in transport.findings]

    assert FINDING_TRANSPORT_UNREACHABLE in codes
    assert FINDING_TRANSPORT_NEGOTIATION_INCOMPLETE not in codes


@pytest.mark.component
def test_transport_score_uses_best_with_breadth_bonus() -> None:
    manifest = UCPManifestResult(
        manifest_found=True,
        manifest_valid=True,
        transport_entries=[
            {"service": "dev.ucp.shopping", "transport": "mcp", "endpoint": "https://a"},
            {"service": "dev.ucp.shopping", "transport": "mcp", "endpoint": "https://b"},
        ],
    )

    dimensions = build_protocol_dimensions(
        manifest,
        [
            UCPTransportProbe(
                service="dev.ucp.shopping",
                transport="mcp",
                endpoint="https://a",
                reachable=True,
                profile_required=True,
            ),
            UCPTransportProbe(
                service="dev.ucp.shopping",
                transport="mcp",
                endpoint="https://b",
                reachable=True,
                profile_required=True,
            ),
        ],
        [],
    )
    transport = _dimension(dimensions, D_UCP3_ID)
    assert transport.score == 75

    dimensions = build_protocol_dimensions(
        manifest,
        [
            UCPTransportProbe(
                service="dev.ucp.shopping",
                transport="mcp",
                endpoint="https://a",
                reachable=True,
            )
        ],
        [],
    )
    transport = _dimension(dimensions, D_UCP3_ID)
    assert transport.score == 50


@pytest.mark.component
def test_schema_url_keywords_do_not_score_without_fields() -> None:
    manifest = UCPManifestResult(
        manifest_found=True,
        manifest_valid=True,
        services_declared=["dev.ucp.shopping"],
        capabilities_declared=[
            "dev.ucp.shopping.catalog.search",
            "dev.ucp.shopping.catalog.lookup",
        ],
    )
    schema_probes = [
        UCPSchemaProbe(
            url="https://ucp.dev/catalog_search.json",
            reachable=True,
            valid_json=True,
            schema_valid=True,
            title="Catalog Search",
            field_results={"catalog": {"product_id": False, "title": False, "price": False, "currency": False, "availability": False}},
        )
    ]

    dimensions = build_protocol_dimensions(manifest, [], schema_probes)
    scores = {item.dimension_id: item.score for item in dimensions}

    assert scores[D_UCP4_ID] == 60


@pytest.mark.component
def test_schema_contains_field_resolves_local_refs() -> None:
    schema = {
        "properties": {"items": {"$ref": "#/components/schemas/Product"}},
        "components": {
            "schemas": {
                "Product": {
                    "properties": {
                        "product_id": {},
                    }
                }
            }
        },
    }

    assert protocol_checks._schema_contains_field(schema, "product_id", root=schema)
    assert not protocol_checks._schema_contains_field(
        {"$ref": "https://example.com/schema.json"},
        "product_id",
        root=schema,
    )


@pytest.mark.component
def test_schema_contains_field_resolves_chained_refs_in_composed_schemas() -> None:
    schema = {
        "allOf": [{"$ref": "#/components/schemas/ProductEnvelope"}],
        "components": {
            "schemas": {
                "ProductEnvelope": {
                    "allOf": [{"$ref": "#/components/schemas/Product"}]
                },
                "Product": {"properties": {"product_id": {}}},
            }
        },
    }

    assert protocol_checks._schema_contains_field(schema, "product_id", root=schema)


@pytest.mark.component
def test_schema_groups_detect_monolithic_shopping_schema() -> None:
    payload = {
        "properties": {
            "product_id": {},
            "cart_id": {},
            "order_id": {},
        }
    }
    groups = protocol_checks._schema_groups(
        "https://ucp.dev/2026-04-08/services/shopping/rest.openapi.json",
        payload,
    )

    assert groups == ["catalog", "cart_checkout", "order_policy"]
    assert "catalog" in protocol_checks._schema_groups(
        "https://example.com/api/schema.json",
        payload,
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_probe_rest_requires_ucp_shaped_get(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = "https://example.com/rest"
    fake_client = DummyAsyncClient(
        options_resp=_response("OPTIONS", endpoint, 200, {}, {"allow": "GET, OPTIONS"}),
        get_resp=_response("GET", endpoint, 200, {"error": "not found"}),
    )
    monkeypatch.setattr(
        "app.services.ucp_audit.protocol_checks.build_async_http_client",
        lambda **kwargs: fake_client,
    )

    probe = await protocol_checks._probe_rest(
        service="dev.ucp.shopping",
        endpoint=endpoint,
    )

    assert probe.negotiated is False

    fake_client.get_resp = _response("GET", endpoint, 200, {"capabilities": []})

    probe = await protocol_checks._probe_rest(
        service="dev.ucp.shopping",
        endpoint=endpoint,
    )

    assert probe.negotiated is False

    fake_client.get_resp = _response("GET", endpoint, 200, {"capabilities": ["catalog.search"]})

    probe = await protocol_checks._probe_rest(
        service="dev.ucp.shopping",
        endpoint=endpoint,
    )

    assert probe.negotiated is True

    fake_client.options_resp = _response("OPTIONS", endpoint, 500, {})
    fake_client.get_resp = _response(
        "GET",
        endpoint,
        200,
        {"capabilities": ["catalog.search"]},
    )

    probe = await protocol_checks._probe_rest(
        service="dev.ucp.shopping",
        endpoint=endpoint,
    )

    assert probe.reachable is True
    assert probe.negotiated is True
    assert probe.status_code == 200


@pytest.mark.asyncio
@pytest.mark.component
async def test_probe_mcp_sends_ucp_agent_header(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = "https://example.com/mcp"
    fake_client = DummyAsyncClient(
        post_resp=_response(
            "POST",
            endpoint,
            200,
            {
                "jsonrpc": "2.0",
                "id": "ucp-audit-tools-list",
                "result": {"tools": [{"name": "catalog", "inputSchema": {}}]},
            },
        )
    )
    monkeypatch.setattr(
        "app.services.ucp_audit.protocol_checks.build_async_http_client",
        lambda **kwargs: fake_client,
    )

    await protocol_checks._probe_mcp(service="dev.ucp.shopping", endpoint=endpoint)

    assert "UCP-Agent" in fake_client.post_headers


@pytest.mark.component
def test_summarize_tool_schemas_redacts_raw_payload_fields() -> None:
    summaries = protocol_checks._summarize_tool_schemas(
        [
            {
                "name": "catalog.search",
                "type": "function",
                "description": "internal prompt text",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "$defs": {"query": {"type": "string"}},
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {"items": {"type": "array"}},
                },
            }
        ]
    )

    assert len(summaries) == 1
    assert summaries[0] == {
        "name": "catalog.search",
        "type": "function",
        "schema_size": summaries[0]["schema_size"],
        "input_schema": {
            "valid": True,
            "type": "object",
            "property_count": 1,
            "required_count": 1,
            "has_items": False,
            "has_refs": True,
            "has_composition": False,
        },
        "output_schema": {
            "valid": True,
            "type": "object",
            "property_count": 1,
            "required_count": 0,
            "has_items": False,
            "has_refs": False,
            "has_composition": False,
        },
        "redacted_field_count": 1,
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_probe_mcp_persists_redacted_tool_schema_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = "https://example.com/mcp"
    fake_client = DummyAsyncClient(
        post_resp=_response(
            "POST",
            endpoint,
            200,
            {
                "jsonrpc": "2.0",
                "id": "ucp-audit-tools-list",
                "result": {
                    "tools": [
                        {
                            "name": "catalog",
                            "type": "function",
                            "description": "secret internal text",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"sku": {"type": "string"}},
                                "required": ["sku"],
                            },
                        }
                    ]
                },
            },
        )
    )
    monkeypatch.setattr(
        "app.services.ucp_audit.protocol_checks.build_async_http_client",
        lambda **kwargs: fake_client,
    )

    probe = await protocol_checks._probe_mcp(service="dev.ucp.shopping", endpoint=endpoint)

    assert probe.tool_names == ["catalog"]
    assert probe.tool_schemas == [
        {
            "name": "catalog",
            "type": "function",
            "schema_size": probe.tool_schemas[0]["schema_size"],
            "input_schema": {
                "valid": True,
                "type": "object",
                "property_count": 1,
                "required_count": 1,
                "has_items": False,
                "has_refs": False,
                "has_composition": False,
            },
            "redacted_field_count": 1,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_probe_transports_handles_a2a_without_catch_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_probe_a2a(*, service: str, endpoint: str):
        return UCPTransportProbe(
            service=service,
            transport="a2a",
            endpoint=endpoint,
            reachable=True,
            negotiated=True,
        )

    monkeypatch.setattr("app.services.ucp_audit.protocol_checks._probe_a2a", fake_probe_a2a)
    manifest = UCPManifestResult(
        transport_entries=[
            {
                "service": "dev.ucp.shopping",
                "transport": "a2a",
                "endpoint": "https://example.com/a2a",
            }
        ]
    )

    probes = await probe_transports(manifest)

    assert probes[0].transport == "a2a"
    assert probes[0].error != "missing schema or endpoint"
