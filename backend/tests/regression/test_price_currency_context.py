from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from app.services.acquisition.browser_capture import BrowserNetworkCapture
from app.services.acquisition.runtime import NetworkPayloadReadResult
from app.services.extract.detail.validation import validate_price_currency
from app.services.extract.variant_normalization import backfill


@pytest.mark.regression
def test_root_variant_currency_contradiction_creates_finding() -> None:
    record = {
        "currency": "USD",
        "variants": [
            {"size": "S", "price": "10", "currency": "CAD"},
            {"size": "M", "price": "12", "currency": "CAD"},
        ],
    }

    findings = validate_price_currency(record)

    assert [finding["rule_id"] for finding in findings] == [
        "CURRENCY_CONTRADICTION",
        "CURRENCY_CONTRADICTION",
    ]
    assert findings[0]["severity"] == "high"
    assert findings[0]["field_name"] == "currency"


@pytest.mark.regression
def test_currency_enforcement_records_validation_finding_without_dropping_variants() -> None:
    record = {
        "currency": "INR",
        "variants": [
            {"size": "S", "currency": "USD", "price": "10"},
            {"size": "M", "currency": "EUR", "price": "12"},
        ],
    }

    backfill._enforce_variant_currency_context(record)

    assert record["variants"] == [
        {"size": "S", "currency": "USD", "price": "10"},
        {"size": "M", "currency": "EUR", "price": "12"},
    ]
    assert {finding["rule_id"] for finding in validate_price_currency(record)} == {
        "CURRENCY_CONTRADICTION"
    }


@pytest.mark.asyncio
@pytest.mark.regression
async def test_network_payload_retains_safe_request_context_for_currency_review() -> None:
    body = b'{"price":"10","currency":"USD"}'
    request = SimpleNamespace(
        method="POST",
        headers={"accept-language": "en-US", "authorization": "secret"},
        resource_type="xhr",
        frame=SimpleNamespace(url="https://example.com/products/widget"),
    )
    response = SimpleNamespace(
        url="https://example.com/api/product",
        status=200,
        headers={
            "content-type": "application/json",
            "content-language": "en-US",
            "set-cookie": "secret",
        },
        request=request,
    )

    async def _read_body(*_args, **_kwargs) -> NetworkPayloadReadResult:
        return NetworkPayloadReadResult(body=body, outcome="ok")

    capture = BrowserNetworkCapture(
        surface="ecommerce_detail",
        should_capture_payload=lambda **_kwargs: True,
        classify_endpoint=lambda **_kwargs: {"type": "api", "family": "generic"},
        read_payload_body=_read_body,
    )
    await capture._capture_response(response)
    summary = await capture.close(SimpleNamespace(remove_listener=None))

    payload = summary.payloads[0]
    assert payload["request_headers"] == {"accept-language": "en-US"}
    assert payload["response_headers"] == {
        "content-type": "application/json",
        "content-language": "en-US",
    }
    assert payload["body_sha256"] == hashlib.sha256(body).hexdigest()
    assert payload["resource_type"] == "xhr"
    assert payload["frame_url"] == "https://example.com/products/widget"
