from __future__ import annotations

import pytest

from app.extraction.collectors._helpers import evidence
from app.extraction.contracts import (
    CaptureBundle,
    EntityHint,
    RequestContext,
    SourceLocator,
)

pytestmark = pytest.mark.unit


def _bundle() -> CaptureBundle:
    return CaptureBundle(
        schema_version="capture.v1",
        bundle_id="bundle-1",
        run_id=1,
        requested_url="https://example.test/product",
        final_url="https://example.test/product",
        request_context=RequestContext(context_id="ctx-1"),
        artifacts=(),
        acquisition_outcome="success",
    )


def test_variant_evidence_declares_product_ownership_relation() -> None:
    item = evidence(
        _bundle(),
        "artifact-1",
        "test",
        "variant.sku",
        "SKU-1",
        SourceLocator(kind="json_pointer", value="/hasVariant/0/sku"),
        hint=EntityHint(entity_type="variant", sku="SKU-1"),
        subject_id="variant-1",
        parent_subject_id="product-1",
        parent_scope="product",
    )
    assert item.subject_scope == "variant"
    assert item.relation_type == "product_variant"


def test_offer_can_explicitly_belong_to_variant() -> None:
    item = evidence(
        _bundle(),
        "artifact-1",
        "test",
        "offer.price",
        "10.00",
        SourceLocator(kind="json_pointer", value="/hasVariant/0/offers/0/price"),
        hint=EntityHint(entity_type="offer"),
        subject_id="offer-1",
        parent_subject_id="variant-1",
        parent_scope="variant",
    )
    assert item.subject_scope == "offer"
    assert item.relation_type == "variant_offer"


def test_asset_defaults_to_product_asset_relation() -> None:
    item = evidence(
        _bundle(),
        "artifact-1",
        "test",
        "asset.image_url",
        "https://example.test/image.jpg",
        SourceLocator(kind="json_pointer", value="/image/0"),
        hint=EntityHint(entity_type="asset"),
        parent_subject_id="product-1",
        parent_scope="product",
    )
    assert item.subject_scope == "asset"
    assert item.relation_type == "product_asset"


def test_canonicalized_values_share_evidence_and_subject_ids() -> None:
    bundle = _bundle()
    first = evidence(
        bundle,
        "artifact-1",
        "test",
        "offer.availability",
        "https://schema.org/InStock",
        SourceLocator(kind="json_pointer", value="/offers/availability"),
        hint=EntityHint(entity_type="offer"),
        parent_subject_id="product-1",
        parent_scope="product",
    )
    second = evidence(
        bundle,
        "artifact-1",
        "test",
        "offer.availability",
        "in_stock",
        SourceLocator(kind="json_pointer", value="/offers/availability"),
        hint=EntityHint(entity_type="offer"),
        parent_subject_id="product-1",
        parent_scope="product",
    )

    assert first.value == second.value == "in_stock"
    assert first.evidence_id == second.evidence_id
    assert first.subject_id == second.subject_id


def test_fact_scope_overrides_conflicting_hint_for_relation_derivation() -> None:
    item = evidence(
        _bundle(),
        "artifact-1",
        "test",
        "offer.price",
        "10.00",
        SourceLocator(kind="json_pointer", value="/hasVariant/0/offers/0/price"),
        hint=EntityHint(entity_type="variant"),
        parent_subject_id="variant-1",
        parent_scope="variant",
    )

    assert item.subject_scope == "offer"
    assert item.relation_type == "variant_offer"


def test_unknown_parent_scope_does_not_invent_product_relation() -> None:
    item = evidence(
        _bundle(),
        "artifact-1",
        "test",
        "asset.image_url",
        "https://example.test/image.jpg",
        SourceLocator(kind="json_pointer", value="/image/0"),
        hint=EntityHint(entity_type="asset"),
        parent_subject_id="unknown-parent",
    )

    assert item.subject_scope == "asset"
    assert item.relation_type is None
