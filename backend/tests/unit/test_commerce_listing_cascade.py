"""Slice 1: commerce-listing cascade seam (structured -> network -> DOM).

Pins the deterministic, selector-free listing cascade for the commerce-listing
surface: with the enable flag ON, a structured (JSON-LD) capture yields records
via the structured floor, a DOM-only capture yields records via the DOM floor,
and the cascade always reports its floors in structured -> network -> DOM
order. No model is invoked on any path.
"""

from __future__ import annotations

import pytest

from app.extraction.cascade import (
    LISTING_FLOOR_ORDER,
    run_listing_cascade,
)
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface, listing_schema

pytestmark = pytest.mark.unit

PAGE = "https://shop.test/c/dresses/"

_STRUCTURED_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
  {"@type":"ListItem","url":"https://shop.test/p/aida-1001.html",
   "item":{"@type":"Product","name":"Aida Dress",
     "offers":{"@type":"Offer","price":"119.00"},"image":"https://img.test/a.jpg"}},
  {"@type":"ListItem","url":"https://shop.test/p/mira-1002.html",
   "item":{"@type":"Product","name":"Mira Dress",
     "offers":{"@type":"Offer","price":"99.00"}}}
]}
</script></head>
<body><div class="grid">
  <div class="card"><a href="/p/aida-1001.html"><img src=x></a><span>$119</span></div>
  <div class="card"><a href="/p/mira-1002.html"><img src=x></a><span>$99</span></div>
</div></body></html>
"""

_DOM_ONLY_HTML = """
<html><body><main>
  <article class="product-card">
    <a href="/products/trail-shoe"><h2>Trail Shoe</h2></a>
    <span class="price">$129.00</span>
    <img src="/images/trail.jpg">
  </article>
  <article class="product-card">
    <a href="/products/day-pack"><h2>Day Pack</h2></a>
    <span class="price">$89.00</span>
    <img src="/images/day-pack.jpg">
  </article>
</main></body></html>
"""


def _run(html: str, *, page_url: str = PAGE):
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_LISTING,
        html,
        page_url,
        max_records=10,
    )
    schema = listing_schema(Surface.ECOMMERCE_LISTING)
    assert schema is not None
    return run_listing_cascade(request, request.artifact_reader, schema)


def test_structured_floor_produces_records_with_zero_model_calls() -> None:
    result = _run(_STRUCTURED_HTML)
    assert result.evidence
    collectors = {row.collector_id for row in result.evidence}
    assert collectors == {"listing_structured_floor"}
    titles = {row.value for row in result.evidence if row.fact_type == "product.title"}
    assert titles == {"Aida Dress", "Mira Dress"}
    # No model collector ever appears in a deterministic floor run.
    assert not any("model" in cid or "llm" in cid for cid in collectors)


def test_dom_floor_produces_records_when_no_structured_source() -> None:
    result = _run(_DOM_ONLY_HTML)
    assert result.evidence
    collectors = {row.collector_id for row in result.evidence}
    # The DOM floor reuses the commerce card collector for admissibility rules.
    assert collectors <= {"listing_dom_floor", "ecommerce_listing_css"}
    titles = {row.value for row in result.evidence if row.fact_type == "product.title"}
    assert titles == {"Trail Shoe", "Day Pack"}
    assert not any("model" in cid or "llm" in cid for cid in collectors)


def test_cascade_reports_floors_in_structured_network_dom_order() -> None:
    result = _run(_STRUCTURED_HTML)
    assert result.floor_order == ("structured", "network", "dom")
    assert LISTING_FLOOR_ORDER == ("structured", "network", "dom")
    reported = tuple(outcome.collector_id for outcome in result.collector_outcomes)
    assert reported == (
        "listing_structured_floor",
        "listing_network_floor",
        "listing_dom_floor",
    )
    # The structured floor is the one that produced evidence here.
    by_id = {o.collector_id: o.outcome for o in result.collector_outcomes}
    assert by_id["listing_structured_floor"] == "produced_evidence"
    # Floors after the winner are never executed — reported as skipped.
    assert by_id["listing_network_floor"] == "skipped"
    assert by_id["listing_dom_floor"] == "skipped"
