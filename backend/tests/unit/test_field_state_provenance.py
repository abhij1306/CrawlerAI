"""Phase 0.1 — field states are derived from the resolution decision graph.

A field suppressed by publication policy must read as ``captured_but_rejected``
*with a reason*, never as
``not_present_in_captured_sources`` ("no candidate collected"). A field with no
collected candidate stays ``not_present``; a published field is
``captured_and_resolved``.
"""

from __future__ import annotations

import pytest

from app.core.config import field_mappings
from app.extraction.contracts import CommerceDetailRecord, Decision
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.result_building import field_evidence_states
from app.extraction.surfaces import Surface

pytestmark = pytest.mark.unit

_PRODUCT_ID = "product:1"
_OFFER_ID = "offer:1"


def _request():
    return fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<main><h1>A Real Title</h1></main>",
        "https://shop.test/products/a-real-title",
        requested_fields=("title", "price", "sku"),
    )


def _resolved_price_decision() -> Decision:
    # Resolution accepted a price, but its evidence row is absent from the
    # captured evidence passed below — i.e. the value was stripped downstream.
    return Decision(
        decision_id="decision:price",
        entity_id=_OFFER_ID,
        fact_type=field_mappings.OFFER_PRICE_FACT_TYPE,
        accepted_evidence_ids=("ev-stripped",),
        rejected=(),
        finding_ids=(),
        rule_id="SCALAR_LEXICOGRAPHIC",
        status="resolved",
    )


def test_resolved_but_stripped_field_is_rejected_with_reason() -> None:
    record = CommerceDetailRecord(
        url="https://shop.test/products/a-real-title",
        title="A Real Title",
    )
    states = {
        row.field: row
        for row in field_evidence_states(
            (record,),
            (),  # no captured evidence rows for price -> rows branch is empty
            (_resolved_price_decision(),),
            _request(),
            primary_product_entity_id=_PRODUCT_ID,
            primary_offer_entity_id=_OFFER_ID,
        )
    }

    # Resolution owned a price; it is absent from the record => rejected, not
    # "no candidate collected", and the state carries a reason.
    assert states["price"].state == "captured_but_rejected"
    assert states["price"].reason_codes
    assert states["price"].state != "not_present_in_captured_sources"


def test_published_field_is_captured_and_resolved() -> None:
    record = CommerceDetailRecord(
        url="https://shop.test/products/a-real-title",
        title="A Real Title",
    )
    states = {
        row.field: row
        for row in field_evidence_states(
            (record,),
            (),
            (),
            _request(),
            primary_product_entity_id=_PRODUCT_ID,
            primary_offer_entity_id=_OFFER_ID,
        )
    }
    assert states["title"].state == "captured_and_resolved"


def test_no_candidate_field_is_not_present() -> None:
    record = CommerceDetailRecord(
        url="https://shop.test/products/a-real-title",
        title="A Real Title",
    )
    states = {
        row.field: row
        for row in field_evidence_states(
            (record,),
            (),
            (),
            _request(),
            primary_product_entity_id=_PRODUCT_ID,
            primary_offer_entity_id=_OFFER_ID,
        )
    }
    # No evidence, no decision, not in the record.
    assert states["sku"].state == "not_present_in_captured_sources"
    assert states["sku"].reason_codes == ()
