from __future__ import annotations

import pytest

from app.extraction.collectors._helpers import evidence
from app.extraction.contracts import (
    CaptureBundle,
    EntityHint,
    RequestContext,
    SourceLocator,
)
from app.extraction.entities import _link_products, _owner_product_id, build_entities

pytestmark = pytest.mark.unit


def _bundle() -> CaptureBundle:
    return CaptureBundle(
        schema_version="capture.v1",
        bundle_id="bundle-conflict-linking",
        run_id=1,
        requested_url="https://shop.test/products/item",
        final_url="https://shop.test/products/item",
        request_context=RequestContext(context_id="ctx-conflict-linking"),
        artifacts=(),
        acquisition_outcome="success",
    )


def _row(
    bundle: CaptureBundle,
    subject: str,
    fact_type: str,
    value: str,
    *,
    collector_id: str = "jsonld",
):
    return evidence(
        bundle,
        "artifact-1",
        collector_id,
        fact_type,
        value,
        SourceLocator(kind="json_pointer", value=f"/{subject}/{fact_type}"),
        hint=EntityHint(entity_type="product"),
        subject_id=subject,
    )


def test_same_title_with_different_urls_and_skus_remains_separate() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "one", "product.title", "Classic Cap"),
        _row(bundle, "one", "product.url", "https://shop.test/products/cap-one"),
        _row(bundle, "one", "product.sku", "CAP-ONE"),
        _row(bundle, "two", "product.title", "Classic Cap"),
        _row(bundle, "two", "product.url", "https://shop.test/products/cap-two"),
        _row(bundle, "two", "product.sku", "CAP-TWO"),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.products) == 2


def test_canonical_url_and_matching_sku_merge_product_subjects() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "one", "product.url", "https://shop.test/products/item?variant=1"),
        _row(bundle, "one", "product.sku", "ITEM-1"),
        _row(bundle, "two", "product.url", "https://shop.test/products/item"),
        _row(bundle, "two", "product.sku", "item-1"),
        _row(bundle, "two", "product.title", "Item"),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.products) == 1


def test_shared_url_does_not_merge_conflicting_skus() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "one", "product.url", "https://shop.test/products/item"),
        _row(bundle, "one", "product.sku", "ITEM-A"),
        _row(bundle, "two", "product.url", "https://shop.test/products/item?variant=2"),
        _row(bundle, "two", "product.sku", "ITEM-B"),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.products) == 2


def test_url_collector_fallback_only_merges_matching_resource() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "main", "product.title", "Item"),
        _row(bundle, "main", "product.url", "https://shop.test/products/item"),
        _row(
            bundle,
            "url-only",
            "product.url",
            "https://shop.test/products/other",
            collector_id="url",
        ),
    )

    products = _link_products(rows)

    assert len(products) == 2


def test_owner_product_id_rejects_conflicting_parent_products() -> None:
    bundle = _bundle()
    rows = [
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.sku",
            "SKU-1",
            SourceLocator(kind="json_pointer", value="/a/sku"),
            hint=EntityHint(entity_type="variant", sku="SKU-1"),
            subject_id="variant-1",
            parent_subject_id="product-a",
            parent_scope="product",
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.url",
            "https://shop.test/products/item?variant=1",
            SourceLocator(kind="json_pointer", value="/b/url"),
            hint=EntityHint(entity_type="variant", sku="SKU-1"),
            subject_id="variant-1",
            parent_subject_id="product-b",
            parent_scope="product",
        ),
    ]

    owner = _owner_product_id(
        rows,
        {"product-a": "entity-a", "product-b": "entity-b"},
        allowed_relations=frozenset({"product_variant"}),
    )

    assert owner is None
