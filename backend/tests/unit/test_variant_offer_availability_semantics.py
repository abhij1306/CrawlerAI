from __future__ import annotations

import pytest

from app.core.records.output_safety import public_availability
from app.extraction.collectors._helpers import evidence
from app.extraction.contracts import (
    CaptureBundle,
    EntityHint,
    RequestContext,
    SourceLocator,
)
from app.extraction.entities import build_entities
from app.extraction.validation import validate

pytestmark = pytest.mark.unit


def _bundle() -> CaptureBundle:
    return CaptureBundle(
        schema_version="capture.v1",
        bundle_id="bundle-slices-7-9",
        run_id=1,
        requested_url="https://shop.test/products/item",
        final_url="https://shop.test/products/item",
        request_context=RequestContext(context_id="ctx-slices-7-9"),
        artifacts=(),
        acquisition_outcome="success",
    )


def _product(bundle: CaptureBundle):
    return evidence(
        bundle,
        "artifact-1",
        "jsonld",
        "product.url",
        bundle.final_url,
        SourceLocator(kind="json_pointer", value="/product/url"),
        hint=EntityHint(entity_type="product", url=bundle.final_url),
        subject_id="product-1",
    )


def test_option_inventory_without_sellable_identity_is_not_variant() -> None:
    bundle = _bundle()
    rows = (
        _product(bundle),
        evidence(
            bundle,
            "artifact-1",
            "dom",
            "variant.option.size",
            "S M L XL",
            SourceLocator(kind="css_selector", value=".sizes"),
            hint=EntityHint(entity_type="variant"),
            subject_id="variant-options",
            parent_subject_id="product-1",
        ),
    )

    entities = build_entities(bundle, rows)

    assert entities.variants == ()


def test_real_variant_with_sku_remains_variant() -> None:
    bundle = _bundle()
    rows = (
        _product(bundle),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.sku",
            "SKU-S",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/sku"),
            hint=EntityHint(entity_type="variant", sku="SKU-S"),
            subject_id="variant-s",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.option.size",
            "S",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/size"),
            hint=EntityHint(entity_type="variant", sku="SKU-S"),
            subject_id="variant-s",
            parent_subject_id="product-1",
        ),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.variants) == 1
    assert entities.variants[0].identity_key == "sku:SKU-S"


def test_mixed_product_and_variant_offer_ownership_is_rejected() -> None:
    bundle = _bundle()
    rows = (
        _product(bundle),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.sku",
            "SKU-S",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/sku"),
            hint=EntityHint(entity_type="variant", sku="SKU-S"),
            subject_id="variant-s",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "offer.price",
            "10.00",
            SourceLocator(kind="json_pointer", value="/offers/0/price"),
            hint=EntityHint(entity_type="offer"),
            group_id="offer-1",
            subject_id="offer-1",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "offer.currency",
            "USD",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/offers/0/currency"),
            hint=EntityHint(entity_type="offer"),
            group_id="offer-1",
            subject_id="offer-1",
            parent_subject_id="variant-s",
            parent_scope="variant",
        ),
    )

    entities = build_entities(bundle, rows)
    findings = validate(rows, entities)

    assert entities.offers == ()
    assert any(item.rule_id == "OFFER_RELATION_CONFLICT" for item in findings)


def test_availability_is_canonicalized_with_raw_provenance_retained() -> None:
    bundle = _bundle()
    item = evidence(
        bundle,
        "artifact-1",
        "jsonld",
        "offer.availability",
        "https://schema.org/InStock",
        SourceLocator(kind="json_pointer", value="/offers/availability"),
        hint=EntityHint(entity_type="offer"),
        parent_subject_id="product-1",
    )

    assert item.raw_value == "https://schema.org/InStock"
    assert item.value == "in_stock"


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("LimitedAvailability", "limited_stock"),
        ("low_stock", "limited_stock"),
        ("PreOrder", "preorder"),
        ("BackOrder", "backorder"),
        ("Discontinued", "discontinued"),
    ),
)
def test_supported_availability_states_share_canonical_semantics(
    raw: str, expected: str
) -> None:
    bundle = _bundle()
    item = evidence(
        bundle,
        "artifact-1",
        "jsonld",
        "offer.availability",
        raw,
        SourceLocator(kind="json_pointer", value="/offers/availability"),
        hint=EntityHint(entity_type="offer"),
        parent_subject_id="product-1",
    )

    assert item.raw_value == raw
    assert item.value == expected
    assert public_availability(item.value) == expected
    assert public_availability(raw) == ""
