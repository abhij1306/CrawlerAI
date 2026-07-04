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
    metadata: dict[str, object] | None = None,
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
        metadata=metadata or {},
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


def test_matching_sku_allows_different_url_resources_to_merge() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "one", "product.url", "https://shop.test/products/item-red"),
        _row(bundle, "one", "product.sku", "ITEM-1"),
        _row(bundle, "two", "product.url", "https://shop.test/products/item-blue"),
        _row(bundle, "two", "product.sku", "item-1"),
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


def test_url_only_title_overlap_does_not_merge_sibling_brand_product() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "url", "product.url", "https://shop.test/products/nike-air-max-90", collector_id="url"),
        _row(bundle, "url", "product.title", "Nike Air Max 90", collector_id="url"),
        _row(bundle, "sibling", "product.title", "Nike Dunk Low"),
        _row(bundle, "sibling", "product.brand", "Nike"),
    )

    products = _link_products(rows)

    assert len(products) == 2


def test_jsonld_node_path_difference_does_not_block_url_title_merge() -> None:
    bundle = _bundle()
    rows = (
        _row(
            bundle,
            "script-one",
            "product.title",
            "Trail Shoe",
            metadata={"jsonld_node_path": "/@graph/0"},
        ),
        _row(
            bundle,
            "script-one",
            "product.url",
            "https://shop.test/products/trail-shoe",
            metadata={"jsonld_node_path": "/@graph/0"},
        ),
        _row(
            bundle,
            "script-two",
            "product.title",
            "Trail Shoe",
            metadata={"jsonld_node_path": "/@graph/3"},
        ),
        _row(
            bundle,
            "script-two",
            "product.url",
            "https://shop.test/products/trail-shoe",
            metadata={"jsonld_node_path": "/@graph/3"},
        ),
        _row(
            bundle,
            "script-two",
            "product.brand",
            "Invoro",
            metadata={"jsonld_node_path": "/@graph/3"},
        ),
    )

    products = _link_products(rows)

    assert len(products) == 1


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


def test_explicit_parent_source_subject_alias_links_variant_without_parent_subject() -> (
    None
):
    bundle = _bundle()
    rows = (
        _row(
            bundle, "product-source", "product.url", "https://shop.test/products/item"
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.sku",
            "SKU-1",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/sku"),
            hint=EntityHint(entity_type="variant", sku="SKU-1"),
            subject_id="variant-1",
            parent_source_subject_ids=("product-source",),
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.option.size",
            "M",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/size"),
            hint=EntityHint(entity_type="variant", sku="SKU-1"),
            subject_id="variant-1",
            parent_source_subject_ids=("product-source",),
        ),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.variants) == 1
    assert entities.variants[0].product_entity_id == entities.products[0].entity_id


def test_evidence_normalizes_ids_and_falls_back_from_invalid_explicit_brand_role() -> (
    None
):
    bundle = _bundle()
    row = evidence(
        bundle,
        "artifact-1",
        "js_state",
        "product.brand",
        "Acme",
        SourceLocator(kind="script_path", value="/product/brand"),
        brand_role="not-a-role",
        metadata={"brand_role": "vendor"},
        source_subject_ids=(" source-a ",),
        parent_source_subject_ids=(" parent-a ",),
        relation_evidence_ids=(" relation-a ",),
    )

    assert row.brand_role == "vendor"
    assert row.source_subject_ids == ("source-a",)
    assert row.parent_source_subject_ids == ("parent-a",)
    assert row.relation_evidence_ids == ("relation-a",)


def test_metadata_parent_alias_is_trimmed_before_linking() -> None:
    bundle = _bundle()
    rows = (
        _row(
            bundle, "product-source", "product.url", "https://shop.test/products/item"
        ),
        evidence(
            bundle,
            "artifact-1",
            "legacy",
            "variant.sku",
            "SKU-1",
            SourceLocator(kind="json_pointer", value="/variant/sku"),
            hint=EntityHint(entity_type="variant", sku="SKU-1"),
            subject_id="variant-1",
            metadata={"parent_source_subject_ids": [" product-source "]},
        ),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.variants) == 1
