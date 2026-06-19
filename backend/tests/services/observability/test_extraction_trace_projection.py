from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.extraction import Surface, extract
from app.extraction.replay import fixture_request_from_inputs
from app.observability.run_trace import RunTrace
from app.crawl.pipeline.extraction_loop import _record_extraction_trace


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
