# ruff: noqa: F401
from __future__ import annotations

from collections.abc import Mapping
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.acquisition import variant_endpoint_expansion
from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.browser_block_detection import classify_blocked_page
from app.acquisition.browser_listing_visual import listing_visual_elements_html
from app.acquisition.browser_result_builder import build_browser_artifacts
from app.acquisition.runtime_plan import AcquisitionIntent
from app.acquisition.source_capabilities import build_source_capability_diagnostics
from app.core.config import variant_policy
from app.core.config.variant_policy import canonical_variant_axis
from app.core.records import structured_variant_state
from app.crawl.pipeline import record_extraction_stage
from app.core.shared.url_utils import structured_extensionless_image_url
from app.extraction import Surface, extract
from app.extraction.collectors._helpers import evidence
from app.extraction.engine import _assess, _blocked_result
from app.extraction.contracts import (
    CommerceDetailRecord,
    EntityHint,
    ExtractionRequest,
    Finding,
    PublicRecord,
    SourceLocator,
    TargetSelection,
)
from app.extraction.contracts import Evidence
from app.core.config.extraction_rules import (
    MAX_DIAGNOSTIC_EXAMPLES_PER_REASON,
    MAX_EVIDENCE_PER_SOURCE_OBJECT,
    PRODUCT_ASSET_EXTENSIONLESS_PATH_PATTERN,
)
from app.extraction.replay import (
    fixture_request_from_inputs,
    request_from_acquisition_result,
)

pytestmark = pytest.mark.unit


HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Trail Shoe",
  "brand": {"@type": "Brand", "name": "Invoro"},
  "description": "A durable trail shoe for long-distance runs.",
  "sku": "TS-1",
  "url": "https://shop.test/products/trail-shoe",
  "image": ["https://shop.test/i/trail.jpg"],
  "offers": {
    "@type": "Offer",
    "price": "129",
    "priceCurrency": "usd",
    "availability": "https://schema.org/InStock"
  },
  "hasVariant": [
    {"@type": "Product", "sku": "TS-1-BLK-9", "color": "Black", "size": "9"}
  ]
}
</script>
</head>
<body><main><h1>Trail Shoe</h1></main></body>
</html>
"""


def _extract(
    surface: str,
    html: str,
    page_url: str,
    *,
    max_records: int = 1,
    artifacts: Mapping[str, object] | None = None,
    network_payloads: tuple[dict[str, object], ...] = (),
    requested_fields: tuple[str, ...] = (),
):
    return extract(
        fixture_request_from_inputs(
            Surface(surface),
            html,
            page_url,
            max_records=max_records,
            artifacts=dict(artifacts) if artifacts is not None else None,
            network_payloads=list(network_payloads),
            requested_fields=requested_fields,
        )
    )


def _price_repair_facts(result, rule_id: str):
    return tuple(
        fact
        for fact in result.derived_facts
        if fact.fact_type == "offer.price" and fact.rule_id == rule_id
    )


def _group_facts_by_group_id(rows: list[Evidence]) -> dict[str, set[str]]:
    return {
        group_id: {row.fact_type for row in rows if row.group_id == group_id}
        for group_id in {row.group_id for row in rows if row.group_id}
    }


# Split suites share the original fixture vocabulary. Keep test bodies focused.
__all__ = [name for name in globals() if not name.startswith("__")]
