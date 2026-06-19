from __future__ import annotations

import pytest

from app.services.extraction import Surface, extract
from app.services.extraction.replay import fixture_request_from_inputs
from app.services.pipeline.persistence import build_extraction_decision_payload


pytestmark = pytest.mark.unit


def test_extraction_result_is_the_canonical_persistence_payload() -> None:
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            """
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "Trail Shoe",
              "url": "https://shop.test/products/trail-shoe",
              "offers": {
                "@type": "Offer",
                "price": "129",
                "priceCurrency": "USD"
              }
            }
            </script>
            """,
            "https://shop.test/products/trail-shoe",
        )
    )

    payload = build_extraction_decision_payload(
        result=result,
        persisted_count=1,
    )

    assert payload["verdict"] == result.verdict
    assert payload["records"]
    assert payload["evidence"]
    assert payload["decisions"]
    assert payload["persisted_count"] == 1
    assert "replay" not in payload
