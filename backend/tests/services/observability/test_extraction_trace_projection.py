from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.extraction import Surface, extract
from app.extraction.replay import fixture_request_from_inputs
from app.core.config import observability as obs_config
from app.observability.run_trace import RunTrace
from app.crawl.pipeline.extraction_loop import (
    _record_acquire_timeline,
    _record_extraction_trace,
)


pytestmark = pytest.mark.unit


def _result():
    return extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            """
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "Widget",
              "url": "https://example.com/p/widget",
              "offers": {
                "@type": "Offer",
                "price": "49.99",
                "priceCurrency": "USD"
              }
            }
            </script>
            """,
            "https://example.com/p/widget",
        )
    )


def test_projects_canonical_extraction_metrics() -> None:
    result = _result()
    trace = RunTrace(
        run_id=1,
        url="https://example.com/p/widget",
        surface="ecommerce_detail",
        requested_fields=["price"],
    )

    _record_extraction_trace(SimpleNamespace(trace=trace), result)

    summary = trace.to_dict()["extraction"]["evidence_summary"]
    assert summary["candidate_count"] == result.metrics.evidence_count
    assert summary["field_decision_count"] == len(result.decisions)
    assert summary["validation_finding_count"] == len(result.findings)


def test_noop_when_context_has_no_trace() -> None:
    _record_extraction_trace(SimpleNamespace(), _result())


def test_projects_each_canonical_http_attempt_into_run_trace() -> None:
    trace = RunTrace(
        run_id=1,
        url="https://example.com/p/widget",
        surface="ecommerce_detail",
        requested_fields=["price"],
    )
    acquisition_result = SimpleNamespace(
        method="httpx",
        status_code=200,
        blocked=False,
        browser_diagnostics={},
        acquisition_diagnostics={
            "result": {
                "selected_attempt_id": "attempt-2",
                "attempts": [
                    {
                        "attempt_id": "attempt-1",
                        "outcome": "error",
                        "status_code": None,
                        "error": "ConnectTimeout: curl timed out",
                        "diagnostics": {
                            "transport": "curl",
                            "proxy": "direct",
                            "duration_ms": 9,
                        },
                    },
                    {
                        "attempt_id": "attempt-2",
                        "outcome": "success",
                        "status_code": 200,
                        "error": None,
                        "diagnostics": {
                            "transport": "httpx",
                            "method": "httpx",
                            "proxy": "direct",
                            "duration_ms": 12,
                        },
                    },
                ],
            }
        },
    )

    _record_acquire_timeline(SimpleNamespace(trace=trace), acquisition_result)

    timeline = trace.to_dict()["acquire_timeline"]
    assert [event["kind"] for event in timeline] == [
        obs_config.ACQUIRE_EVENT_HTTP_FETCH,
        obs_config.ACQUIRE_EVENT_HTTP_FETCH,
    ]
    assert [event["detail"]["outcome"] for event in timeline] == [
        "error",
        "success",
    ]
    assert [event["detail"]["selected"] for event in timeline] == [False, True]
    assert [event["duration_ms"] for event in timeline] == [9, 12]
